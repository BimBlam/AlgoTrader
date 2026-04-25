"""Tests for s1_orchestrator.scheduler."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


from s1_orchestrator.scheduler import JobScheduler, _SCHEDULE


class TestSchedulerRegistration:
    def test_all_jobs_registered(self):
        callback = MagicMock()
        with patch("s1_orchestrator.scheduler.BackgroundScheduler") as mock_sched_cls:
            mock_sched = MagicMock()
            mock_sched_cls.return_value = mock_sched
            JobScheduler(dispatch_callback=callback)

        expected_ids = {s[0] for s in _SCHEDULE}
        # All job IDs in _SCHEDULE must have been registered.
        for jid in expected_ids:
            assert any(
                jid == ca.kwargs.get("id") for ca in mock_sched.add_job.call_args_list
            ), f"Job {jid} not registered"

    def test_start_calls_scheduler_start(self):
        callback = MagicMock()
        with patch("s1_orchestrator.scheduler.BackgroundScheduler") as mock_sched_cls:
            mock_sched = MagicMock()
            mock_sched_cls.return_value = mock_sched
            scheduler = JobScheduler(dispatch_callback=callback)
            scheduler.start()
        mock_sched.start.assert_called_once()

    def test_stop_calls_scheduler_shutdown(self):
        callback = MagicMock()
        with patch("s1_orchestrator.scheduler.BackgroundScheduler") as mock_sched_cls:
            mock_sched = MagicMock()
            mock_sched_cls.return_value = mock_sched
            scheduler = JobScheduler(dispatch_callback=callback)
            scheduler.stop()
        mock_sched.shutdown.assert_called_once_with(wait=False)


class TestDispatchCallback:
    def test_dispatch_fn_calls_callback_with_job_types(self):
        received = []

        def callback(job_types):
            received.extend(job_types)

        with patch("s1_orchestrator.scheduler.BackgroundScheduler"):
            scheduler = JobScheduler(dispatch_callback=callback)

        # Manually invoke the dispatch function for the ingest+sentiment slot.
        fn = scheduler._make_dispatch_fn(["INGEST_EOD", "RUN_SENTIMENT"])
        fn()
        assert "INGEST_EOD" in received
        assert "RUN_SENTIMENT" in received

    def test_dispatch_fn_does_not_raise_on_callback_error(self):
        def bad_callback(job_types):
            raise RuntimeError("boom")

        with patch("s1_orchestrator.scheduler.BackgroundScheduler"):
            scheduler = JobScheduler(dispatch_callback=bad_callback)

        fn = scheduler._make_dispatch_fn(["INGEST_EOD"])
        fn()  # must not propagate


class TestGetNextFireTime:
    def test_returns_none_for_unknown_job(self):
        callback = MagicMock()
        with patch("s1_orchestrator.scheduler.BackgroundScheduler") as mock_sched_cls:
            mock_sched = MagicMock()
            mock_sched.get_job.return_value = None
            mock_sched_cls.return_value = mock_sched
            scheduler = JobScheduler(dispatch_callback=callback)
            result = scheduler.get_next_fire_time("nonexistent_job")
        assert result is None


class TestScheduleDefinition:
    """Validate that the hard-coded schedule matches spec §2.3."""

    def _find(self, job_id):
        return next(s for s in _SCHEDULE if s[0] == job_id)

    def test_ingest_at_21_00_weekdays(self):
        entry = self._find("ingest_and_sentiment")
        cron = entry[1]
        assert cron["hour"] == 21
        assert cron["minute"] == 0
        assert cron["day_of_week"] == "mon-fri"

    def test_ingest_dispatches_both_s2_and_s5(self):
        entry = self._find("ingest_and_sentiment")
        job_types = entry[2]
        assert "INGEST_EOD" in job_types
        assert "RUN_SENTIMENT" in job_types

    def test_signals_at_21_30_weekdays(self):
        entry = self._find("run_signals")
        cron = entry[1]
        assert cron["hour"] == 21
        assert cron["minute"] == 30

    def test_execute_at_09_25_weekdays(self):
        entry = self._find("execute_orders")
        cron = entry[1]
        assert cron["hour"] == 9
        assert cron["minute"] == 25

    def test_reconcile_at_16_30_weekdays(self):
        entry = self._find("reconcile")
        cron = entry[1]
        assert cron["hour"] == 16
        assert cron["minute"] == 30

    def test_backtest_sunday_20_00(self):
        entry = self._find("weekly_backtest")
        cron = entry[1]
        assert cron["hour"] == 20
        assert cron["minute"] == 0
        assert cron["day_of_week"] == "sun"
