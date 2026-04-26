"""tests/unit/s6/test_reconciler.py"""
from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch

import pytest

from algotrader.execution.reconcile import _last_fill_price, _reconcile
from algotrader.shared.constants import EventType
from algotrader.shared.models import Position


def _open_position(ticker: str, account_type: str = "PAPER") -> Position:
    return Position(
        id=1,
        ticker=ticker,
        side="BUY",
        entry_price=150.0,
        quantity=10,
        entry_time=datetime.datetime.now(tz=datetime.UTC),
        status="OPEN",
        order_id=1,
        account_type=account_type,
    )


def _make_ibkr_position(symbol: str) -> MagicMock:
    pos = MagicMock()
    pos.contract.symbol = symbol
    return pos


class TestLastFillPrice:
    def test_returns_avg_price_from_executions(self):
        ibkr = MagicMock()
        exec_mock = MagicMock()
        exec_mock.contract.symbol = "AAPL"
        exec_mock.execution.avgPrice = "149.75"
        ibkr._ib.executions.return_value = [exec_mock]
        result = _last_fill_price(ibkr, "AAPL")
        assert result == pytest.approx(149.75)

    def test_returns_none_when_no_matching_execution(self):
        ibkr = MagicMock()
        exec_mock = MagicMock()
        exec_mock.contract.symbol = "MSFT"
        ibkr._ib.executions.return_value = [exec_mock]
        result = _last_fill_price(ibkr, "AAPL")
        assert result is None

    def test_returns_none_on_exception(self):
        ibkr = MagicMock()
        ibkr._ib.executions.side_effect = RuntimeError("IBKR error")
        result = _last_fill_price(ibkr, "AAPL")
        assert result is None


class TestReconcile:
    @patch("algotrader.execution.reconcile.expire_stale_signals", return_value=0)
    @patch("algotrader.execution.reconcile.write_event")
    @patch("algotrader.execution.reconcile.close_position")
    @patch("algotrader.execution.reconcile.get_session")
    def test_closes_position_not_in_ibkr(
        self,
        mock_get_session,
        mock_close_pos,
        mock_write_event,
        mock_expire,
    ):
        db_pos = _open_position("AAPL")
        session = MagicMock()
        session.__enter__ = lambda s: s
        session.__exit__ = MagicMock(return_value=False)
        session.query.return_value.filter.return_value.all.return_value = [db_pos]
        mock_get_session.return_value = session

        ibkr = MagicMock()
        # AAPL is NOT in IBKR portfolio
        ibkr._ib.positions.return_value = []
        ibkr._ib.executions.return_value = []

        _reconcile("run-1", "PAPER", ibkr)

        mock_close_pos.assert_called_once()
        event_types = [c.kwargs["event_type"] for c in mock_write_event.call_args_list]
        assert EventType.POSITION_CLOSED in event_types

    @patch("algotrader.execution.reconcile.expire_stale_signals", return_value=0)
    @patch("algotrader.execution.reconcile.write_event")
    @patch("algotrader.execution.reconcile.close_position")
    @patch("algotrader.execution.reconcile.get_session")
    def test_keeps_position_still_in_ibkr(
        self,
        mock_get_session,
        mock_close_pos,
        mock_write_event,
        mock_expire,
    ):
        db_pos = _open_position("AAPL")
        session = MagicMock()
        session.__enter__ = lambda s: s
        session.__exit__ = MagicMock(return_value=False)
        session.query.return_value.filter.return_value.all.return_value = [db_pos]
        mock_get_session.return_value = session

        ibkr = MagicMock()
        # AAPL IS in IBKR portfolio
        ibkr._ib.positions.return_value = [_make_ibkr_position("AAPL")]

        _reconcile("run-1", "PAPER", ibkr)

        mock_close_pos.assert_not_called()

    @patch("algotrader.execution.reconcile.expire_stale_signals", return_value=3)
    @patch("algotrader.execution.reconcile.write_event")
    @patch("algotrader.execution.reconcile.close_position")
    @patch("algotrader.execution.reconcile.get_session")
    def test_expires_stale_signals(
        self,
        mock_get_session,
        mock_close_pos,
        mock_write_event,
        mock_expire,
    ):
        session = MagicMock()
        session.__enter__ = lambda s: s
        session.__exit__ = MagicMock(return_value=False)
        session.query.return_value.filter.return_value.all.return_value = []
        mock_get_session.return_value = session

        ibkr = MagicMock()
        ibkr._ib.positions.return_value = []

        _reconcile("run-1", "PAPER", ibkr)

        mock_expire.assert_called_once()
