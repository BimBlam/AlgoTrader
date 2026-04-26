"""tests/unit/s6/test_writer.py"""
from __future__ import annotations

import datetime
import uuid
from unittest.mock import MagicMock

import pytest

from algotrader.execution.writer import (
    close_position,
    expire_stale_signals,
    mark_signal_executed,
    update_order_filled,
    update_order_rejected,
    update_order_submitted,
    write_event,
    write_order,
    write_position,
)
from algotrader.shared.constants import EventType, OrderStatus, PositionStatus, Severity, SignalStatus
from algotrader.shared.models import Signal


class TestWriteOrder:
    def test_long_signal_creates_buy_order(self, mock_session, sample_signal):
        sample_signal.side = "LONG"
        order = write_order(
            mock_session, sample_signal,
            quantity=10, limit_price=150.0, account_type="PAPER"
        )
        assert order.side == "BUY"
        assert order.ticker == "AAPL"
        assert order.quantity == 10
        assert order.limit_price == 150.0
        assert order.status == OrderStatus.PENDING.value
        assert order.account_type == "PAPER"
        assert order.order_type == "LIMIT"
        mock_session.add.assert_called_once_with(order)
        mock_session.flush.assert_called_once()

    def test_short_signal_creates_sell_order(self, mock_session, sample_signal):
        sample_signal.side = "SHORT"
        order = write_order(
            mock_session, sample_signal,
            quantity=5, limit_price=200.0, account_type="LIVE"
        )
        assert order.side == "SELL"
        assert order.account_type == "LIVE"


class TestUpdateOrderSubmitted:
    def test_sets_ibkr_order_id_and_status(self, sample_order):
        session = MagicMock()
        update_order_submitted(session, sample_order, "98765")
        assert sample_order.ibkr_order_id == "98765"
        assert sample_order.status == OrderStatus.SUBMITTED.value


class TestUpdateOrderFilled:
    def test_records_fill(self, sample_order):
        session = MagicMock()
        filled_at = datetime.datetime.now(tz=datetime.UTC)
        update_order_filled(session, sample_order, 149.75, filled_at)
        assert sample_order.fill_price == 149.75
        assert sample_order.filled_at == filled_at
        assert sample_order.status == OrderStatus.FILLED.value


class TestUpdateOrderRejected:
    def test_sets_rejected_status(self, sample_order):
        session = MagicMock()
        update_order_rejected(session, sample_order)
        assert sample_order.status == OrderStatus.REJECTED.value


class TestWritePosition:
    def test_creates_open_position(self, mock_session, sample_order):
        filled_at = datetime.datetime.now(tz=datetime.UTC)
        pos = write_position(mock_session, sample_order, 149.75, filled_at)
        assert pos.ticker == "AAPL"
        assert pos.side == "BUY"
        assert pos.entry_price == 149.75
        assert pos.quantity == 10
        assert pos.entry_time == filled_at
        assert pos.status == PositionStatus.OPEN.value
        assert pos.order_id == sample_order.id
        assert pos.account_type == "PAPER"
        mock_session.add.assert_called_once_with(pos)
        mock_session.flush.assert_called_once()


class TestClosePosition:
    def test_long_position_positive_pnl(self, sample_position):
        session = MagicMock()
        exit_time = datetime.datetime.now(tz=datetime.UTC)
        close_position(session, sample_position, 160.0, exit_time)
        assert sample_position.exit_price == 160.0
        assert sample_position.exit_time == exit_time
        assert sample_position.status == PositionStatus.CLOSED.value
        # P&L = (160 - 150) * 10 * 1.0 = 100
        assert sample_position.realised_pnl == pytest.approx(100.0)

    def test_long_position_negative_pnl(self, sample_position):
        session = MagicMock()
        exit_time = datetime.datetime.now(tz=datetime.UTC)
        close_position(session, sample_position, 140.0, exit_time)
        assert sample_position.realised_pnl == pytest.approx(-100.0)

    def test_short_position_pnl(self, sample_position):
        session = MagicMock()
        sample_position.side = "SELL"
        exit_time = datetime.datetime.now(tz=datetime.UTC)
        # Short: profit when price falls
        close_position(session, sample_position, 140.0, exit_time)
        # P&L = (140 - 150) * 10 * -1.0 = 100
        assert sample_position.realised_pnl == pytest.approx(100.0)


class TestMarkSignalExecuted:
    def test_updates_status(self, sample_signal):
        session = MagicMock()
        mark_signal_executed(session, sample_signal)
        assert sample_signal.status == SignalStatus.EXECUTED.value


class TestExpireStaleSignals:
    def test_expires_old_approved_signals(self, mock_session):
        yesterday = (
            datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(days=1)
        )
        old_signal = Signal(
            id=2,
            run_id=uuid.uuid4(),
            created_at=yesterday,
            ticker="MSFT",
            strategy="REVERSAL",
            side="LONG",
            raw_score=0.5,
            sentiment_adj=1.0,
            regime="LOW_VOL",
            target_size_usd=0.0,
            status="APPROVED",
        )
        today_signal = Signal(
            id=3,
            run_id=uuid.uuid4(),
            created_at=datetime.datetime.now(tz=datetime.UTC),
            ticker="GOOGL",
            strategy="REVERSAL",
            side="SHORT",
            raw_score=0.3,
            sentiment_adj=1.0,
            regime="LOW_VOL",
            target_size_usd=0.0,
            status="APPROVED",
        )
        mock_session.query.return_value.filter.return_value.all.return_value = [
            old_signal, today_signal
        ]
        today_iso = datetime.datetime.now(tz=datetime.UTC).date().isoformat()
        expired = expire_stale_signals(mock_session, today_iso)
        assert expired == 1
        assert old_signal.status == SignalStatus.EXPIRED.value
        assert today_signal.status == SignalStatus.APPROVED.value

    def test_no_stale_signals(self, mock_session):
        mock_session.query.return_value.filter.return_value.all.return_value = []
        count = expire_stale_signals(mock_session, "2026-03-27")
        assert count == 0


class TestWriteEvent:
    def test_creates_event_with_correct_fields(self, mock_session):
        event = write_event(
            mock_session,
            event_type=EventType.ORDER_SUBMITTED,
            severity=Severity.INFO,
            message="test message",
            run_id="abc-123",
            payload={"ticker": "AAPL"},
        )
        assert event.event_type == "ORDER_SUBMITTED"
        assert event.severity == "INFO"
        assert event.subsystem == "S6"
        assert event.message == "test message"
        assert event.run_id == "abc-123"
        assert event.payload == {"ticker": "AAPL"}
        mock_session.add.assert_called_once_with(event)
        mock_session.flush.assert_called_once()

    def test_defaults_payload_to_empty_dict(self, mock_session):
        event = write_event(
            mock_session,
            event_type=EventType.RISK_HALT,
            severity=Severity.CRITICAL,
            message="halt",
        )
        assert event.payload == {}
