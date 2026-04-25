"""
Integration-level unit tests for s1_orchestrator.main.Orchestrator.

All external dependencies (DB, config, subprocesses, background threads) are
mocked.  We test the orchestrator's logic in isolation: state transitions,
dispatch decisions, halt policy, and approval wiring.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


from shared.constants import ApprovalMode, JobStatus, SystemMode, SystemState
from s1_orchestrator.main import Orchestrator


def make_minimal_cfg(mode="PAPER", approval_mode="HARD"):
    return SimpleNamespace(
        system=SimpleNamespace(
            mode=mode,
            approval_mode=approval_mode,
            db_url="postgresql://test:test@localhost/test",
            log_level="INFO",
            log_dir="logs/",
            data_dir_ssd="data/",
            data_dir_hdd="/mnt/hdd/",
            allow_market_orders=False,
        ),
        risk=SimpleNamespace(
            halt_on_data_failure=True,
            halt_on_daily_loss=True,
        ),
        sentiment=SimpleNamespace(
            sentiment_threshold_positive=0.30,
        ),
    )


def build_orchestrator(mode="PAPER", approval_mode="HARD") -> Orchestrator:
    orch = Orchestrator()
    orch._mode = SystemMode(mode)
    orch._approval_mode = ApprovalMode(approval_mode)
    orch._soft_threshold = 0.5
    return orch


class TestOrchestratorStateTransitions:
    def test_initial_state_is_disabled(self):
        orch = build_orchestrator()
        assert orch._state.state == SystemState.DISABLED

    def test_force_halt_sets_halt_state(self):
        orch = build_orchestrator()
        orch._state._state = SystemState.IDLE
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        with patch("s1_orchestrator.main.get_session", return_value=mock_session):
            orch._force_halt("test reason")

        assert orch._state.is_halted()

    def test_force_halt_terminates_workers(self):
        orch = build_orchestrator()
        orch._state._state = SystemState.IDLE
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        with patch("s1_orchestrator.main.get_session", return_value=mock_session):
            orch._force_halt("test")


class TestDispatchJobs:
    def test_dispatch_blocked_when_halted(self):
        orch = build_orchestrator()
        orch._state._state = SystemState.HALT
        dispatched = []
        with patch.object(orch, "_launch_single_job", side_effect=lambda *a, **kw: dispatched.append(a)):
            orch._dispatch_jobs(["INGEST_EOD"])
        assert dispatched == []

    def test_dispatch_skipped_when_disabled(self):
        orch = build_orchestrator(mode="DISABLED")
        orch._state._state = SystemState.IDLE
        dispatched = []
        mock_cfg = make_minimal_cfg(mode="DISABLED")
        with patch("s1_orchestrator.main.get_config", return_value=mock_cfg):
            with patch.object(orch, "_launch_single_job", side_effect=lambda *a, **kw: dispatched.append(a)):
                orch._dispatch_jobs(["INGEST_EOD"])
        assert dispatched == []

    def test_both_mode_execute_launches_two_account_types(self):
        orch = build_orchestrator(mode="BOTH")
        orch._state._state = SystemState.IDLE
        launched = []
        mock_cfg = make_minimal_cfg(mode="BOTH")
        with patch("s1_orchestrator.main.get_config", return_value=mock_cfg):
            with patch.object(orch, "_launch_single_job", side_effect=lambda jt, cfg, **kw: launched.append(kw.get("account_type"))):
                orch._dispatch_jobs(["EXECUTE_ORDERS"])
        assert "PAPER" in launched
        assert "LIVE" in launched

    def test_single_mode_execute_launches_once(self):
        orch = build_orchestrator(mode="PAPER")
        orch._state._state = SystemState.IDLE
        launched = []
        mock_cfg = make_minimal_cfg(mode="PAPER")
        with patch("s1_orchestrator.main.get_config", return_value=mock_cfg):
            with patch.object(orch, "_launch_single_job", side_effect=lambda jt, cfg, **kw: launched.append(jt)):
                orch._dispatch_jobs(["EXECUTE_ORDERS"])
        assert len(launched) == 1

    def test_running_job_type_not_double_dispatched(self):
        orch = build_orchestrator()
        orch._state._state = SystemState.IDLE
        orch._running_job_types.add("INGEST_EOD")
        launched = []
        mock_cfg = make_minimal_cfg()
        with patch("s1_orchestrator.main.get_config", return_value=mock_cfg):
            with patch.object(orch, "_launch_single_job", side_effect=lambda *a, **kw: launched.append(a)):
                orch._dispatch_jobs(["INGEST_EOD"])
        assert launched == []


class TestHandleWorkerExit:
    def _make_job(self, job_type="INGEST_EOD"):
        job = MagicMock()
        job.run_id = str(uuid.uuid4())
        job.job_type = job_type
        job.status = JobStatus.RUNNING.value
        return job

    def test_exit_code_0_calls_mark_completed(self):
        orch = build_orchestrator()
        job = self._make_job("RECONCILE")
        orch._state._state = SystemState.MONITORING

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        with patch("s1_orchestrator.main.get_session", return_value=mock_session):
            with patch("s1_orchestrator.main.get_job_by_run_id", return_value=job):
                with patch("s1_orchestrator.main.mark_job_completed") as mock_complete:
                    with patch("s1_orchestrator.main.mark_job_failed") as mock_fail:
                        orch._handle_worker_exit(job.run_id, "RECONCILE", 0)

        mock_complete.assert_called_once()
        mock_fail.assert_not_called()

    def test_non_zero_exit_calls_mark_failed(self):
        orch = build_orchestrator()
        job = self._make_job("RUN_SIGNALS")
        orch._state._state = SystemState.PROCESSING

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        mock_cfg = make_minimal_cfg()
        with patch("s1_orchestrator.main.get_session", return_value=mock_session):
            with patch("s1_orchestrator.main.get_job_by_run_id", return_value=job):
                with patch("s1_orchestrator.main.get_config", return_value=mock_cfg):
                    with patch("s1_orchestrator.main.mark_job_completed") as mock_complete:
                        with patch("s1_orchestrator.main.mark_job_failed") as mock_fail:
                            orch._handle_worker_exit(job.run_id, "RUN_SIGNALS", 1)

        mock_fail.assert_called_once()
        mock_complete.assert_not_called()

    def test_ingest_failure_halts_when_configured(self):
        orch = build_orchestrator()
        orch._state._state = SystemState.INGESTING
        job = self._make_job("INGEST_EOD")

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        mock_cfg = make_minimal_cfg()
        with patch("s1_orchestrator.main.get_session", return_value=mock_session):
            with patch("s1_orchestrator.main.get_job_by_run_id", return_value=job):
                with patch("s1_orchestrator.main.mark_job_failed"):
                    with patch("s1_orchestrator.main.get_config", return_value=mock_cfg):
                        with patch.object(orch, "_force_halt") as mock_halt:
                            orch._handle_worker_exit(job.run_id, "INGEST_EOD", 1)

        mock_halt.assert_called_once()


class TestEnterApprovalState:
    def test_transitions_to_pending_approval(self):
        orch = build_orchestrator()
        orch._state._state = SystemState.IDLE
        run_id = str(uuid.uuid4())
        orch._active_run_ids[run_id] = "PAPER"

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        with patch("s1_orchestrator.main.get_session", return_value=mock_session):
            with patch("s1_orchestrator.main.ApprovalManager") as mock_am_cls:
                mock_am = MagicMock()
                mock_am.process_pending_signals.return_value = (0, 3)
                mock_am_cls.return_value = mock_am
                orch._enter_approval_state(run_id)

        assert orch._state.state == SystemState.PENDING_APPROVAL
        assert orch._pending_approval_run_id == run_id

    def test_no_pending_after_auto_approve_resolves_immediately(self):
        orch = build_orchestrator()
        orch._state._state = SystemState.IDLE
        run_id = str(uuid.uuid4())
        orch._active_run_ids[run_id] = "PAPER"

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter.return_value.count.return_value = 0

        with patch("s1_orchestrator.main.get_session", return_value=mock_session):
            with patch("s1_orchestrator.main.ApprovalManager") as mock_am_cls:
                mock_am = MagicMock()
                mock_am.process_pending_signals.return_value = (5, 0)
                mock_am_cls.return_value = mock_am
                orch._enter_approval_state(run_id)

        assert orch._pending_approval_run_id is None


class TestOnModeChanged:
    def test_mode_updated(self):
        orch = build_orchestrator()
        orch._on_mode_changed(SystemMode.LIVE, ApprovalMode.HARD)
        assert orch._mode == SystemMode.LIVE
        assert orch._approval_mode == ApprovalMode.HARD

    def test_switching_to_disabled_triggers_halt(self):
        orch = build_orchestrator()
        orch._state._state = SystemState.IDLE

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        with patch("s1_orchestrator.main.get_session", return_value=mock_session):
            with patch.object(orch, "_force_halt") as mock_halt:
                orch._on_mode_changed(SystemMode.DISABLED, ApprovalMode.HARD)

        mock_halt.assert_called_once()


class TestHandleCriticalException:
    def test_writes_critical_event_and_halts(self):
        orch = build_orchestrator()
        orch._state._state = SystemState.IDLE

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        with patch("s1_orchestrator.main.get_session", return_value=mock_session):
            orch._handle_critical_exception(RuntimeError("boom"))

        assert orch._state.is_halted()
