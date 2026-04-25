"""Tests for s1_orchestrator.watchdog."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch


from s1_orchestrator.watchdog import Watchdog


def make_session_with_events(events):
    """Build a mock session whose query chain returns the given list."""
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    # watchdog uses: session.query(X).filter(A, B).order_by(Y).all()
    (
        session.query.return_value
        .filter.return_value
        .order_by.return_value
        .all.return_value
    ) = events
    return session


def make_session_no_stale():
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    session.query.return_value.filter.return_value.all.return_value = []
    (
        session.query.return_value
        .filter.return_value
        .order_by.return_value
        .all.return_value
    ) = []
    return session


class TestWatchdogStaleJobDetection:
    def test_stale_jobs_are_reset(self):
        halt_called = []

        stale_job = MagicMock()
        stale_job.run_id = str(uuid.uuid4())
        stale_job.job_type = "INGEST_EOD"

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter.return_value.all.return_value = [stale_job]

        with patch("s1_orchestrator.watchdog.get_session", return_value=mock_session), \
             patch("s1_orchestrator.watchdog.get_stale_running_jobs", return_value=[stale_job]), \
             patch("s1_orchestrator.watchdog.mark_job_failed") as mock_fail:
            wd = Watchdog(force_halt_callback=lambda r: halt_called.append(r), poll_interval_seconds=999)
            wd._check_stale_jobs()
            mock_fail.assert_called_once()
            assert mock_fail.call_args.kwargs.get("retryable") is True

    def test_no_stale_jobs_does_nothing(self):
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)

        with patch("s1_orchestrator.watchdog.get_session", return_value=mock_session), \
             patch("s1_orchestrator.watchdog.get_stale_running_jobs", return_value=[]), \
             patch("s1_orchestrator.watchdog.mark_job_failed") as mock_fail:
            wd = Watchdog(force_halt_callback=lambda r: None)
            wd._check_stale_jobs()
            mock_fail.assert_not_called()


class TestWatchdogCriticalEventDetection:
    def test_critical_event_triggers_halt(self):
        halt_reasons = []

        critical_event = MagicMock()
        critical_event.event_type = "RISK_HALT"
        critical_event.subsystem = "S6"
        critical_event.message = "Risk breach"
        critical_event.timestamp = datetime.now(tz=timezone.utc)

        session = make_session_with_events([critical_event])

        with patch("s1_orchestrator.watchdog.get_session", return_value=session):
            wd = Watchdog(force_halt_callback=lambda r: halt_reasons.append(r))
            wd._check_critical_events()

        assert len(halt_reasons) == 1
        assert "S6" in halt_reasons[0]

    def test_no_critical_events_does_not_halt(self):
        halt_reasons = []
        session = make_session_with_events([])

        with patch("s1_orchestrator.watchdog.get_session", return_value=session):
            wd = Watchdog(force_halt_callback=lambda r: halt_reasons.append(r))
            wd._check_critical_events()

        assert halt_reasons == []

    def test_watermark_advances_after_event(self):
        t = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        critical_event = MagicMock()
        critical_event.event_type = "RISK_HALT"
        critical_event.subsystem = "S1"
        critical_event.message = "test"
        critical_event.timestamp = t

        session = make_session_with_events([critical_event])

        with patch("s1_orchestrator.watchdog.get_session", return_value=session):
            wd = Watchdog(force_halt_callback=lambda r: None)
            wd._check_critical_events()

        assert wd._started_at == t


class TestWatchdogLifecycle:
    def test_start_and_stop(self):
        session = make_session_no_stale()
        with patch("s1_orchestrator.watchdog.get_session", return_value=session), \
             patch("s1_orchestrator.watchdog.get_stale_running_jobs", return_value=[]):
            wd = Watchdog(force_halt_callback=lambda r: None, poll_interval_seconds=999)
            wd.start()
            assert wd._thread.is_alive()
            wd.stop()
            assert not wd._thread.is_alive()
