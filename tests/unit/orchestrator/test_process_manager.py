"""Tests for algotrader.orchestrator.process_manager."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from algotrader.orchestrator.process_manager import ProcessManager


def make_popen(pid=1234, returncode=None):
    proc = MagicMock()
    proc.pid = pid
    proc.poll.return_value = returncode
    return proc


class TestLaunchWorker:
    def test_launch_creates_handle(self):
        mgr = ProcessManager()
        mock_proc = make_popen(pid=9999)
        with patch("algotrader.orchestrator.process_manager.subprocess.Popen", return_value=mock_proc):
            handle = mgr.launch_worker("INGEST_EOD", "some-run-id")
        assert handle.pid == 9999
        assert handle.run_id == "some-run-id"
        assert handle.job_type == "INGEST_EOD"

    def test_launch_with_extra_env(self):
        mgr = ProcessManager()
        mock_proc = make_popen()
        with patch("algotrader.orchestrator.process_manager.subprocess.Popen", return_value=mock_proc) as popen:
            mgr.launch_worker("EXECUTE_ORDERS", "rid", extra_env={"ACCOUNT_TYPE": "LIVE"})
            call_env = popen.call_args.kwargs["env"]
            assert call_env.get("ACCOUNT_TYPE") == "LIVE"

    def test_launch_unknown_job_type_raises(self):
        mgr = ProcessManager()
        with pytest.raises(KeyError):
            mgr.launch_worker("NONEXISTENT_JOB", "rid")

    def test_handle_stored_in_registry(self):
        mgr = ProcessManager()
        run_id = str(uuid.uuid4())
        mock_proc = make_popen(pid=42)
        with patch("algotrader.orchestrator.process_manager.subprocess.Popen", return_value=mock_proc):
            mgr.launch_worker("RUN_SIGNALS", run_id)
        assert mgr.get_handle(run_id) is not None


class TestCollectFinished:
    def test_finished_workers_removed_from_registry(self):
        mgr = ProcessManager()
        run_id = str(uuid.uuid4())
        proc = make_popen(pid=10, returncode=0)
        with patch("algotrader.orchestrator.process_manager.subprocess.Popen", return_value=proc):
            mgr.launch_worker("RUN_SENTIMENT", run_id)

        finished = mgr.collect_finished()
        assert len(finished) == 1
        handle, code = finished[0]
        assert code == 0
        assert mgr.get_handle(run_id) is None  # removed

    def test_alive_workers_stay_in_registry(self):
        mgr = ProcessManager()
        run_id = str(uuid.uuid4())
        proc = make_popen(pid=20, returncode=None)  # still running
        with patch("algotrader.orchestrator.process_manager.subprocess.Popen", return_value=proc):
            mgr.launch_worker("RUN_BACKTEST", run_id)

        finished = mgr.collect_finished()
        assert finished == []
        assert mgr.get_handle(run_id) is not None

    def test_non_zero_exit_code_captured(self):
        mgr = ProcessManager()
        proc = make_popen(pid=30, returncode=1)
        with patch("algotrader.orchestrator.process_manager.subprocess.Popen", return_value=proc):
            mgr.launch_worker("RECONCILE", "rid2")

        finished = mgr.collect_finished()
        _, code = finished[0]
        assert code == 1


class TestTerminateAll:
    def test_terminate_all_calls_terminate(self):
        mgr = ProcessManager()
        proc = make_popen(returncode=None)
        with patch("algotrader.orchestrator.process_manager.subprocess.Popen", return_value=proc):
            mgr.launch_worker("EXECUTE_ORDERS", "rid3")

        mgr.terminate_all()
        proc.terminate.assert_called_once()
        assert mgr.active_run_ids() == []

    def test_terminate_all_noop_when_empty(self):
        mgr = ProcessManager()
        mgr.terminate_all()  # must not raise


class TestActiveRunIds:
    def test_returns_tracked_run_ids(self):
        mgr = ProcessManager()
        proc = make_popen(returncode=None)
        with patch("algotrader.orchestrator.process_manager.subprocess.Popen", return_value=proc):
            mgr.launch_worker("RUN_SIGNALS", "abc")
            mgr.launch_worker("RUN_BACKTEST", "def")
        ids = mgr.active_run_ids()
        assert "abc" in ids
        assert "def" in ids
