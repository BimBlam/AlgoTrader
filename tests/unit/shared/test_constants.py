"""Unit tests for shared/constants.py."""
from algotrader.shared.constants import (
    ApprovalMode, EventType, JobStatus, OrderType,
    Severity, SignalStrategy,
    SystemMode, SystemState,
)


def test_system_mode_values():
    assert SystemMode.PAPER == "PAPER"
    assert SystemMode.LIVE  == "LIVE"
    assert set(SystemMode) == {"DISABLED", "PAPER", "LIVE", "BOTH"}


def test_approval_mode_values():
    assert ApprovalMode.HARD == "HARD"
    assert ApprovalMode.SOFT == "SOFT"


def test_system_state_contains_halt():
    assert SystemState.HALT in SystemState


def test_signal_strategy_values():
    assert SignalStrategy.STAT_ARB     == "STAT_ARB"
    assert SignalStrategy.REVERSAL     == "REVERSAL"
    assert SignalStrategy.REGIME_COMBO == "REGIME_COMBO"


def test_order_type_only_limit_and_market():
    assert set(OrderType) == {"LIMIT", "MARKET"}


def test_severity_ordering_by_name():
    # All four levels from spec must be present.
    assert {s.value for s in Severity} == {"INFO", "WARNING", "ERROR", "CRITICAL"}


def test_event_type_completeness():
    # Spot-check a few critical event types from §4.3.
    required = {
        "RISK_BREACH", "RISK_HALT", "JOB_FAILED",
        "ORDER_SUBMITTED", "POSITION_CLOSED", "CONFIG_CHANGED",
    }
    defined = {e.value for e in EventType}
    assert required.issubset(defined)


def test_enums_are_str_subclass():
    """str-enum values must compare equal to plain strings (used in DB queries)."""
    assert SystemMode.PAPER == "PAPER"
    assert JobStatus.RUNNING == "RUNNING"
