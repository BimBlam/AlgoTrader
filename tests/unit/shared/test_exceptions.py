"""Unit tests for shared/exceptions.py."""
import pytest

from algotrader.shared.exceptions import (
    AlgoTraderError, BacktestError, ConfigError, DataError,
    ExecutionError, RiskBreach, SentimentError, SignalError,
)


def test_all_exceptions_inherit_base():
    for cls in (
        ConfigError, DataError, SignalError, RiskBreach,
        ExecutionError, SentimentError, BacktestError,
    ):
        assert issubclass(cls, AlgoTraderError)
        assert issubclass(cls, Exception)


def test_exceptions_carry_message():
    exc = RiskBreach("daily loss limit breached")
    assert "daily loss limit" in str(exc)


def test_exceptions_are_catchable_by_base():
    with pytest.raises(AlgoTraderError):
        raise ConfigError("missing file")


def test_exceptions_are_catchable_by_specific_type():
    with pytest.raises(RiskBreach):
        raise RiskBreach("position too large")


def test_data_error_is_not_config_error():
    """DataError must not be catchable as ConfigError."""
    with pytest.raises(DataError):
        raise DataError("db down")

    # Confirm the exception hierarchy is strictly separated
    assert not issubclass(DataError, ConfigError)
    assert not issubclass(ConfigError, DataError)

