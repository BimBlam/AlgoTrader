"""
Watchdog: stale job detection and CRITICAL event polling.

Two responsibilities:
1. Detect RUNNING jobs whose elapsed time exceeds 2 × expected duration and
   reset them to RETRYABLE_FAILED.
2. Poll system_events for any CRITICAL-severity row that was written after
   the orchestrator started, and force-halt the state machine if found.

Both loops run in a background daemon thread so they never block the scheduler.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Callable

from shared.constants import Severity
from shared.db import get_session
from shared.logger import get_logger
from shared.models import SystemEvent

from s1_orchestrator.job_manager import get_stale_running_jobs, mark_job_failed

log = get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class Watchdog:
    """Background thread that enforces stale-job timeouts and halt policy.

    Parameters
    ----------
    force_halt_callback:
        Called (with a reason string) when a CRITICAL event is detected or
        when halt_on_data_failure triggers.  Typically
        ``StateMachine.force_halt``.
    poll_interval_seconds:
        How often the watchdog wakes up to check.  Default 60 s (1 min).
    """

    def __init__(
        self,
        force_halt_callback: Callable[[str], None],
        poll_interval_seconds: int = 60,
    ) -> None:
        self._force_halt = force_halt_callback
        self._interval = poll_interval_seconds
        self._started_at: datetime = _utcnow()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="AlgoTrader-Watchdog",
            daemon=True,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background watchdog thread."""
        self._started_at = _utcnow()
        self._thread.start()
        log.info("watchdog_started", interval_seconds=self._interval)

    def stop(self) -> None:
        """Signal the background thread to exit and wait for it."""
        self._stop_event.set()
        self._thread.join(timeout=5)
        log.info("watchdog_stopped")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._check_stale_jobs()
                self._check_critical_events()
            except Exception as exc:  # noqa: BLE001
                # Watchdog must never crash the orchestrator — log and continue.
                log.error("watchdog_loop_error", error=str(exc))
            self._stop_event.wait(timeout=self._interval)

    def _check_stale_jobs(self) -> None:
        """Detect and reset any RUNNING jobs past their 2× timeout."""
        with get_session() as session:
            stale = get_stale_running_jobs(session)
            for job in stale:
                mark_job_failed(
                    session,
                    job,
                    f"Stale: exceeded 2× expected duration for {job.job_type}",
                    retryable=True,
                )
            if stale:
                session.commit()
                log.warning("watchdog_stale_jobs_reset", count=len(stale))

    def _check_critical_events(self) -> None:
        """Poll system_events for any CRITICAL row written after startup.

        A single CRITICAL event is enough to trigger a system halt (§7.2).
        We record the most recent event we processed so we don't re-trigger.
        """
        with get_session() as session:
            critical_events: list[SystemEvent] = (
                session.query(SystemEvent)
                .filter(
                    SystemEvent.severity == Severity.CRITICAL.value,
                    SystemEvent.timestamp > self._started_at,
                )
                .order_by(SystemEvent.timestamp.asc())
                .all()
            )
            if critical_events:
                latest = critical_events[-1]
                log.warning(
                    "watchdog_critical_event_detected",
                    event_type=latest.event_type,
                    subsystem=latest.subsystem,
                    message=latest.message,
                )
                # Advance the watermark so we don't re-trigger on the same events.
                self._started_at = latest.timestamp
                self._force_halt(
                    f"CRITICAL event from {latest.subsystem}: {latest.event_type} — {latest.message}"
                )
