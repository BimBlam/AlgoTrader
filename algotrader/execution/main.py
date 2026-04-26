"""
algotrader.execution/main.py — EXECUTE_ORDERS job entry point.

Invoked by S1 as:
    python -m algotrader.execution.main <run_id>

with ``ACCOUNT_TYPE=PAPER|LIVE`` in the environment.

Execution lifecycle
-------------------
1.  Read ACCOUNT_TYPE from env; load config; init DB.
2.  Connect to IBKR TWS with retry.
3.  Check Guard 1 (daily loss limit) — HALT if breached.
4.  Fetch today's APPROVED signals.
5.  For each signal:
        a. Compute position size (quarter-Kelly + ATR).
        b. Run Guards 2–7 (per-signal pre-flight).
        c. Build limit order; submit to IBKR.
        d. Write Order row; update signal to EXECUTED.
        e. Register fill tracker callback.
6.  Wait FILL_TIMEOUT seconds for fills.
7.  Disconnect; exit 0.

Error handling
--------------
- Guard 1 RiskBreach → RISK_HALT CRITICAL event + cancel all orders + exit 1.
- IBKR ExecutionError → RISK_HALT CRITICAL event + exit 1.
- Per-signal RiskBreach / DataError → log warning + skip signal, continue loop.
- Unexpected exception → RISK_HALT CRITICAL event + cancel all orders + exit 1.
"""
from __future__ import annotations

import os
import sys
from datetime import UTC, datetime

from algotrader.shared.config_loader import get_config
from algotrader.shared.constants import EventType, Severity, SignalStatus
from algotrader.shared.db import get_session, init_db
from algotrader.shared.exceptions import DataError, ExecutionError, RiskBreach
from algotrader.shared.logger import get_logger
from algotrader.shared.models import Signal

from .fill_tracker import FillTracker
from .ibkr_client import IBKRClient
from .order_builder import build_contract, build_order, get_limit_price
from .risk_guards import check_daily_loss, run_per_signal_guards
from .sizer import compute_position_size
from .writer import (
    mark_signal_executed,
    update_order_submitted,
    write_event,
    write_order,
)

log = get_logger(__name__)


def run(run_id: str) -> None:
    account_type = os.environ.get("ACCOUNT_TYPE", "PAPER")

    cfg = get_config()
    init_db(cfg.system.db_url)

    log.info("execution_start", run_id=run_id, account_type=account_type)

    ibkr = IBKRClient(cfg, account_type)

    try:
        ibkr.connect()
    except ExecutionError as exc:
        _emit_halt(run_id, f"IBKR connection failed: {exc}")
        sys.exit(1)

    try:
        _execute(run_id, account_type, cfg, ibkr)
    except RiskBreach as exc:
        _emit_halt(run_id, f"RiskBreach (daily loss): {exc}")
        ibkr.cancel_all_pending()
        sys.exit(1)
    except Exception as exc:
        _emit_halt(run_id, f"Unexpected execution error: {exc}")
        ibkr.cancel_all_pending()
        sys.exit(1)
    finally:
        ibkr.disconnect()

    log.info("execution_complete", run_id=run_id)


def _execute(run_id: str, account_type: str, cfg, ibkr: IBKRClient) -> None:
    today = datetime.now(tz=UTC).date()

    with get_session() as session:
        # Guard 1: daily loss — halts the entire batch if breached.
        check_daily_loss(session, cfg, account_type)

        signals = (
            session.query(Signal)
            .filter(Signal.status == SignalStatus.APPROVED.value)
            .all()
        )
        today_signals = [s for s in signals if s.created_at.date() == today]

        log.info("signals_fetched", count=len(today_signals), date=str(today))

        if not today_signals:
            write_event(
                session,
                event_type=EventType.JOB_COMPLETED,
                severity=Severity.INFO,
                message="No approved signals found for today.",
                run_id=run_id,
            )
            session.commit()
            return

        account_equity = ibkr.get_account_equity()
        log.info("account_equity_fetched", equity=round(account_equity, 2))

        tracker = FillTracker(session, run_id)

        for signal in today_signals:
            _process_signal(
                signal=signal,
                session=session,
                cfg=cfg,
                ibkr=ibkr,
                account_type=account_type,
                account_equity=account_equity,
                run_id=run_id,
                tracker=tracker,
            )

        if tracker._pending:
            tracker.wait(ibkr)


def _process_signal(
    signal,
    session,
    cfg,
    ibkr: IBKRClient,
    account_type: str,
    account_equity: float,
    run_id: str,
    tracker: FillTracker,
) -> None:
    """Process one signal through sizing → guards → submission → fill tracking."""
    try:
        limit_price = get_limit_price(signal.ticker, cfg)
        target_usd, quantity = compute_position_size(
            signal, cfg, account_equity, limit_price
        )
        target_usd, quantity = run_per_signal_guards(
            signal=signal,
            session=session,
            cfg=cfg,
            ibkr_client=ibkr,
            account_type=account_type,
            target_usd=target_usd,
            quantity=quantity,
            limit_price=limit_price,
        )
    except RiskBreach as exc:
        log.warning(
            "signal_denied_risk_guard",
            ticker=signal.ticker,
            reason=str(exc),
        )
        return
    except DataError as exc:
        log.warning(
            "signal_skipped_data_error",
            ticker=signal.ticker,
            error=str(exc),
        )
        return

    # Build and submit
    try:
        contract = build_contract(signal.ticker)
        ib_order = build_order(signal, quantity, limit_price, cfg)

        order_row = write_order(
            session,
            signal,
            quantity=quantity,
            limit_price=limit_price,
            account_type=account_type,
        )
        session.commit()  # persist Order before submitting to IBKR

        trade = ibkr.submit_order(contract, ib_order)
        ibkr_order_id = str(trade.order.orderId)

        update_order_submitted(session, order_row, ibkr_order_id)
        mark_signal_executed(session, signal)

        write_event(
            session,
            event_type=EventType.ORDER_SUBMITTED,
            severity=Severity.INFO,
            message=(
                f"Order submitted: {signal.ticker} x{quantity} "
                f"@ {limit_price:.2f} ({account_type})"
            ),
            run_id=run_id,
            payload={
                "ticker": signal.ticker,
                "quantity": quantity,
                "limit_price": limit_price,
                "ibkr_order_id": ibkr_order_id,
                "account_type": account_type,
            },
        )
        session.commit()

        tracker.attach(trade, order_row)

    except ExecutionError as exc:
        log.error(
            "order_submission_failed",
            ticker=signal.ticker,
            error=str(exc),
        )
        write_event(
            session,
            event_type=EventType.ORDER_REJECTED,
            severity=Severity.ERROR,
            message=f"Order submission failed for {signal.ticker}: {exc}",
            run_id=run_id,
            payload={"ticker": signal.ticker, "error": str(exc)},
        )
        session.commit()


def _emit_halt(run_id: str, message: str) -> None:
    log.error("execution_halt", message=message)
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
