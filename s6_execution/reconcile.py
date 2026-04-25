"""
s6_execution/reconcile.py — RECONCILE job entry point.

Invoked by S1 as:
    python -m s6_execution.reconcile <run_id>

with ``ACCOUNT_TYPE=PAPER|LIVE`` in the environment.

End-of-day reconciliation
-------------------------
1.  Connect to IBKR.
2.  Fetch current portfolio positions from TWS.
3.  For each OPEN DB position no longer held at IBKR: mark CLOSED, compute
    realised P&L, emit POSITION_CLOSED event.
4.  Expire APPROVED signals whose creation date predates today.
5.  Disconnect and exit 0.

On IBKR connection failure: emit RISK_HALT CRITICAL event and exit 1 so S1's
watchdog detects the failure and sets system state to HALT.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from shared.config_loader import get_config
from shared.constants import EventType, PositionStatus, Severity
from shared.db import get_session, init_db
from shared.exceptions import ExecutionError
from shared.logger import get_logger
from shared.models import Position

from .ibkr_client import IBKRClient
from .writer import close_position, expire_stale_signals, write_event

log = get_logger(__name__)


def run(run_id: str) -> None:
    account_type = os.environ.get("ACCOUNT_TYPE", "PAPER")

    cfg = get_config()
    init_db(cfg.system.db_url)

    log.info("reconcile_start", run_id=run_id, account_type=account_type)

    ibkr = IBKRClient(cfg, account_type)
    try:
        ibkr.connect()
    except ExecutionError as exc:
        _emit_halt_event(run_id, f"IBKR connection failed during reconciliation: {exc}")
        sys.exit(1)

    try:
        _reconcile(run_id, account_type, ibkr)
    except Exception as exc:
        log.error("reconcile_unexpected_error", error=str(exc))
        _emit_halt_event(run_id, f"Unexpected reconciliation error: {exc}")
        sys.exit(1)
    finally:
        ibkr.disconnect()

    log.info("reconcile_complete", run_id=run_id)


def _reconcile(run_id: str, account_type: str, ibkr: IBKRClient) -> None:
    # Fetch live IBKR portfolio (symbols currently held)
    ibkr_positions = ibkr._ib.positions()
    ibkr_tickers = {p.contract.symbol for p in ibkr_positions}

    today_iso = datetime.now(tz=timezone.utc).date().isoformat()

    with get_session() as session:
        open_db_positions = (
            session.query(Position)
            .filter(
                Position.status == PositionStatus.OPEN.value,
                Position.account_type == account_type,
            )
            .all()
        )

        closed_count = 0
        for pos in open_db_positions:
            if pos.ticker not in ibkr_tickers:
                # Position no longer held — close it in the DB
                exit_price = _last_fill_price(ibkr, pos.ticker) or pos.entry_price
                exit_time = datetime.now(tz=timezone.utc)

                close_position(session, pos, exit_price, exit_time)
                write_event(
                    session,
                    event_type=EventType.POSITION_CLOSED,
                    severity=Severity.INFO,
                    message=(
                        f"Position closed (reconciliation): {pos.ticker} "
                        f"x{pos.quantity} @ {exit_price:.2f}, "
                        f"P&L={pos.realised_pnl or 0.0:.2f}"
                    ),
                    run_id=run_id,
                    payload={
                        "ticker": pos.ticker,
                        "quantity": pos.quantity,
                        "exit_price": exit_price,
                        "realised_pnl": pos.realised_pnl,
                    },
                )
                closed_count += 1
                log.info(
                    "position_closed_reconcile",
                    ticker=pos.ticker,
                    exit_price=exit_price,
                    realised_pnl=pos.realised_pnl,
                )

        expired_count = expire_stale_signals(session, today_iso)
        session.commit()

    log.info(
        "reconcile_summary",
        closed_positions=closed_count,
        expired_signals=expired_count,
        account_type=account_type,
    )


def _last_fill_price(ibkr: IBKRClient, ticker: str) -> float | None:
    """
    Try to find the last execution fill price for *ticker* from IBKR.
    Returns None if not available (caller falls back to entry_price).
    """
    try:
        executions = ibkr._ib.executions()
        fills = [e for e in executions if e.contract.symbol == ticker]
        if fills:
            return float(fills[-1].execution.avgPrice)
    except Exception:
        pass
    return None


def _emit_halt_event(run_id: str, message: str) -> None:
    log.error("reconcile_halt", message=message)
    try:
        with get_session() as session:
            write_event(
                session,
                event_type=EventType.RISK_HALT,
                severity=Severity.CRITICAL,
                message=message,
                run_id=run_id,
            )
            session.commit()
    except Exception as db_exc:
        log.error("halt_event_write_failed", error=str(db_exc))


if __name__ == "__main__":
    run(sys.argv[1])
