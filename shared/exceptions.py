"""
shared/exceptions.py

Typed exceptions for every failure domain in AlgoTrader.
All subsystems must raise one of these; never raise bare Exception.
Catching code can then target specific failure domains without
parsing message strings.
"""


class AlgoTraderError(Exception):
    """Base class for all AlgoTrader exceptions."""


class ConfigError(AlgoTraderError):
    """Raised when a config file is missing, unparseable, or fails validation."""


class DataError(AlgoTraderError):
    """Raised on database connection failure or data integrity violations."""


class SignalError(AlgoTraderError):
    """Raised when signal generation fails or produces invalid output."""


class RiskBreach(AlgoTraderError):
    """Raised when a pre-flight risk guard is violated. Must trigger RISK_HALT."""


class ExecutionError(AlgoTraderError):
    """Raised when order submission or fill tracking encounters an unrecoverable error."""


class SentimentError(AlgoTraderError):
    """Raised when the sentiment engine fails and no fallback is available."""


class BacktestError(AlgoTraderError):
    """Raised when a backtest run cannot complete (e.g. insufficient history)."""
