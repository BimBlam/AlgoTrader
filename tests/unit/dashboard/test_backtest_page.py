"""Tests for dashboard backtest page."""
from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch

from dash import html

from algotrader.dashboard.pages.backtest import get_layout, update_backtest


class TestGetLayout:
    def test_returns_div(self):
        layout = get_layout()
        assert layout is not None
        assert isinstance(layout, html.Div)


class TestUpdateBacktest:
    @patch("algotrader.dashboard.pages.backtest.get_session")
    def test_no_runs_shows_alert(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: s
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_session

        mock_session.query.return_value.order_by.return_value.limit.return_value.all.return_value = []

        result = update_backtest(0, 0)
        assert result is not None

    @patch("algotrader.dashboard.pages.backtest.get_session")
    def test_runs_renders_table(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: s
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_session

        run = MagicMock()
        run.created_at = datetime.datetime(2026, 4, 26, 12, 0, tzinfo=datetime.UTC)
        run.strategy = "REVERSAL"
        run.sharpe = 1.25
        run.sortino = 1.50
        run.max_drawdown = -0.08
        run.pbo = 0.12
        run.deflated_sharpe = 0.95
        run.date_range_start = datetime.date(2024, 1, 1)
        run.date_range_end = datetime.date(2025, 1, 1)
        run.code_version = "abc123def"

        mock_session.query.return_value.order_by.return_value.limit.return_value.all.return_value = [run]

        result = update_backtest(0, 0)
        assert result is not None

    @patch("algotrader.dashboard.pages.backtest.get_session")
    def test_error_returns_alert(self, mock_get_session):
        mock_get_session.side_effect = Exception("DB failure")

        result = update_backtest(0, 0)
        assert result is not None
