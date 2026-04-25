"""
S3 Signal Engine — main entry point.

Orchestrates the full signal pipeline: load data, fit OU params,
compute signals for each active strategy, apply sentiment adjustments,
resolve per-ticker competition, persist results.
"""
# Requirements:
#   pandas>=2.0
#   numpy>=1.26
#   scipy>=1.12
#   statsmodels>=0.14
#   pyarrow>=15.0
#   sqlalchemy>=2.0
#   structlog>=24.0
#   pydantic>=2.0

import datetime
import sys

from shared.config_loader import get_config
from shared.db import get_session, init_db
from shared.logger import get_logger
from shared.exceptions import DataError, SignalError
from shared.constants import EventType, Severity

from s3_signal_engine.loaders import load_returns, load_sector_etf_returns, load_prior_ou_params, load_sentiment_scores
from s3_signal_engine.ou_model import fit_ou_params, write_ou_params
from s3_signal_engine.stat_arb import compute_stat_arb_signals
from s3_signal_engine.reversal import compute_reversal_signals
from s3_signal_engine.regime import classify_regime
from s3_signal_engine.competition import resolve_competition
from s3_signal_engine.writer import write_signals, write_event

log = get_logger(__name__)


def run(run_id: str) -> None:
    """
    Full signal engine pipeline for one trading day.

    Steps:
      1. Resolve today's date from the returns parquet filename.
      2. Load returns and sector ETF data.
      3. Fit OU parameters; persist to ou_params table.
      4. Classify VIX regime.
      5. Load sentiment scores.
      6. Compute strategy signals (stat arb, reversal, regime combo).
      7. Resolve per-ticker competition (highest |score|×adj wins).
      8. Persist winning signals as PENDING.
      9. Emit SIGNALS_READY event.

    On missing returns data, emits SIGNAL_ERROR and exits without
    writing any partial signals — fail closed per spec §10 S3.
    """
    cfg = get_config()
    init_db(cfg.system.db_url)

    today = datetime.date.today()  # UTC date; S1 launches this at 21:30 ET
    log.info("signal_engine_start", run_id=run_id, date=str(today))

    with get_session() as session:
        try:
            _run_pipeline(session, run_id, today, cfg)
        except (DataError, SignalError) as exc:
            session.rollback()
            log.error(
                "signal_engine_failed",
                run_id=run_id,
                error=str(exc),
            )
            sys.exit(1)
        except Exception as exc:
            session.rollback()
            log.error(
                "signal_engine_unexpected_failure",
                run_id=run_id,
                error=str(exc),
                exc_info=True,
            )
            sys.exit(1)


def _run_pipeline(session, run_id: str, today: datetime.date, cfg) -> None:
    """
    Inner pipeline — all DB writes happen within the caller's session.
    Raises DataError or SignalError to trigger fail-closed behaviour.
    """
    strategy_cfg = cfg.strategy_params
    risk_cfg = cfg.risk

    # ── 1. Load today's returns ──────────────────────────────────────────────
    returns_df = load_returns(today, cfg)
    # load_returns raises DataError on missing file; caught by caller.

    etf_returns = load_sector_etf_returns(today, cfg)

    # ── 2. Warm-start OU params from prior day ───────────────────────────────
    prior_ou = load_prior_ou_params(session, today)

    # ── 3. Fit OU parameters for all tickers ─────────────────────────────────
    ou_results = fit_ou_params(returns_df, etf_returns, strategy_cfg, prior_ou)
    write_ou_params(session, run_id, today, ou_results)

    # ── 4. VIX regime ────────────────────────────────────────────────────────
    regime = classify_regime(today, cfg)
    log.info("regime_classified", regime=regime, date=str(today))

    # ── 5. Sentiment ─────────────────────────────────────────────────────────
    sentiment_map = load_sentiment_scores(session, today)

    # ── 6. Strategy signals ──────────────────────────────────────────────────
    all_candidates = []

    if strategy_cfg.stat_arb.enabled:
        stat_arb_signals = compute_stat_arb_signals(
            ou_results=ou_results,
            strategy_cfg=strategy_cfg,
            sentiment_map=sentiment_map,
            regime=regime,
            run_id=run_id,
            today=today,
        )
        all_candidates.extend(stat_arb_signals)

    if strategy_cfg.reversal.enabled:
        reversal_signals = compute_reversal_signals(
            returns_df=returns_df,
            strategy_cfg=strategy_cfg,
            sentiment_map=sentiment_map,
            regime=regime,
            run_id=run_id,
            today=today,
        )
        all_candidates.extend(reversal_signals)

    # regime_combo is a meta-strategy that re-scores the winners from
    # the sub-strategies above rather than generating independent signals.
    # Its allocation cap is enforced at the competition stage.

    # ── 7. Competition: one signal per ticker ────────────────────────────────
    winning_signals = resolve_competition(all_candidates, strategy_cfg, regime, risk_cfg)

    # ── 8. Persist ───────────────────────────────────────────────────────────
    write_signals(session, winning_signals)

    write_event(
        session,
        run_id=run_id,
        event_type=EventType.SIGNALS_READY,
        severity=Severity.INFO,
        message=f"Signal engine complete: {len(winning_signals)} signals written",
        payload={
            "date": str(today),
            "n_signals": len(winning_signals),
            "regime": regime,
        },
    )
    session.commit()
    log.info("signal_engine_complete", run_id=run_id, n_signals=len(winning_signals), regime=regime)
