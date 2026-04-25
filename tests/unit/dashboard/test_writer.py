"""tests/unit/s7/test_writer.py"""
from __future__ import annotations


import pytest

from algotrader.shared.constants import EventType, Severity, SignalStatus
from algotrader.shared.exceptions import DataError
from algotrader.shared.models import SystemEvent
from algotrader.dashboard.writer import (
    approve_signal,
    deny_signal,
    write_config_changed_event,
    write_event,
    write_halt_event,
    write_mode_changed_event,
    write_resume_event,
)


# ── write_event ───────────────────────────────────────────────────────────────

class TestWriteEvent:
    def test_creates_event_with_correct_fields(self, mock_session):
        event = write_event(
            mock_session,
            event_type=EventType.USER_HALT,
            severity=Severity.WARNING,
            message="halted",
            run_id="run-1",
            payload={"source": "test"},
        )
        assert event.event_type == "USER_HALT"
        assert event.severity == "WARNING"
        assert event.subsystem == "S7"
        assert event.message == "halted"
        assert event.run_id == "run-1"
        assert event.payload == {"source": "test"}
        mock_session.add.assert_called_once_with(event)
        mock_session.flush.assert_called_once()

    def test_defaults_payload_to_empty_dict(self, mock_session):
        event = write_event(
            mock_session,
            event_type=EventType.USER_RESUME,
            severity=Severity.INFO,
            message="resumed",
        )
        assert event.payload == {}

    def test_subsystem_is_always_s7(self, mock_session):
        event = write_event(
            mock_session,
            event_type=EventType.CONFIG_CHANGED,
            severity=Severity.WARNING,
            message="config",
        )
        assert event.subsystem == "S7"


# ── approve_signal ────────────────────────────────────────────────────────────

class TestApproveSignal:
    def test_approves_pending_signal(self, mock_session, pending_signal):
        mock_session.get.return_value = pending_signal
        result = approve_signal(mock_session, 1)
        assert result.status == SignalStatus.APPROVED.value
        assert result.approved_by == "USER"
        assert result.approved_at is not None

    def test_sets_notes_when_provided(self, mock_session, pending_signal):
        mock_session.get.return_value = pending_signal
        result = approve_signal(mock_session, 1, notes="Looks good")
        assert result.notes == "Looks good"

    def test_writes_approval_granted_event(self, mock_session, pending_signal):
        mock_session.get.return_value = pending_signal
        approve_signal(mock_session, 1)
        # add called twice: once for signal update (implicit), once for event
        added_objects = [call.args[0] for call in mock_session.add.call_args_list]
        event_objects = [o for o in added_objects if isinstance(o, SystemEvent)]
        assert len(event_objects) == 1
        assert event_objects[0].event_type == EventType.APPROVAL_GRANTED.value

    def test_raises_when_signal_not_found(self, mock_session):
        mock_session.get.return_value = None
        with pytest.raises(DataError, match="not found"):
            approve_signal(mock_session, 999)

    def test_raises_when_signal_not_pending(self, mock_session, approved_signal):
        mock_session.get.return_value = approved_signal
        with pytest.raises(DataError, match="cannot be approved"):
            approve_signal(mock_session, 2)

    def test_does_not_set_notes_when_none(self, mock_session, pending_signal):
        original_notes = pending_signal.notes
        mock_session.get.return_value = pending_signal
        approve_signal(mock_session, 1, notes=None)
        assert pending_signal.notes == original_notes  # unchanged


# ── deny_signal ───────────────────────────────────────────────────────────────

class TestDenySignal:
    def test_denies_pending_signal(self, mock_session, pending_signal):
        mock_session.get.return_value = pending_signal
        result = deny_signal(mock_session, 1)
        assert result.status == SignalStatus.DENIED.value

    def test_sets_notes_when_provided(self, mock_session, pending_signal):
        mock_session.get.return_value = pending_signal
        deny_signal(mock_session, 1, notes="Too risky")
        assert pending_signal.notes == "Too risky"

    def test_writes_approval_denied_event(self, mock_session, pending_signal):
        mock_session.get.return_value = pending_signal
        deny_signal(mock_session, 1)
        added_objects = [call.args[0] for call in mock_session.add.call_args_list]
        events = [o for o in added_objects if isinstance(o, SystemEvent)]
        assert len(events) == 1
        assert events[0].event_type == EventType.APPROVAL_DENIED.value

    def test_raises_when_signal_not_found(self, mock_session):
        mock_session.get.return_value = None
        with pytest.raises(DataError, match="not found"):
            deny_signal(mock_session, 999)

    def test_raises_when_signal_already_denied(self, mock_session, pending_signal):
        pending_signal.status = "DENIED"
        mock_session.get.return_value = pending_signal
        with pytest.raises(DataError, match="cannot be denied"):
            deny_signal(mock_session, 1)

    def test_raises_when_signal_executed(self, mock_session, pending_signal):
        pending_signal.status = "EXECUTED"
        mock_session.get.return_value = pending_signal
        with pytest.raises(DataError, match="cannot be denied"):
            deny_signal(mock_session, 1)


# ── write_halt_event ──────────────────────────────────────────────────────────

class TestWriteHaltEvent:
    def test_writes_user_halt_warning(self, mock_session):
        event = write_halt_event(mock_session)
        assert event.event_type == EventType.USER_HALT.value
        assert event.severity == Severity.WARNING.value
        assert event.subsystem == "S7"

    def test_message_contains_halt(self, mock_session):
        event = write_halt_event(mock_session)
        assert "halt" in event.message.lower()


# ── write_resume_event ────────────────────────────────────────────────────────

class TestWriteResumeEvent:
    def test_writes_user_resume_info(self, mock_session):
        event = write_resume_event(mock_session)
        assert event.event_type == EventType.USER_RESUME.value
        assert event.severity == Severity.INFO.value
        assert event.subsystem == "S7"


# ── write_config_changed_event ────────────────────────────────────────────────

class TestWriteConfigChangedEvent:
    def test_writes_config_changed_warning(self, mock_session):
        event = write_config_changed_event(mock_session, {"param": "x"})
        assert event.event_type == EventType.CONFIG_CHANGED.value
        assert event.severity == Severity.WARNING.value

    def test_carries_payload(self, mock_session):
        event = write_config_changed_event(mock_session, {"source": "calibration"})
        assert event.payload == {"source": "calibration"}

    def test_defaults_empty_payload(self, mock_session):
        event = write_config_changed_event(mock_session)
        assert event.payload == {}


# ── write_mode_changed_event ──────────────────────────────────────────────────

class TestWriteModeChangedEvent:
    def test_writes_mode_changed_warning(self, mock_session):
        event = write_mode_changed_event(mock_session, "LIVE", "HARD")
        assert event.event_type == EventType.MODE_CHANGED.value
        assert event.severity == Severity.WARNING.value

    def test_payload_contains_new_mode(self, mock_session):
        event = write_mode_changed_event(mock_session, "BOTH", "SOFT")
        assert event.payload["new_mode"] == "BOTH"
        assert event.payload["new_approval_mode"] == "SOFT"

    def test_message_contains_mode(self, mock_session):
        event = write_mode_changed_event(mock_session, "PAPER", "HARD")
        assert "PAPER" in event.message
