"""Tests for dashboard home page."""
from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch

from dash import html

from algotrader.dashboard.pages.home import _build_events_table, get_layout, update_home


class TestGetLayout:
    def test_returns_div(self):
        layout = get_layout()
        assert layout is not None
        assert isinstance(layout, html.Div)

    def test_contains_expected_elements(self):
        layout = get_layout()
        # Check that the layout contains the expected header
        children = layout.children
        assert any(
            hasattr(c, "children") and c.children == "System Overview"
            for c in children
        )


class TestBuildEventsTable:
    def test_empty_events_returns_table(self):
        table = _build_events_table([])
        assert table is not None

    def test_single_event_renders_row(self):
        event = MagicMock()
        event.timestamp = datetime.datetime(2026, 4, 26, 12, 0, tzinfo=datetime.UTC)
        event.subsystem = "S1"
        event.event_type = "STARTUP"
        event.severity = "INFO"
        event.message = "System started"

        table = _build_events_table([event])
        assert table is not None

    def test_severity_color_mapping(self):
        for sev, expected_class in [
            ("INFO", "table-light"),
            ("WARNING", "table-warning"),
            ("ERROR", "table-danger"),
            ("CRITICAL", "table-danger fw-bold"),
        ]:
            event = MagicMock()
            event.timestamp = None
            event.subsystem = "S1"
            event.event_type = "TEST"
            event.severity = sev
            event.message = "test"

            table = _build_events_table([event])
            rows = table.children[1].children  # tbody
            assert rows[0].className == expected_class


class TestUpdateHome:
    @patch("algotrader.dashboard.pages.home.get_session")
    def test_returns_five_values(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: s
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_session

        # Mock queries
        mock_session.query.return_value.order_by.return_value.first.return_value = None
        mock_session.query.return_value.filter.return_value.all.return_value = []
        mock_session.query.return_value.filter.return_value.count.return_value = 0

        result = update_home(0)
        assert len(result) == 5
        assert result[0] == "—"
        assert result[2] == "0"
        assert result[3] == "0"

    @patch("algotrader.dashboard.pages.home.get_session")
    def test_pnl_calculation(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: s
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_session

        # Mock latest event
        latest = MagicMock()
        latest.subsystem = "S1"
        mock_session.query.return_value.order_by.return_value.first.return_value = latest

        # Mock closed positions
        pos = MagicMock()
        pos.realised_pnl = 123.45
        pos.exit_time = datetime.datetime.now(tz=datetime.UTC)
        mock_session.query.return_value.filter.return_value.all.return_value = [pos]
        mock_session.query.return_value.filter.return_value.count.side_effect = [1, 2]

        result = update_home(0)
        assert result[0] == "S1"
        assert result[2] == "1"
        assert result[3] == "2"

    @patch("algotrader.dashboard.pages.home.get_session")
    def test_error_handling(self, mock_get_session):
        mock_get_session.side_effect = Exception("DB failure")

        result = update_home(0)
        assert len(result) == 5
        assert result[0] == "—"
