"""
s4_backtest_validator/writer.py

Thin persistence layer: writes BacktestRun and SystemEvent rows via ORM.

Changes from audit:
  - config_hash and strategy are now explicit parameters, not derived from cfg.
    The caller (main.py) reads config_hash from the jobs table row so the
    recorded hash is the one captured at job-creation time, not the live value.
  - n_mc_paths and include_costs are also explicit so write_backtest_record
    has no hidden dependency on the config object at all.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from shared.models import BacktestRun, SystemEvent
from shared.constants import EventType, Severity
from shared.logger import get_logger

log = get_logger(__name__)


def write_backtest_record(
    *,
    session: Session,
    run_id: str,
    strategy: str,
    config_hash: str,
    universe_hash: str,
    code_version: str,
    date_range_start,
    date_range_end,
    n_mc_paths: int,
    include_costs: bool,
    sharpe: float,
    sortino: float,
    max_drawdown: float,
    pbo: float,
    deflated_sharpe: float,
    result_path: str,
) -> BacktestRun:
    """
    Persist a BacktestRun row satisfying all §9.2 identity requirements.

    Every field is passed explicitly — no cfg reads inside this function —
    so the caller controls which config snapshot the record is stamped with.

    Parameters
    ----------
    session        : active SQLAlchemy session; caller manages commit boundary
    run_id         : UUID string from the jobs table
    strategy       : "STATARB", "REVERSAL", "REGIMECOMBO", or "ALL"
    config_hash    : SHA-256 of strategy_params.yaml at job-creation time
                     (read from jobs.config_hash, not the live config)
    universe_hash  : SHA-256 of universe.yaml at config-load time
    code_version   : git commit hash from _get_git_hash()
    date_range_start / date_range_end : datetime.date bounds of the history used
    n_mc_paths     : number of GARCH paths configured (from BacktestConfig)
    include_costs  : whether transaction costs were applied
    sharpe         : annualised OOS Sharpe ratio
    sortino        : annualised OOS Sortino ratio
    max_drawdown   : maximum peak-to-trough drawdown (negative fraction)
    pbo            : probability of backtest overfitting from CSCV
    deflated_sharpe: deflated Sharpe ratio (DSR)
    result_path    : absolute path to HDD output directory

    Returns
    -------
    BacktestRun ORM instance added to session (not yet committed).
    """
    record = BacktestRun(
        run_id=uuid.UUID(run_id),
        created_at=datetime.datetime.now(tz=datetime.timezone.utc),
        date_range_start=date_range_start,
        date_range_end=date_range_end,
        strategy=strategy,
        universe_hash=universe_hash,
        config_hash=config_hash,
        code_version=code_version,
        n_mc_paths=n_mc_paths,
        include_costs=include_costs,
        sharpe=sharpe,
        sortino=sortino,
        max_drawdown=max_drawdown,
        pbo=pbo,
        deflated_sharpe=deflated_sharpe,
        result_path=result_path,
    )
    session.add(record)
    session.flush()
    log.info("backtest_record_written", run_id=run_id,
             sharpe=round(sharpe, 4), pbo=round(pbo, 4),
             strategy=strategy, config_hash=config_hash[:8] + "...")
    return record


def write_event(
    session: Session,
    event_type: EventType,
    severity: Severity,
    subsystem: str,
    run_id: Optional[str],
    message: str,
    payload: Optional[Dict[str, Any]] = None,
) -> SystemEvent:
    """
    Append a row to `system_events` using only canonical EventType values.

    S4 may only emit BACKTEST_RESULT (INFO) and BACKTEST_FAILED (ERROR).
    Callers must not pass any other event_type — the canonical table in §4.3
    is exhaustive and no new types may be invented without a spec revision.

    Parameters
    ----------
    session    : active SQLAlchemy session
    event_type : BACKTEST_RESULT or BACKTEST_FAILED
    severity   : INFO or ERROR
    subsystem  : "S4"
    run_id     : job UUID string, or None if not job-scoped
    message    : human-readable description
    payload    : optional JSONB dict
    """
    event = SystemEvent(
        timestamp=datetime.datetime.now(tz=datetime.timezone.utc),
        event_type=event_type.value if hasattr(event_type, "value") else event_type,
        severity=severity.value if hasattr(severity, "value") else severity,
        subsystem=subsystem,
        run_id=uuid.UUID(run_id) if run_id else None,
        message=message,
        payload=payload or {},
    )
    session.add(event)
    session.flush()
    return event