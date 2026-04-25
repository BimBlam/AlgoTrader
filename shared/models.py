"""
shared/models.py

SQLAlchemy 2.0 ORM definitions for every canonical table in Section 4.2.
Column types, constraints, and names are authoritative; do not alter them
in subsystem code.

All timestamp columns use DateTime(timezone=True) so PostgreSQL stores
TIMESTAMPTZ and Python receives timezone-aware datetime objects. Callers
must always pass UTC-aware datetimes — enforcement happens at the DB layer.
"""
import uuid

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, ForeignKey,
    Integer, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


class Job(Base):
    """Tracks every unit of work dispatched by the orchestrator (S1)."""

    __tablename__ = "jobs"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    run_id       = Column(UUID(as_uuid=True), nullable=False, unique=True, default=uuid.uuid4)
    job_type     = Column(Text, nullable=False)
    status       = Column(Text, nullable=False)
    created_at   = Column(DateTime(timezone=True), nullable=False)
    started_at   = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    worker_pid   = Column(Integer)
    error_msg    = Column(Text)
    retry_count  = Column(Integer, default=0)
    config_hash  = Column(Text)

    signals      = relationship("Signal",         back_populates="job", cascade="all, delete-orphan")
    ou_params    = relationship("OUParam",         back_populates="job", cascade="all, delete-orphan")
    sentiments   = relationship("SentimentScore",  back_populates="job", cascade="all, delete-orphan")
    backtest_run = relationship("BacktestRun",     back_populates="job", uselist=False)


class Signal(Base):
    """A trading signal produced by S3 and approved/denied by S7 or S1."""

    __tablename__ = "signals"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    run_id          = Column(UUID(as_uuid=True), ForeignKey("jobs.run_id"), nullable=False)
    created_at      = Column(DateTime(timezone=True), nullable=False)
    ticker          = Column(Text, nullable=False)
    strategy        = Column(Text, nullable=False)
    side            = Column(Text, nullable=False)
    raw_score       = Column(Float, nullable=False)
    sentiment_adj   = Column(Float, nullable=False)
    regime          = Column(Text, nullable=False)
    target_size_usd = Column(Float, nullable=False)
    status          = Column(Text, nullable=False)
    approved_by     = Column(Text)
    approved_at     = Column(DateTime(timezone=True))
    notes           = Column(Text)

    job    = relationship("Job",   back_populates="signals")
    orders = relationship("Order", back_populates="signal", cascade="all, delete-orphan")


class Order(Base):
    """A limit order submitted to IBKR by S6."""

    __tablename__ = "orders"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    signal_id     = Column(Integer, ForeignKey("signals.id"), nullable=False)
    ibkr_order_id = Column(Text)
    ticker        = Column(Text, nullable=False)
    side          = Column(Text, nullable=False)
    order_type    = Column(Text, nullable=False)
    quantity      = Column(Integer, nullable=False)
    limit_price   = Column(Float, nullable=False)
    submitted_at  = Column(DateTime(timezone=True))
    filled_at     = Column(DateTime(timezone=True))
    fill_price    = Column(Float)
    status        = Column(Text, nullable=False)
    account_type  = Column(Text, nullable=False)

    signal    = relationship("Signal",   back_populates="orders")
    positions = relationship("Position", back_populates="order", cascade="all, delete-orphan")


class Position(Base):
    """An open or closed equity position managed by S6."""

    __tablename__ = "positions"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    ticker       = Column(Text, nullable=False)
    side         = Column(Text, nullable=False)
    entry_price  = Column(Float, nullable=False)
    quantity     = Column(Integer, nullable=False)
    entry_time   = Column(DateTime(timezone=True), nullable=False)
    exit_price   = Column(Float)
    exit_time    = Column(DateTime(timezone=True))
    realised_pnl = Column(Float)
    status       = Column(Text, nullable=False)
    order_id     = Column(Integer, ForeignKey("orders.id"))
    account_type = Column(Text, nullable=False)

    order = relationship("Order", back_populates="positions")


class OUParam(Base):
    """
    Ornstein-Uhlenbeck parameters per ticker per day, fit by S3.
    A row with valid=False is retained so the signal engine can log *why*
    a ticker was skipped rather than treating it as missing data.
    """

    __tablename__  = "ou_params"
    __table_args__ = (UniqueConstraint("date", "ticker", name="uq_ou_date_ticker"),)

    id       = Column(Integer, primary_key=True, autoincrement=True)
    run_id   = Column(UUID(as_uuid=True), ForeignKey("jobs.run_id"), nullable=False)
    date     = Column(Date, nullable=False)
    ticker   = Column(Text, nullable=False)
    kappa    = Column(Float, nullable=False)
    mu       = Column(Float, nullable=False)
    sigma_eq = Column(Float, nullable=False)
    beta     = Column(Float, nullable=False)
    valid    = Column(Boolean, nullable=False)

    job = relationship("Job", back_populates="ou_params")


class SentimentScore(Base):
    """
    Per-ticker daily sentiment scored by S5.
    A row is always written for every universe ticker — even when no data
    is available (sentiment_res=0.0, model_used='none').
    """

    __tablename__  = "sentiment_scores"
    __table_args__ = (UniqueConstraint("date", "ticker", name="uq_sentiment_date_ticker"),)

    id            = Column(Integer, primary_key=True, autoincrement=True)
    run_id        = Column(UUID(as_uuid=True), ForeignKey("jobs.run_id"), nullable=False)
    date          = Column(Date, nullable=False)
    ticker        = Column(Text, nullable=False)
    raw_mentions  = Column(Integer, nullable=False)
    abn_attention = Column(Float, nullable=False)
    raw_sentiment = Column(Float, nullable=False)
    sentiment_res = Column(Float, nullable=False)
    model_used    = Column(Text, nullable=False)

    job = relationship("Job", back_populates="sentiments")


class BacktestRun(Base):
    """Metadata and aggregate metrics for a single backtest execution by S4."""

    __tablename__ = "backtest_runs"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    run_id           = Column(UUID(as_uuid=True), ForeignKey("jobs.run_id"), nullable=False, unique=True)
    created_at       = Column(DateTime(timezone=True), nullable=False)
    date_range_start = Column(Date, nullable=False)
    date_range_end   = Column(Date, nullable=False)
    strategy         = Column(Text, nullable=False)
    universe_hash    = Column(Text, nullable=False)
    config_hash      = Column(Text, nullable=False)
    code_version     = Column(Text, nullable=False)
    n_mc_paths       = Column(Integer, nullable=False)
    include_costs    = Column(Boolean, nullable=False)
    sharpe           = Column(Float)
    sortino          = Column(Float)
    max_drawdown     = Column(Float)
    pbo              = Column(Float)
    deflated_sharpe  = Column(Float)
    result_path      = Column(Text)

    job = relationship("Job", back_populates="backtest_run")


class SystemEvent(Base):
    """
    Immutable audit log written by every subsystem.
    The model lives in shared/ so all modules share the same schema;
    actual writes are performed by each subsystem, not by shared/ itself.
    """

    __tablename__ = "system_events"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    timestamp  = Column(DateTime(timezone=True), nullable=False)
    event_type = Column(Text, nullable=False)
    severity   = Column(Text, nullable=False)
    subsystem  = Column(Text, nullable=False)
    run_id     = Column(UUID(as_uuid=True))
    message    = Column(Text, nullable=False)
    payload    = Column(JSONB)
