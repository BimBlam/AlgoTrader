"""
Job lifecycle management for the AlgoTrader orchestrator.

Owns all CREATE and UPDATE operations on the ``jobs`` table.  The only other
writer to this table is the worker process that claims its own job row via
``SELECT … FOR UPDATE SKIP LOCKED`` — but that path is in the worker, not
here.

This module deliberately knows nothing about which subprocess implements each
job type.  That mapping lives in ``process_manager``.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from algotrader.shared.constants import EventType, JobStatus, Severity
from algotrader.shared.exceptions import DataError
from algotrader.shared.logger import get_logger
from algotrader.shared.models import Job, SystemEvent

log = get_logger(__name__)

# Expected durations in *minutes* per job type.  Stale timeout = 2×.
# Sourced from spec §2.3 timelines and practical estimates.
_EXPECTED_DURATION_MINUTES: dict[str, int] = {
    "INGEST_EOD": 30,
    "RUN_SENTIMENT": 30,
    "RUN_SIGNALS": 15,
    "EXECUTE_ORDERS": 20,
    "RECONCILE": 15,
    "RUN_BACKTEST": 120,
}


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _config_hash(cfg_obj: Any) -> str:
    """Compute a deterministic SHA-256 of the config snapshot.

    We serialise only the non-sensitive fields that affect job behaviour.
    The hash is stored in jobs.config_hash for audit reproducibility (§9.2).
    """
    try:
        raw = json.dumps(
            {
                "mode": str(getattr(getattr(cfg_obj, "system", cfg_obj), "mode", "UNKNOWN")),
                "approval_mode": str(
                    getattr(getattr(cfg_obj, "system", cfg_obj), "approval_mode", "UNKNOWN")
                ),
            },
            sort_keys=True,
        )
        return hashlib.sha256(raw.encode()).hexdigest()
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_job(
    session: Session,
    job_type: str,
    config_snapshot: Any,
    *,
    run_id: str | None = None,
) -> Job:
    """Insert a new job row with status PENDING and return it.

    Parameters
    ----------
    session:
        Active SQLAlchemy session.  Caller is responsible for commit.
    job_type:
        One of the canonical job types defined in the spec.
    config_snapshot:
        The AppConfig object at job-creation time; used to compute config_hash.
    run_id:
        Optional explicit UUID string.  A fresh UUID4 is generated if omitted.

    Raises
    ------
    DataError
        If the job_type is not in the known set (fail-closed).
    """
    if job_type not in _EXPECTED_DURATION_MINUTES:
        raise DataError(f"Unknown job_type '{job_type}'; cannot create job row.")

    job = Job(
        run_id=run_id or str(uuid.uuid4()),
        job_type=job_type,
        status=JobStatus.PENDING.value,
        created_at=_utcnow(),
        retry_count=0,
        config_hash=_config_hash(config_snapshot),
    )
    session.add(job)
    log.info("job_created", run_id=job.run_id, job_type=job_type)
    return job


def mark_job_started(session: Session, job: Job, worker_pid: int) -> None:
    """Transition job from PENDING → RUNNING and record the worker PID.

    Also writes a JOB_STARTED system event so the audit trail is complete.
    """
    job.status = JobStatus.RUNNING.value
    job.started_at = _utcnow()
    job.worker_pid = worker_pid
    _write_event(
        session,
        event_type=EventType.JOB_STARTED.value,
        severity=Severity.INFO.value,
        run_id=job.run_id,
        message=f"Job {job.job_type} started (PID {worker_pid})",
    )
    log.info("job_started", run_id=job.run_id, job_type=job.job_type, pid=worker_pid)


def mark_job_completed(session: Session, job: Job) -> None:
    """Transition job to DONE and write JOB_COMPLETED event."""
    job.status = JobStatus.DONE.value
    job.completed_at = _utcnow()
    _write_event(
        session,
        event_type=EventType.JOB_COMPLETED.value,
        severity=Severity.INFO.value,
        run_id=job.run_id,
        message=f"Job {job.job_type} completed successfully",
    )
    log.info("job_completed", run_id=job.run_id, job_type=job.job_type)


def mark_job_failed(
    session: Session,
    job: Job,
    error_msg: str,
    *,
    retryable: bool = False,
) -> None:
    """Transition job to FAILED or RETRYABLE_FAILED and write JOB_FAILED event.

    Parameters
    ----------
    retryable:
        When True the status is set to RETRYABLE_FAILED (stale timeout path).
        When False the status is FAILED (hard error).
    """
    job.status = (
        JobStatus.RETRYABLE_FAILED.value if retryable else JobStatus.FAILED.value
    )
    job.completed_at = _utcnow()
    job.error_msg = error_msg
    _write_event(
        session,
        event_type=EventType.JOB_FAILED.value,
        severity=Severity.ERROR.value,
        run_id=job.run_id,
        message=f"Job {job.job_type} failed: {error_msg}",
        payload={"retryable": retryable},
    )
    log.error("job_failed", run_id=job.run_id, job_type=job.job_type, error=error_msg)


def get_stale_running_jobs(session: Session) -> list[Job]:
    """Return RUNNING jobs whose elapsed time exceeds 2× their expected duration.

    A job is stale when:
        now - started_at  >  2 × expected_duration_minutes

    This means the worker process either crashed without updating the row, or
    is hung.  The orchestrator watchdog will call this and reset each stale job
    to RETRYABLE_FAILED.
    """
    now = _utcnow()
    running_jobs: list[Job] = (
        session.query(Job)
        .filter(Job.status == JobStatus.RUNNING.value)
        .all()
    )
    stale: list[Job] = []
    for job in running_jobs:
        if job.started_at is None:
            continue
        expected_minutes = _EXPECTED_DURATION_MINUTES.get(job.job_type, 60)
        timeout_seconds = expected_minutes * 2 * 60
        elapsed = (now - job.started_at).total_seconds()
        if elapsed > timeout_seconds:
            stale.append(job)
            log.warning(
                "job_stale_detected",
                run_id=job.run_id,
                job_type=job.job_type,
                elapsed_seconds=int(elapsed),
                timeout_seconds=timeout_seconds,
            )
    return stale


def get_job_by_run_id(session: Session, run_id: str) -> Job | None:
    """Fetch a job row by run_id, or None if not found."""
    return session.query(Job).filter(Job.run_id == run_id).first()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _write_event(
    session: Session,
    *,
    event_type: str,
    severity: str,
    message: str,
    run_id: str | None = None,
    payload: dict | None = None,
) -> None:
    """Insert a system_events row scoped to S1."""
    event = SystemEvent(
        timestamp=_utcnow(),
        event_type=event_type,
        severity=severity,
        subsystem="S1",
        run_id=run_id,
        message=message,
        payload=payload or {},
    )
    session.add(event)
