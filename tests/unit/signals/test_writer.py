"""
Unit tests for writer.py — DB persistence helpers.
"""
import datetime
from unittest.mock import MagicMock

from algotrader.shared.constants import EventType, Severity, SignalSide, SignalStrategy
from algotrader.signals.stat_arb import SignalCandidate
from algotrader.signals.writer import write_event, write_signals

TODAY = datetime.date(2025, 1, 15)
RUN_ID = "test-run-004"


def _make_candidate(ticker="AAPL", strategy=SignalStrategy.STAT_ARB, side=SignalSide.LONG):
    return SignalCandidate(
        ticker=ticker,
        strategy=strategy,
        side=side,
        raw_score=1.5,
        sentiment_adj=1.0,
        regime="LOW_VOL",
        run_id=RUN_ID,
        date=TODAY,
    )


class TestWriteSignals:
    def test_adds_one_signal_per_candidate(self):
        session = MagicMock()
        candidates = [_make_candidate("AAPL"), _make_candidate("MSFT")]
        write_signals(session, candidates)
        assert session.add.call_count == 2

    def test_ticker_uppercased(self):
        session = MagicMock()
        candidates = [_make_candidate("aapl")]
        write_signals(session, candidates)
        added = session.add.call_args[0][0]
        assert added.ticker == "AAPL"

    def test_status_is_pending(self):
        session = MagicMock()
        write_signals(session, [_make_candidate()])
        added = session.add.call_args[0][0]
        assert added.status == "PENDING"

    def test_target_size_usd_is_zero_placeholder(self):
        session = MagicMock()
        write_signals(session, [_make_candidate()])
        added = session.add.call_args[0][0]
        assert added.target_size_usd == 0.0

    def test_no_write_on_empty_list(self):
        session = MagicMock()
        write_signals(session, [])
        session.add.assert_not_called()

    def test_run_id_persisted(self):
        session = MagicMock()
        write_signals(session, [_make_candidate()])
        added = session.add.call_args[0][0]
        assert added.run_id == RUN_ID


class TestWriteEvent:
    def test_adds_system_event(self):
        session = MagicMock()
        write_event(session, RUN_ID, EventType.SIGNALS_READY, Severity.INFO, "done")
        session.add.assert_called_once()

    def test_subsystem_is_s3(self):
        session = MagicMock()
        write_event(session, RUN_ID, EventType.SIGNALS_READY, Severity.INFO, "done")
        added = session.add.call_args[0][0]
        assert added.subsystem == "S3"

    def test_payload_defaults_to_empty_dict(self):
        session = MagicMock()
        write_event(session, RUN_ID, EventType.SIGNALS_READY, Severity.INFO, "done")
        added = session.add.call_args[0][0]
        assert added.payload == {}

    def test_payload_stored_when_provided(self):
        session = MagicMock()
        payload = {"date": "2025-01-15", "n_signals": 5}
        write_event(session, RUN_ID, EventType.SIGNALS_READY, Severity.INFO, "done", payload=payload)
        added = session.add.call_args[0][0]
        assert added.payload == payload
