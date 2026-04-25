"""
algotrader.dashboard/writer.py

Database write helpers for S7.  Every public function accepts an active
SQLAlchemy session and does NOT commit — the caller controls the transaction.

Events written by S7
---------------------
APPROVAL_GRANTED  INFO     signal approved by user
APPROVAL_DENIED   INFO     signal denied by user
USER_HALT         WARNING  operator pressed HALT
USER_RESUME       INFO     operator pressed RESUME
CONFIG_CHANGED    WARNING  strategy params edited
MODE_CHANGED      WARNING  system mode changed via dashboard
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from algotrader.shared.constants import EventType, Severity, SignalStatus
from algotrader.shared.exceptions import DataError
from algotrader.shared.logger import get_logger
from algotrader.shared.models import Signal, SystemEvent

log = get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


# ── Generic event writer ──────────────────────────────────────────────────────

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
        subsystem="S7",
        run_id=run_id,
        message=message,
        payload=payload or {},
    )
    session.add(event)
    session.flush()
    return event


# ── Signal approval / denial ──────────────────────────────────────────────────

def approve_signal(
    session: Session,
    signal_id: int,
    notes: str | None = None,
) -> Signal:
    """
    Approve a PENDING signal.

    Sets status=APPROVED, approved_by='USER', approved_at=now(), optional notes.
    Writes an APPROVAL_GRANTED event.

    Raises DataError if the signal is not found or is not in PENDING status.
    """
    signal = session.get(Signal, signal_id)
    if signal is None:
        raise DataError(f"Signal {signal_id} not found.")
    if signal.status != SignalStatus.PENDING.value:
        raise DataError(
            f"Signal {signal_id} cannot be approved: status={signal.status!r} "
            f"(must be PENDING)."
        )

    now = _utcnow()
    signal.status = SignalStatus.APPROVED.value
    signal.approved_by = "USER"
    signal.approved_at = now
    if notes:
        signal.notes = notes

    write_event(
        session,
        event_type=EventType.APPROVAL_GRANTED,
        severity=Severity.INFO,
        message=f"Signal approved: {signal.ticker} ({signal.strategy}, {signal.side})",
        run_id=str(signal.run_id),
        payload={
            "signal_id": signal_id,
            "ticker": signal.ticker,
            "strategy": signal.strategy,
            "side": signal.side,
        },
    )
    log.info("signal_approved", signal_id=signal_id, ticker=signal.ticker)
    return signal


def deny_signal(
    session: Session,
    signal_id: int,
    notes: str | None = None,
) -> Signal:
    """
    Deny a PENDING signal.

    Sets status=DENIED and optional notes.
    Writes an APPROVAL_DENIED event.

    Raises DataError if the signal is not found or is not in PENDING status.
    """
    signal = session.get(Signal, signal_id)
    if signal is None:
        raise DataError(f"Signal {signal_id} not found.")
    if signal.status != SignalStatus.PENDING.value:
        raise DataError(
            f"Signal {signal_id} cannot be denied: status={signal.status!r} "
            f"(must be PENDING)."
        )

    signal.status = SignalStatus.DENIED.value
    if notes:
        signal.notes = notes

    write_event(
        session,
        event_type=EventType.APPROVAL_DENIED,
        severity=Severity.INFO,
        message=f"Signal denied: {signal.ticker} ({signal.strategy}, {signal.side})",
        run_id=str(signal.run_id),
        payload={
            "signal_id": signal_id,
            "ticker": signal.ticker,
        },
    )
    log.info("signal_denied", signal_id=signal_id, ticker=signal.ticker)
    return signal


# ── Halt / Resume ─────────────────────────────────────────────────────────────

def write_halt_event(session: Session) -> SystemEvent:
    """Write USER_HALT (WARNING).  S1 monitors this to stop order submission."""
    log.warning("user_halt_requested")
    return write_event(
        session,
        event_type=EventType.USER_HALT,
        severity=Severity.WARNING,
        message="Operator-initiated halt via dashboard.",
    )


def write_resume_event(session: Session) -> SystemEvent:
    """Write USER_RESUME (INFO).  S1 monitors this to return to IDLE."""
    log.info("user_resume_requested")
    return write_event(
        session,
        event_type=EventType.USER_RESUME,
        severity=Severity.INFO,
        message="Operator-initiated resume via dashboard.",
    )


# ── Config / Mode changes ─────────────────────────────────────────────────────

def write_config_changed_event(
    session: Session,
    payload: dict | None = None,
) -> SystemEvent:
    """
    Write CONFIG_CHANGED (WARNING).
    S1's event_handler reacts by invalidating the config cache and
    scheduling a comparison backtest (§6.2 step 3).
    """
    return write_event(
        session,
        event_type=EventType.CONFIG_CHANGED,
        severity=Severity.WARNING,
        message="Strategy parameters updated via dashboard calibration.",
        payload=payload or {},
    )


def write_mode_changed_event(
    session: Session,
    new_mode: str,
    new_approval_mode: str,
) -> SystemEvent:
    """
    Write MODE_CHANGED (WARNING).
    S1's event_handler reacts by reloading config and propagating the new mode.
    """
    return write_event(
        session,
        event_type=EventType.MODE_CHANGED,
        severity=Severity.WARNING,
        message=f"System mode changed to {new_mode} (approval: {new_approval_mode}).",
        payload={"new_mode": new_mode, "new_approval_mode": new_approval_mode},
    )
