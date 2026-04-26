"""
APScheduler configuration for the AlgoTrader orchestrator.

All cron expressions target the ``America/New_York`` timezone to match the
wall-clock times in §2.3.  APScheduler converts internally to UTC.

Job dependency notes:
- INGEST_EOD and RUN_SENTIMENT fire at the same time (21:00 ET) and run in
  parallel — both are launched concurrently by the cron callback.
- RUN_SIGNALS fires at 21:30 ET.  The cron trigger is a safety net; in normal
  operation the orchestrator also listens for DATA_READY + SENTIMENT_READY
  events and can start S3 early if both arrive before 21:30.
- EXECUTE_ORDERS fires at 09:25 ET.  S6 will check for APPROVED signals itself;
  if none exist it exits cleanly.
- RECONCILE fires at 16:30 ET.
- RUN_BACKTEST fires every Sunday at 20:00 ET.
"""

from __future__ import annotations

from collections.abc import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from algotrader.shared.logger import get_logger

log = get_logger(__name__)

# (job_id, cron kwargs, job_types_to_dispatch)
# job_types_to_dispatch is a list because 21:00 fires two jobs simultaneously.
_SCHEDULE: list[tuple[str, dict, list[str]]] = [
    (
        "ingest_and_sentiment",
        {"day_of_week": "mon-fri", "hour": 21, "minute": 0},
        ["INGEST_EOD", "RUN_SENTIMENT"],
    ),
    (
        "run_signals",
        {"day_of_week": "mon-fri", "hour": 21, "minute": 30},
        ["RUN_SIGNALS"],
    ),
    (
        "execute_orders",
        {"day_of_week": "mon-fri", "hour": 9, "minute": 25},
        ["EXECUTE_ORDERS"],
    ),
    (
        "reconcile",
        {"day_of_week": "mon-fri", "hour": 16, "minute": 30},
        ["RECONCILE"],
    ),
    (
        "weekly_backtest",
        {"day_of_week": "sun", "hour": 20, "minute": 0},
        ["RUN_BACKTEST"],
    ),
]


class JobScheduler:
    """Wraps APScheduler with the AlgoTrader cron schedule.

    Parameters
    ----------
    dispatch_callback:
        Called with a list of job_type strings every time a cron trigger fires.
        The orchestrator uses this to launch the appropriate workers.
    timezone:
        Scheduler timezone.  Must be ``America/New_York`` for spec compliance.
    """

    def __init__(
        self,
        dispatch_callback: Callable[[list[str]], None],
        timezone: str = "America/New_York",
    ) -> None:
        self._dispatch = dispatch_callback
        self._tz = timezone
        self._scheduler = BackgroundScheduler(timezone=timezone)
        self._register_jobs()

    def _register_jobs(self) -> None:
        """Register all cron jobs defined in ``_SCHEDULE``."""
        for job_id, cron_kwargs, job_types in _SCHEDULE:
            trigger = CronTrigger(timezone=self._tz, **cron_kwargs)
            # Capture job_types in closure via default arg.
            self._scheduler.add_job(
                func=self._make_dispatch_fn(job_types),
                trigger=trigger,
                id=job_id,
                name=job_id,
                max_instances=1,
                coalesce=True,  # skip missed fires rather than pile up
                misfire_grace_time=300,  # 5-minute window before a fire is dropped
            )
            log.info("cron_registered", job_id=job_id, cron=cron_kwargs, dispatches=job_types)

    def _make_dispatch_fn(self, job_types: list[str]) -> Callable:
        """Return a closure that calls the dispatch callback with job_types."""
        def _fn() -> None:
            log.info("cron_fired", job_types=job_types)
            try:
                self._dispatch(job_types)
            except Exception as exc:  # noqa: BLE001
                log.error("dispatch_error", job_types=job_types, error=str(exc))
        return _fn

    def start(self) -> None:
        """Start the APScheduler background thread."""
        self._scheduler.start()
        log.info("scheduler_started", timezone=self._tz)

    def stop(self) -> None:
        """Gracefully shut down APScheduler."""
        self._scheduler.shutdown(wait=False)
        log.info("scheduler_stopped")

    def get_next_fire_time(self, job_id: str) -> str | None:
        """Return the next fire time for a registered job as an ISO string."""
        job = self._scheduler.get_job(job_id)
        if job is None or job.next_run_time is None:
            return None
        return job.next_run_time.isoformat()
