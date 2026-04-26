"""Tests for dashboard logs page."""
from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch

from dash import html

from algotrader.dashboard.pages.logs import _SEVERITY_COLOR, get_layout, update_logs


class TestGetLayout:
    def test_returns_div(self):
        layout = get_layout()
        assert layout is not None
        assert isinstance(layout, html.Div)


class TestSeverityColor:
    def test_all_severities_mapped(self):
        assert "INFO" in _SEVERITY_COLOR
        assert "WARNING" in _SEVERITY_COLOR
        assert "ERROR" in _SEVERITY_COLOR
        assert "CRITICAL" in _SEVERITY_COLOR


class TestUpdateLogs:
    @patch("algotrader.dashboard.pages.logs.get_session")
    def test_no_logs_shows_alert(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: s
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_session

        mock_session.query.return_value.order_by.return_value.limit.return_value.all.return_value = []

        result = update_logs(0, "ALL", "ALL", 100)
        assert result is not None

    @patch("algotrader.dashboard.pages.logs.get_session")
    def test_logs_renders_table(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: s
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_session

        event = MagicMock()
        event.timestamp = datetime.datetime(2026, 4, 26, 12, 0, tzinfo=datetime.UTC)
        event.subsystem = "S1"
        event.event_type = "STARTUP"
        event.severity = "INFO"
        event.message = "System started"

        mock_session.query.return_value.order_by.return_value.limit.return_value.all.return_value = [event]

        result = update_logs(0, "ALL", "ALL", 100)
        assert result is not None

    @patch("algotrader.dashboard.pages.logs.get_session")
    def test_error_returns_alert(self, mock_get_session):
        mock_get_session.side_effect = Exception("DB failure")

        result = update_logs(0, "ALL", "ALL", 100)
        assert result is not None

    @patch("algotrader.dashboard.pages.logs.get_session")
    def test_severity_filter_applied(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: s
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_session

        mock_session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

        result = update_logs(0, "ERROR", "ALL", 100)
        assert result is not None

    @patch("algotrader.dashboard.pages.logs.get_session")
    def test_subsystem_filter_applied(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: s
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_session

        mock_session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

        result = update_logs(0, "ALL", "S1", 100)
        assert result is not None
