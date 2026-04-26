"""
algotrader.execution/writer.py

Database write helpers for S6.  All functions accept an active SQLAlchemy
session and return the ORM object written so callers can access the generated
id without an extra query.

None of these functions commit — the caller controls transaction boundaries so
that related writes can be batched or rolled back atomically.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from algotrader.shared.constants import EventType, OrderStatus, PositionStatus, Severity, SignalStatus
from algotrader.shared.logger import get_logger
from algotrader.shared.models import Order, Position, Signal, SystemEvent

log = get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


# ── Orders ────────────────────────────────────────────────────────────────────

def write_order(
    session: Session,
    signal: Signal,
    *,
    quantity: int,
    limit_price: float,
    account_type: str,
) -> Order:
    """Create an Order row linked to *signal* and flush it (without committing)."""
    order = Order(
        signal_id=signal.id,
        ticker=signal.ticker,
        side="BUY" if signal.side == "LONG" else "SELL",
        order_type="LIMIT",
        quantity=quantity,
        limit_price=limit_price,
        status=OrderStatus.PENDING.value,
        account_type=account_type,
        submitted_at=_utcnow(),
    )
    session.add(order)
    session.flush()
    log.info(
        "order_written",
        ticker=signal.ticker,
        quantity=quantity,
        limit_price=limit_price,
    )
    return order


def update_order_submitted(session: Session, order: Order, ibkr_order_id: str) -> None:
    """Record the IBKR order ID once TWS accepts the order."""
    order.ibkr_order_id = ibkr_order_id
    order.status = OrderStatus.SUBMITTED.value
    order.submitted_at = _utcnow()


def update_order_filled(
    session: Session,
    order: Order,
    fill_price: float,
    filled_at: datetime,
) -> None:
    order.fill_price = fill_price
    order.filled_at = filled_at
    order.status = OrderStatus.FILLED.value


def update_order_rejected(session: Session, order: Order) -> None:
    order.status = OrderStatus.REJECTED.value


# ── Positions ─────────────────────────────────────────────────────────────────

def write_position(
    session: Session,
    order: Order,
    fill_price: float,
    filled_at: datetime,
) -> Position:
    """Create an OPEN Position row from a filled order."""
    position = Position(
        ticker=order.ticker,
        side=order.side,
        entry_price=fill_price,
        quantity=order.quantity,
        entry_time=filled_at,
        status=PositionStatus.OPEN.value,
        order_id=order.id,
        account_type=order.account_type,
    )
    session.add(position)
    session.flush()
    return position


def close_position(
    session: Session,
    position: Position,
    exit_price: float,
    exit_time: datetime,
) -> None:
    """Mark a position CLOSED and compute realised P&L."""
    position.exit_price = exit_price
    position.exit_time = exit_time
    # BUY (long): profit when exit > entry.  SELL (short): profit when exit < entry.
    direction = 1.0 if position.side == "BUY" else -1.0
    position.realised_pnl = (exit_price - position.entry_price) * position.quantity * direction
    position.status = PositionStatus.CLOSED.value


# ── Signals ───────────────────────────────────────────────────────────────────

def mark_signal_executed(session: Session, signal: Signal) -> None:
    signal.status = SignalStatus.EXECUTED.value


def expire_stale_signals(session: Session, trade_date_iso: str) -> int:
    """
    Set status=EXPIRED on APPROVED signals whose creation date is before
    *trade_date_iso* (YYYY-MM-DD).  Returns the number of rows updated.
    """
    rows = (
        session.query(Signal)
        .filter(Signal.status == SignalStatus.APPROVED.value)
        .all()
    )
    expired = 0
    for sig in rows:
        if sig.created_at.date().isoformat() < trade_date_iso:
            sig.status = SignalStatus.EXPIRED.value
            expired += 1
    return expired


# ── Events ────────────────────────────────────────────────────────────────────

def write_event(
    session: Session,
    *,
    event_type: EventType,
    severity: Severity,
    message: str,
    run_id: str | None = None,
    payload: dict | None = None,
) -> SystemEvent:
    event = SystemEvent(
        timestamp=_utcnow(),
        event_type=event_type.value,
        severity=severity.value,
        subsystem="S6",
        run_id=run_id,
        message=message,
        payload=payload or {},
    )
    session.add(event)
    session.flush()
    return event
