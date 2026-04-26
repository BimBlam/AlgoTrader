"""tests/unit/s6/test_fill_tracker.py"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from algotrader.execution.fill_tracker import FILL_TIMEOUT_SECONDS, FillTracker
from algotrader.shared.constants import EventType


def _make_trade(order_id: int = 1) -> MagicMock:
    trade = MagicMock()
    trade.order.orderId = order_id
    # fillEvent behaves like an ib_insync Event — support += to attach handlers
    trade.fillEvent = MagicMock()
    return trade


def _make_fill(avg_price: float = 149.75) -> MagicMock:
    fill = MagicMock()
    fill.execution.avgPrice = str(avg_price)
    return fill


class TestFillTrackerAttach:
    def test_registers_callback(self, mock_session, sample_order):
        tracker = FillTracker(mock_session, "run-1")
        trade = _make_trade(order_id=42)
        # Capture fill_event reference BEFORE attach() — the += operator in
        # attach() rebinds trade.fillEvent to the __iadd__ return value.
        fill_event = trade.fillEvent
        tracker.attach(trade, sample_order)

        assert 42 in tracker._pending
        fill_event.__iadd__.assert_called_once_with(tracker._on_fill)

    def test_multiple_trades_tracked(self, mock_session, sample_order):
        tracker = FillTracker(mock_session, "run-1")
        for i in range(3):
            t = _make_trade(order_id=i)
            tracker.attach(t, sample_order)
        assert len(tracker._pending) == 3


class TestFillTrackerOnFill:
    @patch("algotrader.execution.fill_tracker.write_position")
    @patch("algotrader.execution.fill_tracker.update_order_filled")
    @patch("algotrader.execution.fill_tracker.write_event")
    def test_fill_updates_order_and_creates_position(
        self,
        mock_write_event,
        mock_update_order,
        mock_write_position,
        mock_session,
        sample_order,
    ):
        mock_write_position.return_value = MagicMock(id=99)
        tracker = FillTracker(mock_session, "run-1")
        trade = _make_trade(order_id=1)
        tracker.attach(trade, sample_order)

        fill = _make_fill(avg_price=149.75)
        tracker._on_fill(trade, fill)

        mock_update_order.assert_called_once()
        call_args = mock_update_order.call_args
        assert call_args[0][2] == pytest.approx(149.75)  # fill_price

        mock_write_position.assert_called_once()
        assert mock_session.commit.called

    @patch("algotrader.execution.fill_tracker.write_position")
    @patch("algotrader.execution.fill_tracker.update_order_filled")
    @patch("algotrader.execution.fill_tracker.write_event")
    def test_fill_removes_from_pending(
        self,
        mock_write_event,
        mock_update_order,
        mock_write_position,
        mock_session,
        sample_order,
    ):
        mock_write_position.return_value = MagicMock(id=1)
        tracker = FillTracker(mock_session, "run-1")
        trade = _make_trade(order_id=1)
        tracker.attach(trade, sample_order)
        assert 1 in tracker._pending

        tracker._on_fill(trade, _make_fill())
        assert 1 not in tracker._pending

    @patch("algotrader.execution.fill_tracker.write_position")
    @patch("algotrader.execution.fill_tracker.update_order_filled")
    @patch("algotrader.execution.fill_tracker.write_event")
    def test_unknown_order_id_is_ignored(
        self,
        mock_write_event,
        mock_update_order,
        mock_write_position,
        mock_session,
        sample_order,
    ):
        tracker = FillTracker(mock_session, "run-1")
        unknown_trade = _make_trade(order_id=999)
        # Not attached — calling _on_fill should be a no-op
        tracker._on_fill(unknown_trade, _make_fill())
        mock_update_order.assert_not_called()

    @patch("algotrader.execution.fill_tracker.write_position")
    @patch("algotrader.execution.fill_tracker.update_order_filled")
    @patch("algotrader.execution.fill_tracker.write_event")
    def test_emits_two_events_per_fill(
        self,
        mock_write_event,
        mock_update_order,
        mock_write_position,
        mock_session,
        sample_order,
    ):
        mock_write_position.return_value = MagicMock(id=1)
        tracker = FillTracker(mock_session, "run-1")
        trade = _make_trade(order_id=1)
        tracker.attach(trade, sample_order)
        tracker._on_fill(trade, _make_fill())

        event_types = [c.kwargs["event_type"] for c in mock_write_event.call_args_list]
        assert EventType.ORDER_FILLED in event_types
        assert EventType.POSITION_OPENED in event_types


class TestFillTrackerWait:
    def test_wait_calls_ibkr_sleep_with_timeout(self, mock_session):
        mock_ibkr = MagicMock()
        tracker = FillTracker(mock_session, "run-1")
        tracker.wait(mock_ibkr)
        mock_ibkr.sleep.assert_called_once_with(FILL_TIMEOUT_SECONDS)

    def test_returns_number_of_fills_captured(self, mock_session, sample_order):
        mock_ibkr = MagicMock()
        tracker = FillTracker(mock_session, "run-1")

        # Pre-populate two pending trades; none fill (sleep does nothing)
        for i in (1, 2):
            t = _make_trade(order_id=i)
            tracker.attach(t, sample_order)

        fills = tracker.wait(mock_ibkr)
        # Nothing filled during sleep
        assert fills == 0
        assert len(tracker._pending) == 2
