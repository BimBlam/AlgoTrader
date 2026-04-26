"""
algotrader.backtest/main.py

Entry point for the S4 Backtest Validator process.

Changes from audit:
  - Calls get_backtest_config() at startup for eager Pydantic validation
  - Reads config_hash from the jobs table row (captured at job-creation time)
    so backtest identity matches the config that was in effect when S1 queued
    the run, not whatever is live when S4 executes
  - Derives strategy label from enabled strategy flags in config
  - Checks backtest_runs for an identical prior run and warns before proceeding
"""

# =============================================================================
# REQUIREMENTS (subset of global requirements.txt)
# arch             >= 6.3
# numpy            >= 1.26
# pandas           >= 2.2
# pyarrow          >= 15.0
# scipy            >= 1.12
# statsmodels      >= 0.14
# sqlalchemy       >= 2.0
# pydantic         >= 2.0
# structlog        >= 24.0
# =============================================================================

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

from sqlalchemy import select

from algotrader.backtest.bootstrap import run_stationary_bootstrap
from algotrader.backtest.config_schema import get_backtest_config
from algotrader.backtest.costs import TransactionCostModel
from algotrader.backtest.cscv import compute_cscv_pbo
from algotrader.backtest.loader import load_returns_history
from algotrader.backtest.metrics import deflated_sharpe_ratio
from algotrader.backtest.monte_carlo import run_monte_carlo
from algotrader.backtest.permutation import run_permutation_battery
from algotrader.backtest.walk_forward import run_walk_forward
from algotrader.backtest.writer import write_backtest_record, write_event
from algotrader.shared.config_loader import get_config
from algotrader.shared.constants import EventType, Severity
from algotrader.shared.db import get_session, init_db
from algotrader.shared.exceptions import BacktestError, DataError
from algotrader.shared.logger import get_logger
from algotrader.shared.models import BacktestRun, Job

log = get_logger(__name__)

MIN_TRADING_DAYS = 252


def run(run_id: str) -> None:
    """
    Primary entry point invoked by S1.

    Parameters
    ----------
    run_id:
        UUID string matching a RUNBACKTEST row in the `jobs` table.
    """
    cfg = get_config()
    init_db(cfg.system.db_url)

    # Validate backtest config eagerly so bad values surface before any work
    try:
        bt_cfg = get_backtest_config(cfg)
    except BacktestError as exc:
        log.error("backtest_config_invalid", run_id=run_id, error=str(exc))
        with get_session() as session:
            write_event(session, EventType.BACKTEST_FAILED, Severity.ERROR,
                        "S4", run_id, f"Invalid backtest config: {exc}")
        sys.exit(1)

    log.info("backtest_validator_start", run_id=run_id)

    # Pull config_hash from the jobs row — this is the hash captured at
    # job-creation time, which may differ from cfg if config changed since.
    job_config_hash = _read_job_config_hash(run_id)

    try:
        returns_df = load_returns_history(cfg)
    except DataError as exc:
        log.error("backtest_load_failed", run_id=run_id, error=str(exc))
        with get_session() as session:
            write_event(session, EventType.BACKTEST_FAILED, Severity.ERROR,
                        "S4", run_id, "Failed to load returns history",
                        {"error": str(exc)})
        sys.exit(1)

    n_days = len(returns_df.index.get_level_values("date").unique())
    if n_days < MIN_TRADING_DAYS:
        msg = (f"Insufficient history: {n_days} trading days "
               f"(minimum {MIN_TRADING_DAYS})")
        log.error("backtest_insufficient_history", run_id=run_id, n_days=n_days)
        with get_session() as session:
            write_event(session, EventType.BACKTEST_FAILED, Severity.ERROR,
                        "S4", run_id, msg,
                        {"n_days": n_days, "minimum": MIN_TRADING_DAYS})
        sys.exit(1)

    try:
        _execute_backtest(cfg, bt_cfg, run_id, job_config_hash, returns_df)
    except Exception as exc:
        log.error("backtest_unexpected_error", run_id=run_id, error=str(exc))
        with get_session() as session:
            write_event(session, EventType.BACKTEST_FAILED, Severity.ERROR,
                        "S4", run_id, f"Unexpected backtest error: {exc}",
                        {"error": str(exc)})
        sys.exit(1)


def _execute_backtest(cfg, bt_cfg, run_id: str, job_config_hash: str,
                      returns_df) -> None:
    """
    Orchestrate all validation stages and persist results.

    Separated from `run` so each stage failure is still caught by the
    top-level handler there.
    """
    cost_model = TransactionCostModel(cfg)
    strategy = _derive_strategy(cfg)
    date_range = returns_df.index.get_level_values("date").unique()
    date_start = date_range.min()
    date_end = date_range.max()

    # Warn if an identical run already exists — do not block, per spec §6.2
    _check_for_duplicate_run(job_config_hash, date_start, date_end, run_id)

    log.info("backtest_stage_walk_forward", run_id=run_id)
    wf_result = run_walk_forward(returns_df, cfg, cost_model)

    log.info("backtest_stage_monte_carlo", run_id=run_id)
    mc_result = run_monte_carlo(returns_df, cfg, cost_model)

    log.info("backtest_stage_bootstrap", run_id=run_id)
    bs_result = run_stationary_bootstrap(returns_df, cfg, cost_model)

    log.info("backtest_stage_permutation", run_id=run_id)
    perm_result = run_permutation_battery(returns_df, cfg, cost_model)

    log.info("backtest_stage_cscv", run_id=run_id)
    pbo = compute_cscv_pbo(wf_result.oos_sharpe_variants)

    # Only count successful paths to avoid over-deflating DSR
    n_trials = (len(wf_result.oos_sharpe_variants)
                + len(mc_result.path_sharpes))
    dsr = deflated_sharpe_ratio(
        sharpe_obs=wf_result.oos_sharpe,
        n_trials=max(n_trials, 2),
        t=max(wf_result.oos_n_obs, 2),
        skew=wf_result.oos_skew,
        kurt=wf_result.oos_kurt,
    )

    hdd_root = Path(cfg.system.data_dir_hdd) / "backtest" / run_id
    hdd_root.mkdir(parents=True, exist_ok=True)
    _write_hdd_output(hdd_root, wf_result, mc_result, bs_result, perm_result,
                      pbo, dsr)
    result_path = str(hdd_root)

    with get_session() as session:
        write_backtest_record(
            session=session,
            run_id=run_id,
            strategy=strategy,
            config_hash=job_config_hash,
            universe_hash=getattr(cfg, "universe_hash", ""),
            code_version=_get_git_hash(),
            date_range_start=date_start,
            date_range_end=date_end,
            n_mc_paths=bt_cfg.n_mc_paths,
            include_costs=bt_cfg.include_costs,
            sharpe=wf_result.oos_sharpe,
            sortino=wf_result.oos_sortino,
            max_drawdown=wf_result.max_drawdown,
            pbo=pbo,
            deflated_sharpe=dsr,
            result_path=result_path,
        )
        write_event(
            session, EventType.BACKTEST_RESULT, Severity.INFO,
            "S4", run_id, "Backtest validation complete",
            {
                "sharpe": wf_result.oos_sharpe,
                "sortino": wf_result.oos_sortino,
                "max_drawdown": wf_result.max_drawdown,
                "pbo": pbo,
                "deflated_sharpe": dsr,
                "result_path": result_path,
            },
        )

    log.info("backtest_validator_complete", run_id=run_id,
             sharpe=wf_result.oos_sharpe, pbo=pbo, deflated_sharpe=dsr,
             result_path=result_path)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_job_config_hash(run_id: str) -> str:
    """
    Read config_hash from the jobs table row for this run_id.

    Using the job-row hash instead of the live cfg hash preserves the
    backtest identity contract from §9.2: the hash must reflect the config
    that was active when the job was queued, not when it executes.
    Falls back to empty string with a warning if the row is not found
    (should not happen in normal operation — S1 always creates the row first).
    """
    try:
        with get_session() as session:
            stmt = select(Job).where(Job.run_id == uuid.UUID(run_id))
            job = session.execute(stmt).scalar_one_or_none()
            if job is None:
                log.warning("backtest_job_row_missing", run_id=run_id)
                return ""
            return job.config_hash or ""
    except Exception as exc:
        log.warning("backtest_job_config_hash_unreadable",
                    run_id=run_id, error=str(exc))
        return ""


def _derive_strategy(cfg) -> str:
    """
    Determine the strategy label for the backtest_runs row from config.

    If exactly one strategy is enabled, use its name (STATARB, REVERSAL,
    REGIMECOMBO). If multiple are enabled, record "ALL" — the backtest
    exercises the full combined parameter set. "ALL" is a valid value for
    the dashboard diff view; it signals a system-wide validation run rather
    than a single-strategy calibration run.
    """
    enabled: list[str] = []
    try:
        if getattr(cfg.strategy_params.statarb,    "enabled", False):
            enabled.append("STATARB")
        if getattr(cfg.strategy_params.reversal,   "enabled", False):
            enabled.append("REVERSAL")
        if getattr(cfg.strategy_params.regimecombo,"enabled", False):
            enabled.append("REGIMECOMBO")
    except AttributeError:
        pass

    if len(enabled) == 1:
        return enabled[0]
    if len(enabled) > 1:
        return "ALL"

    log.warning("backtest_no_strategy_enabled_in_config")
    return "REVERSAL"   # last-resort — S3 always needs at least reversal


def _check_for_duplicate_run(config_hash: str, date_start, date_end,
                              run_id: str) -> None:
    """
    Warn if a prior backtest_runs row already has the same
    (config_hash, date_range_start, date_range_end).

    The spec lists backtest_runs as an *input* for prior run IDs. A duplicate
    does not block execution — the new run may be a forced re-validation —
    but the warning lets S1 or the dashboard surface it to the user.
    """
    try:
        with get_session() as session:
            stmt = (
                select(BacktestRun)
                .where(BacktestRun.config_hash      == config_hash)
                .where(BacktestRun.date_range_start == date_start)
                .where(BacktestRun.date_range_end   == date_end)
            )
            prior = session.execute(stmt).scalar_one_or_none()
            if prior is not None:
                log.warning(
                    "backtest_duplicate_run_detected",
                    prior_run_id=str(prior.run_id),
                    current_run_id=run_id,
                    config_hash=config_hash,
                )
    except Exception as exc:
        # Non-fatal: duplicate check must never block a run
        log.warning("backtest_duplicate_check_failed", error=str(exc))


def _get_git_hash() -> str:
    """Return the current git commit hash for backtest identity per §9.2."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def _write_hdd_output(hdd_root, wf_result, mc_result, bs_result,
                      perm_result, pbo, dsr) -> None:
    """
    Write all structured artefacts to HDD under data/backtest/<run_id>/.
    Parquet for time-series data, JSON for scalar summaries.
    """
    import pandas as pd

    if len(wf_result.oos_equity_curve) > 0:
        wf_result.oos_equity_curve.to_frame("equity").to_parquet(
            hdd_root / "oos_equity_curve.parquet")
    if len(wf_result.oos_returns) > 0:
        wf_result.oos_returns.to_frame("returns").to_parquet(
            hdd_root / "oos_returns.parquet")

    pd.DataFrame(mc_result.path_sharpes, columns=["sharpe"]).to_parquet(
        hdd_root / "mc_path_sharpes.parquet")
    pd.DataFrame(bs_result.block_sharpes, columns=["sharpe"]).to_parquet(
        hdd_root / "bootstrap_sharpes.parquet")

    mc_series = pd.Series(mc_result.path_sharpes)
    bs_series = pd.Series(bs_result.block_sharpes)

    summary = {
        "wf_sharpe":            wf_result.oos_sharpe,
        "wf_sortino":           wf_result.oos_sortino,
        "wf_max_drawdown":      wf_result.max_drawdown,
        "pbo":                  pbo,
        "deflated_sharpe":      dsr,
        "mc_sharpe_mean":       float(mc_series.mean()) if len(mc_series) else None,
        "mc_sharpe_5pct":       float(mc_series.quantile(0.05)) if len(mc_series) else None,
        "bootstrap_sharpe_mean":float(bs_series.mean()) if len(bs_series) else None,
        "permutation_p_values": perm_result.p_values,
    }
    with open(hdd_root / "summary.json", "w") as fh:
        json.dump(summary, fh, indent=2)
