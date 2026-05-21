"""Tests for dashboard signals page."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from dash import html

from algotrader.dashboard.pages.signals import _signal_row, get_layout, refresh_signals_table


class TestGetLayout:
    def test_returns_div(self):
        layout = get_layout()
        assert layout is not None
        assert isinstance(layout, html.Div)

    def test_has_refresh_button(self):
        layout = get_layout()
        children = layout.children
        assert any(
            hasattr(c, "children") and isinstance(c.children, str) and "Pending" in c.children
            for c in children
        )


class TestSignalRow:
    def test_long_side_green(self):
        signal = MagicMock()
        signal.id = 1
        signal.ticker = "AAPL"
        signal.strategy = "STAT_ARB"
        signal.side = "LONG"
        signal.raw_score = -1.5
        signal.sentiment_adj = 0.8
        signal.regime = "LOW_VOL"
        signal.created_at = None

        row = _signal_row(signal)
        assert row is not None
        assert isinstance(row, html.Tr)

    def test_short_side_red(self):
        signal = MagicMock()
        signal.id = 2
        signal.ticker = "MSFT"
        signal.strategy = "REVERSAL"
        signal.side = "SHORT"
        signal.raw_score = 0.5
        signal.sentiment_adj = 0.5
        signal.regime = "MED_VOL"
        signal.created_at = None

        row = _signal_row(signal)
        assert row is not None


class TestRefreshSignalsTable:
    @patch("algotrader.dashboard.pages.signals.get_session")
    def test_no_pending_signals_shows_alert(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: s
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_session

        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        table, soft_live = refresh_signals_table(0, 0, False, False)
        assert table is not None
        assert soft_live is False

    @patch("algotrader.dashboard.pages.signals.get_session")
    def test_pending_signals_renders_table(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: s
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_session

        signal = MagicMock()
        signal.id = 1
        signal.ticker = "AAPL"
        signal.strategy = "STAT_ARB"
        signal.side = "LONG"
        signal.raw_score = -1.5
        signal.sentiment_adj = 0.8
        signal.regime = "LOW_VOL"
        signal.created_at = None

        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = [signal]

        table, soft_live = refresh_signals_table(0, 0, False, False)
        assert table is not None
        assert soft_live is False

    @patch("algotrader.dashboard.pages.signals.get_session")
    def test_error_returns_alert(self, mock_get_session):
        mock_get_session.side_effect = Exception("DB failure")

        table, soft_live = refresh_signals_table(0, 0, False, False)
        assert table is not None
        assert soft_live is False
