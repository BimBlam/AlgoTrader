"""
shared/constants.py

All system-wide enumerations. Import from here; never define enums elsewhere.
String values match the TEXT columns stored in PostgreSQL exactly so comparisons
are a simple equality check with no transformation.
"""
from enum import StrEnum


class SystemMode(StrEnum):
    DISABLED = "DISABLED"
    PAPER    = "PAPER"
    LIVE     = "LIVE"
    BOTH     = "BOTH"


class ApprovalMode(StrEnum):
    HARD = "HARD"
    SOFT = "SOFT"


class SystemState(StrEnum):
    DISABLED           = "DISABLED"
    STARTING           = "STARTING"
    IDLE               = "IDLE"
    INGESTING          = "INGESTING"
    PROCESSING         = "PROCESSING"
    PENDING_APPROVAL   = "PENDING_APPROVAL"
    APPROVED           = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    EXECUTING          = "EXECUTING"
    MONITORING         = "MONITORING"
    RECONCILING        = "RECONCILING"
    HALT               = "HALT"


class SignalStrategy(StrEnum):
    STAT_ARB     = "STAT_ARB"
    REVERSAL     = "REVERSAL"
    REGIME_COMBO = "REGIME_COMBO"


class SignalSide(StrEnum):
    LONG  = "LONG"
    SHORT = "SHORT"


class OrderType(StrEnum):
    LIMIT  = "LIMIT"
    MARKET = "MARKET"


class OrderStatus(StrEnum):
    PENDING   = "PENDING"
    SUBMITTED = "SUBMITTED"
    FILLED    = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED  = "REJECTED"


class PositionStatus(StrEnum):
    OPEN   = "OPEN"
    CLOSED = "CLOSED"


class JobStatus(StrEnum):
    PENDING          = "PENDING"
    RUNNING          = "RUNNING"
    DONE             = "DONE"
    FAILED           = "FAILED"
    RETRYABLE_FAILED = "RETRYABLE_FAILED"


class SignalStatus(StrEnum):
    PENDING  = "PENDING"
    APPROVED = "APPROVED"
    DENIED   = "DENIED"
    EXECUTED = "EXECUTED"
    EXPIRED  = "EXPIRED"


class Severity(StrEnum):
    INFO     = "INFO"
    WARNING  = "WARNING"
    ERROR    = "ERROR"
    CRITICAL = "CRITICAL"


class EventType(StrEnum):
    STARTUP          = "STARTUP"
    SHUTDOWN         = "SHUTDOWN"
    JOB_STARTED      = "JOB_STARTED"
    JOB_COMPLETED    = "JOB_COMPLETED"
    JOB_FAILED       = "JOB_FAILED"
    JOB_RETRYING     = "JOB_RETRYING"
    DATA_READY       = "DATA_READY"
    DATA_ERROR       = "DATA_ERROR"
    DATA_STALE       = "DATA_STALE"
    SENTIMENT_READY  = "SENTIMENT_READY"
    SENTIMENT_ERROR  = "SENTIMENT_ERROR"
    SIGNALS_READY    = "SIGNALS_READY"
    SIGNAL_FILTERED  = "SIGNAL_FILTERED"
    BACKTEST_RESULT  = "BACKTEST_RESULT"
    BACKTEST_FAILED  = "BACKTEST_FAILED"
    APPROVAL_GRANTED = "APPROVAL_GRANTED"
    APPROVAL_DENIED  = "APPROVAL_DENIED"
    ORDER_SUBMITTED  = "ORDER_SUBMITTED"
    ORDER_FILLED     = "ORDER_FILLED"
    ORDER_REJECTED   = "ORDER_REJECTED"
    POSITION_OPENED  = "POSITION_OPENED"
    POSITION_CLOSED  = "POSITION_CLOSED"
    RISK_BREACH      = "RISK_BREACH"
    RISK_HALT        = "RISK_HALT"
    USER_HALT        = "USER_HALT"
    USER_RESUME      = "USER_RESUME"
    CONFIG_CHANGED   = "CONFIG_CHANGED"
    MODE_CHANGED     = "MODE_CHANGED"
