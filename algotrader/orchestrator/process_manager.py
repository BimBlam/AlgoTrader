"""
Worker process lifecycle management.

Spawns each worker as an independent OS subprocess, stores its PID in the
``jobs`` table, monitors for abnormal exit, and reports failures back through
``job_manager``.

Design notes:
- We use ``subprocess.Popen`` (not ``multiprocessing``) because each worker is
  a separate Python package with its own entry point.  This matches §2.1.
- Environment variables (DB_URL etc.) are inherited from the orchestrator
  process — no explicit passing needed.
- The ``run_id`` UUID is passed as a CLI argument so the worker can claim its
  own jobs row via SKIP LOCKED.
- ``BOTH`` mode is handled by the caller: two separate ``launch_worker`` calls
  with distinct run_ids and an ``account_type`` env-var override.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

from algotrader.shared.logger import get_logger

log = get_logger(__name__)

# Map job_type → the Python module entry point (python -m <module> <run_id>).
# All worker packages must expose a ``__main__.py`` or a ``main`` module.
_JOB_ENTRY_POINTS: dict[str, str] = {
    "INGEST_EOD": "algotrader.ingestion.main",
    "RUN_SENTIMENT": "algotrader.sentiment.main",
    "RUN_SIGNALS": "algotrader.signals.main",
    "RUN_BACKTEST": "algotrader.backtest.main",
    "EXECUTE_ORDERS": "algotrader.execution.main",
    "RECONCILE": "algotrader.execution.reconcile",
}


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass
class WorkerHandle:
    """Lightweight record of a running worker subprocess.

    Attributes
    ----------
    run_id:
        Links back to the jobs row.
    job_type:
        Human-readable label for logging.
    process:
        The Popen object for the live subprocess.
    launched_at:
        UTC timestamp of launch (for external watchdog use).
    """

    run_id: str
    job_type: str
    process: subprocess.Popen
    launched_at: datetime = field(default_factory=_utcnow)

    @property
    def pid(self) -> int:
        return self.process.pid

    def poll(self) -> int | None:
        """Return the exit code if the process has finished, else None."""
        return self.process.poll()

    def is_alive(self) -> bool:
        return self.poll() is None

    def terminate(self) -> None:
        """Send SIGTERM.  The process manager calls this on halt."""
        try:
            self.process.terminate()
        except ProcessLookupError:
            pass  # already dead


class ProcessManager:
    """Manages the set of currently-running worker subprocesses.

    The orchestrator holds one instance of this class for its lifetime.
    """

    def __init__(self) -> None:
        # Keyed by run_id so we can look up handles from job rows.
        self._handles: dict[str, WorkerHandle] = {}

    # ------------------------------------------------------------------
    # Launching
    # ------------------------------------------------------------------

    def launch_worker(
        self,
        job_type: str,
        run_id: str,
        *,
        extra_env: dict[str, str] | None = None,
    ) -> WorkerHandle:
        """Spawn a worker subprocess for the given job_type.

        Parameters
        ----------
        job_type:
            Must be a key in ``_JOB_ENTRY_POINTS``.
        run_id:
            UUID string passed as the first CLI argument to the worker.
        extra_env:
            Optional extra environment variables (e.g. ``ACCOUNT_TYPE=PAPER``
            for BOTH-mode parallelism).  Merged on top of the current env.

        Returns
        -------
        WorkerHandle
            Caller should store the PID from ``handle.pid`` into the jobs row
            via ``job_manager.mark_job_started``.

        Raises
        ------
        KeyError
            If ``job_type`` has no registered entry point.
        OSError
            If the subprocess fails to launch at the OS level.
        """
        entry_module = _JOB_ENTRY_POINTS[job_type]
        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)

        cmd = [sys.executable, "-m", entry_module, run_id]
        log.info("launching_worker", job_type=job_type, run_id=run_id, cmd=cmd)

        proc = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        handle = WorkerHandle(run_id=run_id, job_type=job_type, process=proc)
        self._handles[run_id] = handle
        log.info("worker_launched", job_type=job_type, run_id=run_id, pid=proc.pid)
        return handle

    # ------------------------------------------------------------------
    # Monitoring
    # ------------------------------------------------------------------

    def collect_finished(self) -> list[tuple[WorkerHandle, int]]:
        """Poll all tracked handles and return those that have exited.

        Returns a list of ``(handle, exit_code)`` pairs.  Finished handles are
        removed from the internal registry so they are not reported again.
        """
        finished: list[tuple[WorkerHandle, int]] = []
        still_running: dict[str, WorkerHandle] = {}
        for run_id, handle in self._handles.items():
            exit_code = handle.poll()
            if exit_code is not None:
                finished.append((handle, exit_code))
                log.info(
                    "worker_exited",
                    run_id=run_id,
                    job_type=handle.job_type,
                    exit_code=exit_code,
                )
            else:
                still_running[run_id] = handle
        self._handles = still_running
        return finished

    def terminate_all(self) -> None:
        """Send SIGTERM to every tracked subprocess.

        Called during HALT or graceful shutdown so workers are not left
        orphaned.
        """
        for run_id, handle in list(self._handles.items()):
            log.warning("terminating_worker", run_id=run_id, job_type=handle.job_type)
            handle.terminate()
        self._handles.clear()

    def active_run_ids(self) -> list[str]:
        """Return the run_ids of all currently-tracked (alive) workers."""
        return list(self._handles.keys())

    def get_handle(self, run_id: str) -> WorkerHandle | None:
        """Return the handle for a given run_id, or None."""
        return self._handles.get(run_id)
