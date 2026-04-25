"""
S1 — Orchestrator entry point.

Requirements
------------
apscheduler>=3.10
sqlalchemy>=2.0
structlog>=24.0
pydantic>=2.0

This module owns:
- Startup / shutdown lifecycle
- The system state machine (via StateMachine)
- Worker dispatch and monitoring (via JobScheduler + ProcessManager)
- Approval policy enforcement (via ApprovalManager)
- External event reaction (via EventHandler)
- Stale job + CRITICAL event detection (via Watchdog)

Design principles:
- This is the *only* module that knows the system's current runtime mode.
- It never generates signals, scores sentiment, submits orders, or touches the
  IBKR API.
- On any unhandled exception it writes a CRITICAL event and enters HALT.
- Paper vs live routing is managed here for BOTH mode; every other module is
  mode-agnostic.
"""

from __future__ import annotations

import signal as _signal
import threading
import time
import uuid
from datetime import datetime, timezone

from algotrader.shared.config_loader import get_config
from algotrader.shared.constants import (
    ApprovalMode,
    EventType,
    Severity,
    SignalStatus,
    SystemMode,
    SystemState,
)
from algotrader.shared.db import get_session, init_db
from algotrader.shared.exceptions import ConfigError
from algotrader.shared.logger import get_logger
from algotrader.shared.models import Signal, SystemEvent

from algotrader.orchestrator.approval_manager import ApprovalManager
from algotrader.orchestrator.event_handler import EventHandler
from algotrader.orchestrator.job_manager import (
    create_job,
    get_job_by_run_id,
    mark_job_completed,
    mark_job_failed,
    mark_job_started,
)
from algotrader.orchestrator.process_manager import ProcessManager
from algotrader.orchestrator.scheduler import JobScheduler
from algotrader.orchestrator.state_machine import StateMachine
from algotrader.orchestrator.watchdog import Watchdog

log = get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


_MAIN_LOOP_SLEEP = 5
_APPROVAL_POLL_SLEEP = 15
_MONITOR_POLL_SLEEP = 300  # 5 minutes


class Orchestrator:
    """The AlgoTrader system orchestrator.

    Instantiate once and call ``run()`` to start the event loop.  ``run()``
    blocks until the process receives SIGTERM / SIGINT or an irrecoverable
    error forces a halt.

    Parameters
    ----------
    config_path:
        Not used at runtime (config is read via ``get_config()``); kept as a
        hook for integration tests that need to override config before startup.
    """

    def __init__(self, config_path: str | None = None) -> None:  # noqa: ARG002
        self._state = StateMachine(SystemState.DISABLED)
        self._process_manager = ProcessManager()
        self._mode: SystemMode = SystemMode.PAPER
        self._approval_mode: ApprovalMode = ApprovalMode.HARD
        self._soft_threshold: float = 0.5

        self._active_run_ids: dict[str, str] = {}
        self._running_job_types: set[str] = set()
        self._running_lock = threading.Lock()
        self._pending_approval_run_id: str | None = None
        self._shutdown_requested = threading.Event()

        self._scheduler: JobScheduler | None = None
        self._watchdog: Watchdog | None = None
        self._event_handler: EventHandler | None = None

    def run(self) -> None:
        """Start the orchestrator and block until shutdown."""
        try:
            self._startup()
            self._main_loop()
        except KeyboardInterrupt:
            log.info("orchestrator_keyboard_interrupt")
        except Exception as exc:
            self._handle_critical_exception(exc)
        finally:
            self._shutdown()

    def _startup(self) -> None:
        """Initialise DB, load config, spin up sub-components."""
        self._state.transition(SystemState.STARTING, reason="orchestrator startup")

        cfg = get_config()
        init_db(cfg.system.db_url)

        self._mode = SystemMode(cfg.system.mode)
        self._approval_mode = ApprovalMode(cfg.system.approval_mode)

        try:
            self._soft_threshold = float(cfg.sentiment.sentiment_threshold_positive)
        except AttributeError:
            self._soft_threshold = 0.5

        _signal.signal(_signal.SIGTERM, self._handle_sigterm)
        _signal.signal(_signal.SIGINT, self._handle_sigterm)

        self._write_startup_event()

        self._watchdog = Watchdog(
            force_halt_callback=self._force_halt,
            poll_interval_seconds=60,
        )
        self._watchdog.start()

        self._event_handler = EventHandler(
            on_mode_changed=self._on_mode_changed,
            on_config_changed=self._on_config_changed,
            on_user_halt=self._force_halt,
            on_user_resume=self._on_user_resume,
            poll_interval_seconds=30,
        )
        self._event_handler.start()

        self._scheduler = JobScheduler(dispatch_callback=self._dispatch_jobs)
        self._scheduler.start()

        if self._mode == SystemMode.DISABLED:
            log.info("orchestrator_disabled_mode")
        else:
            self._state.transition(SystemState.IDLE, reason="startup complete")

        log.info(
            "orchestrator_ready",
            mode=self._mode.value,
            approval_mode=self._approval_mode.value,
        )

    def _main_loop(self) -> None:
        """Block, polling for finished workers and pending approvals."""
        while not self._shutdown_requested.is_set():
            if self._state.is_halted():
                time.sleep(_MAIN_LOOP_SLEEP)
                continue

            finished = self._process_manager.collect_finished()
            for handle, exit_code in finished:
                self._handle_worker_exit(handle.run_id, handle.job_type, exit_code)

            if self._state.state == SystemState.PENDING_APPROVAL:
                self._poll_approval_progress()

            time.sleep(_MAIN_LOOP_SLEEP)

    def _dispatch_jobs(self, job_types: list[str]) -> None:
        """Launch worker processes for each job_type in the list.

        Skips job_types already running to prevent duplicate fires.
        In BOTH mode, execution jobs are launched twice with separate account_type env vars.
        """
        if self._state.is_halted():
            log.warning("dispatch_blocked_halted", job_types=job_types)
            return

        if self._mode == SystemMode.DISABLED:
            log.info("dispatch_skipped_disabled", job_types=job_types)
            return

        cfg = get_config()

        for job_type in job_types:
            with self._running_lock:
                if job_type in self._running_job_types:
                    log.warning("dispatch_skip_already_running", job_type=job_type)
                    continue
                self._running_job_types.add(job_type)

            if self._mode == SystemMode.BOTH and job_type in ("EXECUTE_ORDERS", "RECONCILE"):
                self._launch_single_job(job_type, cfg, account_type="PAPER")
                self._launch_single_job(job_type, cfg, account_type="LIVE")
            else:
                self._launch_single_job(job_type, cfg)

    def _launch_single_job(self, job_type: str, cfg, *, account_type: str | None = None) -> None:
        """Create a job row, launch the subprocess, record PID."""
        run_id = str(uuid.uuid4())
        extra_env: dict[str, str] = {}
        if account_type:
            extra_env["ACCOUNT_TYPE"] = account_type

        try:
            with get_session() as session:
                job = create_job(session, job_type, cfg, run_id=run_id)
                session.flush()
                handle = self._process_manager.launch_worker(
                    job_type, run_id, extra_env=extra_env or None
                )
                mark_job_started(session, job, handle.pid)
                session.commit()

            self._active_run_ids[run_id] = account_type or "DEFAULT"
            log.info(
                "job_dispatched",
                job_type=job_type,
                run_id=run_id,
                pid=handle.pid,
                account_type=account_type,
            )
        except Exception as exc:
            log.error("job_dispatch_error", job_type=job_type, error=str(exc))
            with self._running_lock:
                self._running_job_types.discard(job_type)
            self._write_event(
                event_type=EventType.JOB_FAILED.value,
                severity=Severity.ERROR.value,
                message=f"Failed to dispatch {job_type}: {exc}",
                run_id=run_id,
            )

    def _handle_worker_exit(self, run_id: str, job_type: str, exit_code: int) -> None:
        """Update the job row and advance state machine on worker completion."""
        with self._running_lock:
            self._running_job_types.discard(job_type)

        with get_session() as session:
            job = get_job_by_run_id(session, run_id)
            if job is None:
                log.warning("worker_exit_no_job_row", run_id=run_id)
                return

            if exit_code == 0:
                mark_job_completed(session, job)
                session.commit()
                self._advance_state_after_job(job_type, run_id)
            else:
                mark_job_failed(session, job, f"Worker exited with code {exit_code}")
                session.commit()
                self._handle_job_failure(job_type, run_id, exit_code)

        self._active_run_ids.pop(run_id, None)

    def _advance_state_after_job(self, job_type: str, run_id: str) -> None:
        """Attempt state machine transitions after a successful job completion."""
        try:
            current = self._state.state
            if job_type in ("INGEST_EOD", "RUN_SENTIMENT"):
                if current == SystemState.INGESTING:
                    self._state.transition(SystemState.IDLE, reason=f"{job_type} complete")
            elif job_type == "RUN_SIGNALS":
                if current in (SystemState.PROCESSING, SystemState.IDLE):
                    self._enter_approval_state(run_id)
            elif job_type == "EXECUTE_ORDERS":
                if current in (
                    SystemState.EXECUTING,
                    SystemState.APPROVED,
                    SystemState.PARTIALLY_APPROVED,
                ):
                    self._state.transition(SystemState.MONITORING, reason="orders submitted")
            elif job_type == "RECONCILE":
                if current in (SystemState.MONITORING, SystemState.RECONCILING):
                    self._state.transition(SystemState.IDLE, reason="reconciliation complete")
            elif job_type == "RUN_BACKTEST":
                log.info("backtest_complete", run_id=run_id)
        except ConfigError as exc:
            log.warning("state_advance_skipped", reason=str(exc))

    def _handle_job_failure(self, job_type: str, run_id: str, exit_code: int) -> None:
        """React to a non-zero worker exit code."""
        cfg = get_config()
        risk_cfg = getattr(cfg, "risk", None)

        if job_type == "INGEST_EOD":
            halt_on_data_failure = getattr(risk_cfg, "halt_on_data_failure", True)
            if halt_on_data_failure:
                self._force_halt(f"Data ingestion failed (exit {exit_code})")
        else:
            log.warning(
                "non_critical_job_failure",
                job_type=job_type,
                run_id=run_id,
                exit_code=exit_code,
            )

    def _enter_approval_state(self, run_id: str) -> None:
        """Move to PENDING_APPROVAL and run the first approval pass."""
        try:
            self._state.transition(SystemState.PENDING_APPROVAL, reason="signals ready")
        except ConfigError as exc:
            log.warning("approval_state_skip", reason=str(exc))
            return

        self._pending_approval_run_id = run_id
        account_type = self._active_run_ids.get(run_id, "PAPER")

        approval_mgr = ApprovalManager(
            approval_mode=self._approval_mode,
            system_mode=self._mode,
            soft_threshold=self._soft_threshold,
        )

        with get_session() as session:
            n_approved, n_pending = approval_mgr.process_pending_signals(
                session, run_id, account_type=account_type
            )
            session.commit()

        log.info(
            "approval_initial_pass",
            run_id=run_id,
            n_approved=n_approved,
            n_pending=n_pending,
        )

        if n_pending == 0:
            self._resolve_approval(run_id)

    def _poll_approval_progress(self) -> None:
        """Check whether the dashboard has finished approving pending signals."""
        run_id = self._pending_approval_run_id
        if run_id is None:
            return

        approval_mgr = ApprovalManager(
            approval_mode=self._approval_mode,
            system_mode=self._mode,
            soft_threshold=self._soft_threshold,
        )

        with get_session() as session:
            all_done = approval_mgr.has_all_approved(session, run_id)

        if all_done:
            self._resolve_approval(run_id)

    def _resolve_approval(self, run_id: str) -> None:
        """Advance past PENDING_APPROVAL to APPROVED, PARTIALLY_APPROVED, or IDLE."""
        self._pending_approval_run_id = None

        with get_session() as session:
            any_approved = (
                session.query(Signal)
                .filter(
                    Signal.run_id == run_id,
                    Signal.status == SignalStatus.APPROVED.value,
                )
                .count()
                > 0
            )
            still_pending = (
                session.query(Signal)
                .filter(
                    Signal.run_id == run_id,
                    Signal.status == SignalStatus.PENDING.value,
                )
                .count()
                > 0
            )

        try:
            if any_approved and still_pending:
                self._state.transition(
                    SystemState.PARTIALLY_APPROVED, reason="some signals approved"
                )
            elif any_approved:
                self._state.transition(
                    SystemState.APPROVED, reason="all actioned signals approved"
                )
            else:
                self._state.transition(SystemState.IDLE, reason="no signals approved")
        except ConfigError as exc:
            log.warning("resolve_approval_transition_failed", reason=str(exc))

    def _on_mode_changed(self, new_mode: SystemMode, new_approval: ApprovalMode) -> None:
        """Update runtime mode; halt if switching to DISABLED."""
        old_mode = self._mode
        self._mode = new_mode
        self._approval_mode = new_approval
        log.info(
            "runtime_mode_updated",
            old_mode=old_mode.value,
            new_mode=new_mode.value,
            approval_mode=new_approval.value,
        )
        if new_mode == SystemMode.DISABLED and not self._state.is_halted():
            self._force_halt("Mode changed to DISABLED")

    def _on_config_changed(self) -> None:
        """Invalidate config cache and schedule a comparison backtest (spec §6.2 step 3)."""
        log.info("config_changed_scheduling_backtest")
        self._dispatch_jobs(["RUN_BACKTEST"])

    def _on_user_resume(self) -> None:
        """Return the system from HALT to IDLE after an operator RESUME action (§7.2)."""
        if not self._state.is_halted():
            log.info("user_resume_ignored_not_halted", state=self._state.state.value)
            return
        try:
            self._state.transition(SystemState.IDLE, reason="operator resume via dashboard")
            log.info("system_resumed")
        except Exception as exc:
            log.error("user_resume_transition_failed", error=str(exc))

    def _force_halt(self, reason: str) -> None:
        """Force-halt: unconditional state override + kill workers + write CRITICAL event."""
        self._state.force_halt(reason)
        self._process_manager.terminate_all()
        self._write_event(
            event_type=EventType.RISK_HALT.value,
            severity=Severity.CRITICAL.value,
            message=f"System halted: {reason}",
        )
        log.warning("system_halted", reason=reason)

    def _handle_critical_exception(self, exc: Exception) -> None:
        """Top-level exception handler — writes CRITICAL event and enters HALT."""
        log.exception("orchestrator_critical_exception", error=str(exc))
        try:
            self._write_event(
                event_type=EventType.RISK_HALT.value,
                severity=Severity.CRITICAL.value,
                message=f"Unhandled exception in orchestrator: {exc}",
            )
            self._state.force_halt(f"Unhandled exception: {exc}")
            self._process_manager.terminate_all()
        except Exception as inner:
            log.error("critical_handler_failed", error=str(inner))

    def _shutdown(self) -> None:
        """Graceful shutdown: stop sub-components and write SHUTDOWN event."""
        log.info("orchestrator_shutdown_begin")
        if self._scheduler:
            self._scheduler.stop()
        if self._event_handler:
            self._event_handler.stop()
        if self._watchdog:
            self._watchdog.stop()
        self._process_manager.terminate_all()
        self._write_event(
            event_type=EventType.SHUTDOWN.value,
            severity=Severity.INFO.value,
            message="Orchestrator shut down cleanly",
        )
        log.info("orchestrator_shutdown_complete")

    def _handle_sigterm(self, signum: int, frame) -> None:
        log.info("signal_received", signum=signum)
        self._shutdown_requested.set()

    def _write_startup_event(self) -> None:
        self._write_event(
            event_type=EventType.STARTUP.value,
            severity=Severity.INFO.value,
            message=(
                f"Orchestrator starting. mode={self._mode.value}, "
                f"approval={self._approval_mode.value}"
            ),
        )

    def _write_event(
        self,
        *,
        event_type: str,
        severity: str,
        message: str,
        run_id: str | None = None,
        payload: dict | None = None,
    ) -> None:
        """Write a system_events row; best-effort (never raises)."""
        try:
            with get_session() as session:
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
                session.commit()
        except Exception as exc:
            log.error("write_event_failed", event_type=event_type, error=str(exc))


def main() -> None:
    """Start the orchestrator from the command line or a systemd unit."""
    orchestrator = Orchestrator()
    orchestrator.run()


if __name__ == "__main__":
    main()
