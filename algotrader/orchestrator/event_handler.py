"""
External event handler: reacts to dashboard-written system_events.

This runs in its own background thread, polling the DB at a low frequency.
It is separate from the watchdog so that each concern has a single
responsibility and the polling cadences can be tuned independently.

Events handled
--------------
MODE_CHANGED   — re-read system.yaml; propagate new mode/approval to orchestrator.
CONFIG_CHANGED — invalidate config cache; orchestrator queues a comparison backtest.
USER_HALT      — force-halt the state machine and terminate running workers (§7.2).
USER_RESUME    — return the system from HALT to IDLE (§7.2).
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Callable

from algotrader.shared.config_loader import get_config, invalidate_cache
from algotrader.shared.constants import ApprovalMode, EventType, SystemMode
from algotrader.shared.db import get_session
from algotrader.shared.logger import get_logger
from algotrader.shared.models import SystemEvent

log = get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class EventHandler:
    """Polls system_events for dashboard-driven control commands.

    Parameters
    ----------
    on_mode_changed:
        Callback invoked with ``(new_mode: SystemMode, new_approval: ApprovalMode)``
        when a MODE_CHANGED event is detected.
    on_config_changed:
        Callback invoked with no arguments when a CONFIG_CHANGED event is
        detected; the orchestrator should then schedule a backtest.
    on_user_halt:
        Callback invoked with a reason string when USER_HALT is detected.
        Typically ``Orchestrator._force_halt``.
    on_user_resume:
        Callback invoked with no arguments when USER_RESUME is detected.
        Typically transitions state machine from HALT → IDLE.
    poll_interval_seconds:
        How often (seconds) to query the DB.  Default 30 s.
    """

    def __init__(
        self,
        on_mode_changed: Callable[[SystemMode, ApprovalMode], None],
        on_config_changed: Callable[[], None],
        on_user_halt: Callable[[str], None] | None = None,
        on_user_resume: Callable[[], None] | None = None,
        poll_interval_seconds: int = 30,
    ) -> None:
        self._on_mode_changed = on_mode_changed
        self._on_config_changed = on_config_changed
        self._on_user_halt = on_user_halt
        self._on_user_resume = on_user_resume
        self._interval = poll_interval_seconds
        self._watermark: datetime = _utcnow()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="AlgoTrader-EventHandler",
            daemon=True,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._thread.start()
        log.info("event_handler_started", interval_seconds=self._interval)

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=5)
        log.info("event_handler_stopped")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._poll()
            except Exception as exc:  # noqa: BLE001
                log.error("event_handler_poll_error", error=str(exc))
            self._stop_event.wait(timeout=self._interval)

    def _poll(self) -> None:
        """Query DB for new dashboard-driven events since the watermark."""
        interesting = {
            EventType.MODE_CHANGED.value,
            EventType.CONFIG_CHANGED.value,
            EventType.USER_HALT.value,
            EventType.USER_RESUME.value,
        }
        with get_session() as session:
            new_events: list[SystemEvent] = (
                session.query(SystemEvent)
                .filter(
                    SystemEvent.event_type.in_(interesting),
                    SystemEvent.timestamp > self._watermark,
                )
                .order_by(SystemEvent.timestamp.asc())
                .all()
            )
            for event in new_events:
                self._watermark = event.timestamp
                if event.event_type == EventType.MODE_CHANGED.value:
                    self._handle_mode_changed()
                elif event.event_type == EventType.CONFIG_CHANGED.value:
                    self._handle_config_changed()
                elif event.event_type == EventType.USER_HALT.value:
                    self._handle_user_halt()
                elif event.event_type == EventType.USER_RESUME.value:
                    self._handle_user_resume()

    def _handle_mode_changed(self) -> None:
        """Reload config and propagate new mode/approval to the orchestrator."""
        log.info("event_handler_mode_changed")
        invalidate_cache()
        cfg = get_config()
        new_mode = SystemMode(cfg.system.mode)
        new_approval = ApprovalMode(cfg.system.approval_mode)
        self._on_mode_changed(new_mode, new_approval)
        log.info(
            "mode_applied",
            mode=new_mode.value,
            approval_mode=new_approval.value,
        )

    def _handle_config_changed(self) -> None:
        """Invalidate config cache and notify orchestrator to schedule backtest."""
        log.info("event_handler_config_changed")
        invalidate_cache()
        self._on_config_changed()

    def _handle_user_halt(self) -> None:
        """Force-halt the orchestrator in response to a dashboard HALT action."""
        log.warning("event_handler_user_halt")
        if self._on_user_halt is not None:
            self._on_user_halt("Operator-initiated halt via dashboard (USER_HALT event).")
        else:
            log.warning("event_handler_user_halt_no_callback")

    def _handle_user_resume(self) -> None:
        """Resume the orchestrator in response to a dashboard RESUME action."""
        log.info("event_handler_user_resume")
        if self._on_user_resume is not None:
            self._on_user_resume()
        else:
            log.warning("event_handler_user_resume_no_callback")
