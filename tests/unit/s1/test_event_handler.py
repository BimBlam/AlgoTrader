"""Tests for s1_orchestrator.event_handler."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch


from shared.constants import ApprovalMode, SystemMode
from s1_orchestrator.event_handler import EventHandler


def make_session(events=None):
    """Build a session mock that returns events from a single-filter query chain.

    EventHandler._poll() uses:
      session.query(X).filter(A, B).order_by(C).all()
    """
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    (
        session.query.return_value
        .filter.return_value
        .order_by.return_value
        .all.return_value
    ) = events or []
    return session


class TestModeChangedHandling:
    def test_mode_changed_calls_on_mode_changed_callback(self):
        received = []

        def on_mode_changed(mode, approval):
            received.append((mode, approval))

        event = MagicMock()
        event.event_type = "MODE_CHANGED"
        event.timestamp = datetime.now(tz=timezone.utc)
        session = make_session(events=[event])

        mock_cfg = MagicMock()
        mock_cfg.system.mode = "LIVE"
        mock_cfg.system.approval_mode = "HARD"

        with patch("s1_orchestrator.event_handler.get_session", return_value=session), \
             patch("s1_orchestrator.event_handler.get_config", return_value=mock_cfg), \
             patch("s1_orchestrator.event_handler.invalidate_cache"):
            handler = EventHandler(
                on_mode_changed=on_mode_changed,
                on_config_changed=lambda: None,
                poll_interval_seconds=999,
            )
            handler._poll()

        assert len(received) == 1
        mode, approval = received[0]
        assert mode == SystemMode.LIVE
        assert approval == ApprovalMode.HARD

    def test_invalidate_cache_called_on_mode_change(self):
        event = MagicMock()
        event.event_type = "MODE_CHANGED"
        event.timestamp = datetime.now(tz=timezone.utc)
        session = make_session(events=[event])

        mock_cfg = MagicMock()
        mock_cfg.system.mode = "PAPER"
        mock_cfg.system.approval_mode = "HARD"

        with patch("s1_orchestrator.event_handler.get_session", return_value=session), \
             patch("s1_orchestrator.event_handler.get_config", return_value=mock_cfg), \
             patch("s1_orchestrator.event_handler.invalidate_cache") as mock_inv:
            handler = EventHandler(
                on_mode_changed=lambda m, a: None,
                on_config_changed=lambda: None,
                poll_interval_seconds=999,
            )
            handler._poll()

        mock_inv.assert_called_once()


class TestConfigChangedHandling:
    def test_config_changed_calls_on_config_changed_callback(self):
        called = []

        def on_config_changed():
            called.append(True)

        event = MagicMock()
        event.event_type = "CONFIG_CHANGED"
        event.timestamp = datetime.now(tz=timezone.utc)
        session = make_session(events=[event])

        with patch("s1_orchestrator.event_handler.get_session", return_value=session), \
             patch("s1_orchestrator.event_handler.invalidate_cache"):
            handler = EventHandler(
                on_mode_changed=lambda m, a: None,
                on_config_changed=on_config_changed,
                poll_interval_seconds=999,
            )
            handler._poll()

        assert called == [True]

    def test_invalidate_cache_called_on_config_change(self):
        event = MagicMock()
        event.event_type = "CONFIG_CHANGED"
        event.timestamp = datetime.now(tz=timezone.utc)
        session = make_session(events=[event])

        with patch("s1_orchestrator.event_handler.get_session", return_value=session), \
             patch("s1_orchestrator.event_handler.invalidate_cache") as mock_inv:
            handler = EventHandler(
                on_mode_changed=lambda m, a: None,
                on_config_changed=lambda: None,
                poll_interval_seconds=999,
            )
            handler._poll()

        mock_inv.assert_called_once()


class TestNoEvents:
    def test_no_events_does_nothing(self):
        called = []
        session = make_session(events=[])

        with patch("s1_orchestrator.event_handler.get_session", return_value=session):
            handler = EventHandler(
                on_mode_changed=lambda m, a: called.append("mode"),
                on_config_changed=lambda: called.append("cfg"),
                poll_interval_seconds=999,
            )
            handler._poll()

        assert called == []


class TestWatermarkAdvances:
    def test_watermark_moves_to_latest_event_timestamp(self):
        t1 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 1, 1, 10, 5, 0, tzinfo=timezone.utc)

        e1 = MagicMock()
        e1.event_type = "CONFIG_CHANGED"
        e1.timestamp = t1

        e2 = MagicMock()
        e2.event_type = "CONFIG_CHANGED"
        e2.timestamp = t2

        session = make_session(events=[e1, e2])

        with patch("s1_orchestrator.event_handler.get_session", return_value=session), \
             patch("s1_orchestrator.event_handler.invalidate_cache"):
            handler = EventHandler(
                on_mode_changed=lambda m, a: None,
                on_config_changed=lambda: None,
            )
            handler._poll()

        assert handler._watermark == t2


class TestUserHaltHandling:
    def test_user_halt_calls_on_user_halt_callback(self):
        halted = []

        event = MagicMock()
        event.event_type = "USER_HALT"
        event.timestamp = datetime.now(tz=timezone.utc)
        session = make_session(events=[event])

        with patch("s1_orchestrator.event_handler.get_session", return_value=session):
            handler = EventHandler(
                on_mode_changed=lambda m, a: None,
                on_config_changed=lambda: None,
                on_user_halt=lambda reason: halted.append(reason),
                poll_interval_seconds=999,
            )
            handler._poll()

        assert len(halted) == 1
        assert "halt" in halted[0].lower() or "operator" in halted[0].lower()

    def test_user_halt_with_no_callback_does_not_raise(self):
        event = MagicMock()
        event.event_type = "USER_HALT"
        event.timestamp = datetime.now(tz=timezone.utc)
        session = make_session(events=[event])

        with patch("s1_orchestrator.event_handler.get_session", return_value=session):
            handler = EventHandler(
                on_mode_changed=lambda m, a: None,
                on_config_changed=lambda: None,
                on_user_halt=None,
                poll_interval_seconds=999,
            )
            handler._poll()  # must not raise


class TestUserResumeHandling:
    def test_user_resume_calls_on_user_resume_callback(self):
        resumed = []

        event = MagicMock()
        event.event_type = "USER_RESUME"
        event.timestamp = datetime.now(tz=timezone.utc)
        session = make_session(events=[event])

        with patch("s1_orchestrator.event_handler.get_session", return_value=session):
            handler = EventHandler(
                on_mode_changed=lambda m, a: None,
                on_config_changed=lambda: None,
                on_user_resume=lambda: resumed.append(True),
                poll_interval_seconds=999,
            )
            handler._poll()

        assert resumed == [True]

    def test_user_resume_with_no_callback_does_not_raise(self):
        event = MagicMock()
        event.event_type = "USER_RESUME"
        event.timestamp = datetime.now(tz=timezone.utc)
        session = make_session(events=[event])

        with patch("s1_orchestrator.event_handler.get_session", return_value=session):
            handler = EventHandler(
                on_mode_changed=lambda m, a: None,
                on_config_changed=lambda: None,
                on_user_resume=None,
                poll_interval_seconds=999,
            )
            handler._poll()  # must not raise

    def test_watermark_advances_for_halt_and_resume_events(self):
        t1 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 1, 1, 10, 5, 0, tzinfo=timezone.utc)

        e1 = MagicMock()
        e1.event_type = "USER_HALT"
        e1.timestamp = t1

        e2 = MagicMock()
        e2.event_type = "USER_RESUME"
        e2.timestamp = t2

        session = make_session(events=[e1, e2])

        with patch("s1_orchestrator.event_handler.get_session", return_value=session):
            handler = EventHandler(
                on_mode_changed=lambda m, a: None,
                on_config_changed=lambda: None,
                on_user_halt=lambda r: None,
                on_user_resume=lambda: None,
            )
            handler._poll()

        assert handler._watermark == t2


class TestAllFourEventsInOnePoll:
    def test_all_four_event_types_dispatched_in_order(self):
        sequence = []

        events = []
        for et, ts in [
            ("CONFIG_CHANGED", datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)),
            ("USER_HALT",      datetime(2026, 1, 1, 10, 1, tzinfo=timezone.utc)),
            ("USER_RESUME",    datetime(2026, 1, 1, 10, 2, tzinfo=timezone.utc)),
            ("MODE_CHANGED",   datetime(2026, 1, 1, 10, 3, tzinfo=timezone.utc)),
        ]:
            e = MagicMock()
            e.event_type = et
            e.timestamp = ts
            events.append(e)

        session = make_session(events=events)

        mock_cfg = MagicMock()
        mock_cfg.system.mode = "PAPER"
        mock_cfg.system.approval_mode = "HARD"

        with patch("s1_orchestrator.event_handler.get_session", return_value=session), \
             patch("s1_orchestrator.event_handler.get_config", return_value=mock_cfg), \
             patch("s1_orchestrator.event_handler.invalidate_cache"):
            handler = EventHandler(
                on_mode_changed=lambda m, a: sequence.append("mode"),
                on_config_changed=lambda: sequence.append("config"),
                on_user_halt=lambda r: sequence.append("halt"),
                on_user_resume=lambda: sequence.append("resume"),
            )
            handler._poll()

        assert sequence == ["config", "halt", "resume", "mode"]


class TestLifecycle:
    def test_start_stop(self):
        session = make_session(events=[])
        with patch("s1_orchestrator.event_handler.get_session", return_value=session):
            handler = EventHandler(
                on_mode_changed=lambda m, a: None,
                on_config_changed=lambda: None,
                poll_interval_seconds=999,
            )
            handler.start()
            assert handler._thread.is_alive()
            handler.stop()
            assert not handler._thread.is_alive()
