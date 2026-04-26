"""
DB write helpers for S3.

Separated from business logic so that tests can inject mock sessions
without touching any signal computation code.
"""
import datetime

from sqlalchemy.orm import Session

from algotrader.shared.constants import EventType, Severity, SignalStatus
from algotrader.shared.logger import get_logger
from algotrader.shared.models import Signal, SystemEvent
from algotrader.signals.stat_arb import SignalCandidate

log = get_logger(__name__)


def write_signals(session: Session, candidates: list[SignalCandidate]) -> None:
    """
    Persist winning signals to the signals table with status=PENDING.

    target_size_usd is set to 0.0 here — S6 computes the final size
    using Kelly + ATR from risk.yaml.  Storing 0.0 as a placeholder
    keeps the column NOT NULL while making it clear S6 owns sizing.
    """
    if not candidates:
        log.warning("no_signals_to_write")
        return

    for c in candidates:
        signal = Signal(
            run_id=c.run_id,
            created_at=datetime.datetime.now(datetime.UTC),
            ticker=c.ticker.upper(),
            strategy=str(c.strategy.value) if hasattr(c.strategy, "value") else str(c.strategy),
            side=str(c.side.value) if hasattr(c.side, "value") else str(c.side),
            raw_score=c.raw_score,
            sentiment_adj=c.sentiment_adj,
            regime=c.regime,
            target_size_usd=0.0,  # S6 computes final sizing
            status=str(SignalStatus.PENDING.value),
        )
        session.add(signal)

    log.info("signals_written", n=len(candidates))


def write_event(
    session: Session,
    run_id: str,
    event_type: EventType,
    severity: Severity,
    message: str,
    payload: dict | None = None,
) -> None:
    """
    Write a row to system_events.

    Always uses the S3 subsystem label.  Payload is optional JSONB context.
    """
    event = SystemEvent(
        timestamp=datetime.datetime.now(datetime.UTC),
        event_type=str(event_type.value) if hasattr(event_type, "value") else str(event_type),
        severity=str(severity.value) if hasattr(severity, "value") else str(severity),
        subsystem="S3",
        run_id=run_id,
        message=message,
        payload=payload or {},
    )
    session.add(event)
