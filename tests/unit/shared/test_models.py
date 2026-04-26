"""Unit tests for shared/models.py — schema correctness without a live DB."""
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from algotrader.shared.models import (
    Base,
    Job,
    OUParam,
    Signal,
    SystemEvent,
)


@pytest.fixture(scope="module")
def sqlite_session():
    """In-memory SQLite engine — patches JSONB → JSON for dialect compatibility."""
    from sqlalchemy import JSON
    from sqlalchemy.dialects.postgresql import JSONB

    # Remap JSONB to JSON before DDL runs; JSONB is Postgres-only
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, JSONB):
                col.type = JSON()

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()

def _utc_now():
    return datetime.now(UTC)


def test_all_tables_created(sqlite_session):
    inspector = inspect(sqlite_session.bind)
    tables = set(inspector.get_table_names())
    expected = {
        "jobs", "signals", "orders", "positions",
        "ou_params", "sentiment_scores", "backtest_runs", "system_events",
    }
    assert expected.issubset(tables)


def test_job_roundtrip(sqlite_session):
    run_id = uuid.uuid4()
    job = Job(
        run_id=run_id,
        job_type="INGEST_EOD",
        status="PENDING",
        created_at=_utc_now(),
        retry_count=0,
    )
    sqlite_session.add(job)
    sqlite_session.flush()
    fetched = sqlite_session.query(Job).filter_by(run_id=run_id).one()
    assert fetched.job_type == "INGEST_EOD"
    assert fetched.status == "PENDING"


def test_signal_foreign_key(sqlite_session):
    run_id = uuid.uuid4()
    job = Job(run_id=run_id, job_type="RUN_SIGNALS",
              status="DONE", created_at=_utc_now())
    sqlite_session.add(job)
    sqlite_session.flush()

    signal = Signal(
        run_id=run_id,
        created_at=_utc_now(),
        ticker="AAPL",
        strategy="STAT_ARB",
        side="LONG",
        raw_score=1.5,
        sentiment_adj=0.8,
        regime="LOW_VOL",
        target_size_usd=4500.0,
        status="PENDING",
    )
    sqlite_session.add(signal)
    sqlite_session.flush()
    assert signal.id is not None


def test_system_event_no_fk_constraint(sqlite_session):
    """system_events.run_id is nullable — events can exist without a job."""
    ev = SystemEvent(
        timestamp=_utc_now(),
        event_type="STARTUP",
        severity="INFO",
        subsystem="S1",
        message="System starting up.",
    )
    sqlite_session.add(ev)
    sqlite_session.flush()
    assert ev.id is not None


def test_ou_param_unique_constraint(sqlite_session):
    """Duplicate (date, ticker) must raise IntegrityError."""
    import datetime

    from sqlalchemy.exc import IntegrityError

    run_id = uuid.uuid4()
    job = Job(run_id=run_id, job_type="RUN_SIGNALS",
              status="DONE", created_at=_utc_now())
    sqlite_session.add(job)
    sqlite_session.flush()

    today = datetime.date(2025, 1, 15)
    for _ in range(2):
        sqlite_session.add(OUParam(
            run_id=run_id, date=today, ticker="MSFT",
            kappa=10.0, mu=0.0, sigma_eq=0.02, beta=1.0, valid=True,
        ))
    with pytest.raises(IntegrityError):
        sqlite_session.flush()
    sqlite_session.rollback()
