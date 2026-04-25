"""
tests/unit/s4/test_writer.py

Tests for DB writer functions using mocked sessions.
Updated to match the new explicit-parameter signature of write_backtest_record.
"""

import datetime
import uuid
from unittest.mock import MagicMock

import pytest
from algotrader.backtest.writer import write_backtest_record, write_event
from algotrader.shared.constants import EventType, Severity


@pytest.fixture
def session():
    s = MagicMock()
    s.add = MagicMock()
    s.flush = MagicMock()
    return s


def _default_kwargs(run_id):
    return dict(
        session=MagicMock(add=MagicMock(), flush=MagicMock()),
        run_id=run_id,
        strategy="REVERSAL",
        config_hash="abc123def456",
        universe_hash="deadbeef",
        code_version="a1b2c3d",
        date_range_start=datetime.date(2022, 1, 1),
        date_range_end=datetime.date(2023, 1, 1),
        n_mc_paths=1000,
        include_costs=True,
        sharpe=1.2,
        sortino=1.5,
        max_drawdown=-0.15,
        pbo=0.3,
        deflated_sharpe=0.85,
        result_path="/mnt/hdd/backtest/abc",
    )


def test_write_backtest_record_adds_to_session():
    run_id = str(uuid.uuid4())
    kw = _default_kwargs(run_id)
    session = kw["session"]
    write_backtest_record(**kw)
    session.add.assert_called_once()
    session.flush.assert_called_once()


def test_write_backtest_record_strategy_stored():
    """The explicit strategy value is stored, not derived from cfg."""
    run_id = str(uuid.uuid4())
    kw = _default_kwargs(run_id)
    kw["strategy"] = "STATARB"
    session = kw["session"]
    write_backtest_record(**kw)
    added = session.add.call_args[0][0]
    assert added.strategy == "STATARB"


def test_write_backtest_record_config_hash_stored():
    """config_hash comes from the caller, not from live cfg."""
    run_id = str(uuid.uuid4())
    kw = _default_kwargs(run_id)
    kw["config_hash"] = "job_creation_hash"
    session = kw["session"]
    write_backtest_record(**kw)
    added = session.add.call_args[0][0]
    assert added.config_hash == "job_creation_hash"


def test_write_event_backtest_result(session):
    run_id = str(uuid.uuid4())
    write_event(session, EventType.BACKTEST_RESULT, Severity.INFO,
                "S4", run_id, "done", {"sharpe": 1.2})
    session.add.assert_called_once()


def test_write_event_null_run_id(session):
    write_event(session, EventType.BACKTEST_FAILED, Severity.ERROR,
                "S4", None, "No run ID")
    session.add.assert_called_once()
    added = session.add.call_args[0][0]
    assert added.run_id is None