"""Tests for algotrader.orchestrator.state_machine."""
from __future__ import annotations

import pytest

from algotrader.orchestrator.state_machine import StateMachine
from algotrader.shared.constants import SystemState
from algotrader.shared.exceptions import ConfigError


class TestStateMachineTransitions:
    """Verify that legal and illegal transitions behave correctly."""

    def test_initial_state_is_disabled(self):
        sm = StateMachine()
        assert sm.state == SystemState.DISABLED

    def test_disabled_to_starting(self):
        sm = StateMachine()
        sm.transition(SystemState.STARTING, reason="test")
        assert sm.state == SystemState.STARTING

    def test_starting_to_idle(self):
        sm = StateMachine(SystemState.STARTING)
        sm.transition(SystemState.IDLE, reason="test")
        assert sm.state == SystemState.IDLE

    def test_idle_to_ingesting(self):
        sm = StateMachine(SystemState.IDLE)
        sm.transition(SystemState.INGESTING, reason="test")
        assert sm.state == SystemState.INGESTING

    def test_idle_to_processing(self):
        sm = StateMachine(SystemState.IDLE)
        sm.transition(SystemState.PROCESSING, reason="test")
        assert sm.state == SystemState.PROCESSING

    def test_processing_to_pending_approval(self):
        sm = StateMachine(SystemState.PROCESSING)
        sm.transition(SystemState.PENDING_APPROVAL, reason="test")
        assert sm.state == SystemState.PENDING_APPROVAL

    def test_pending_approval_to_approved(self):
        sm = StateMachine(SystemState.PENDING_APPROVAL)
        sm.transition(SystemState.APPROVED, reason="test")
        assert sm.state == SystemState.APPROVED

    def test_approved_to_executing(self):
        sm = StateMachine(SystemState.APPROVED)
        sm.transition(SystemState.EXECUTING, reason="test")
        assert sm.state == SystemState.EXECUTING

    def test_executing_to_monitoring(self):
        sm = StateMachine(SystemState.EXECUTING)
        sm.transition(SystemState.MONITORING, reason="test")
        assert sm.state == SystemState.MONITORING

    def test_monitoring_to_reconciling(self):
        sm = StateMachine(SystemState.MONITORING)
        sm.transition(SystemState.RECONCILING, reason="test")
        assert sm.state == SystemState.RECONCILING

    def test_reconciling_to_idle(self):
        sm = StateMachine(SystemState.RECONCILING)
        sm.transition(SystemState.IDLE, reason="test")
        assert sm.state == SystemState.IDLE

    def test_halt_to_idle_only(self):
        sm = StateMachine(SystemState.HALT)
        sm.transition(SystemState.IDLE, reason="RESUME")
        assert sm.state == SystemState.IDLE

    def test_any_state_to_halt(self):
        for state in [
            SystemState.IDLE,
            SystemState.INGESTING,
            SystemState.PROCESSING,
            SystemState.PENDING_APPROVAL,
            SystemState.EXECUTING,
            SystemState.MONITORING,
            SystemState.RECONCILING,
        ]:
            sm = StateMachine(state)
            sm.transition(SystemState.HALT, reason="test halt")
            assert sm.state == SystemState.HALT


class TestIllegalTransitions:
    """Illegal transitions must raise ConfigError (fail-closed)."""

    def test_disabled_to_idle_raises(self):
        sm = StateMachine(SystemState.DISABLED)
        with pytest.raises(ConfigError):
            sm.transition(SystemState.IDLE)

    def test_idle_to_approved_raises(self):
        sm = StateMachine(SystemState.IDLE)
        with pytest.raises(ConfigError):
            sm.transition(SystemState.APPROVED)

    def test_halt_to_executing_raises(self):
        sm = StateMachine(SystemState.HALT)
        with pytest.raises(ConfigError):
            sm.transition(SystemState.EXECUTING)

    def test_reconciling_to_executing_raises(self):
        sm = StateMachine(SystemState.RECONCILING)
        with pytest.raises(ConfigError):
            sm.transition(SystemState.EXECUTING)


class TestForceHalt:
    """force_halt must always succeed regardless of current state."""

    def test_force_halt_from_idle(self):
        sm = StateMachine(SystemState.IDLE)
        sm.force_halt("test")
        assert sm.state == SystemState.HALT

    def test_force_halt_from_disabled(self):
        sm = StateMachine(SystemState.DISABLED)
        sm.force_halt("test")
        assert sm.state == SystemState.HALT

    def test_force_halt_from_halt_is_idempotent(self):
        sm = StateMachine(SystemState.HALT)
        sm.force_halt("test")
        assert sm.state == SystemState.HALT


class TestHelpers:
    def test_is_halted(self):
        sm = StateMachine(SystemState.HALT)
        assert sm.is_halted()

    def test_is_not_halted(self):
        sm = StateMachine(SystemState.IDLE)
        assert not sm.is_halted()

    def test_is_operational_idle(self):
        sm = StateMachine(SystemState.IDLE)
        assert sm.is_operational()

    def test_is_operational_disabled(self):
        sm = StateMachine(SystemState.DISABLED)
        assert not sm.is_operational()

    def test_is_operational_halt(self):
        sm = StateMachine(SystemState.HALT)
        assert not sm.is_operational()
