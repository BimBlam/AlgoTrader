"""Tests for dashboard calibration page."""
from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch

from dash import html

from algotrader.dashboard.pages.calibration import (
    apply_mode_change,
    get_layout,
    reload_params,
    save_strategy_params,
    update_backtest_diff,
)


class TestGetLayout:
    @patch("algotrader.dashboard.pages.calibration.read_strategy_params")
    @patch("algotrader.dashboard.pages.calibration.read_system_config")
    def test_returns_div(self, mock_read_sys, mock_read_strat):
        mock_read_strat.return_value = {"stat_arb": {"enabled": True}}
        mock_read_sys.return_value = {"mode": "PAPER", "approval_mode": "HARD"}

        layout = get_layout()
        assert layout is not None
        assert isinstance(layout, html.Div)

    @patch("algotrader.dashboard.pages.calibration.read_strategy_params")
    @patch("algotrader.dashboard.pages.calibration.read_system_config")
    def test_fallback_on_error(self, mock_read_sys, mock_read_strat):
        mock_read_strat.side_effect = Exception("file missing")
        mock_read_sys.side_effect = Exception("file missing")

        layout = get_layout()
        assert layout is not None


class TestSaveStrategyParams:
    @patch("algotrader.dashboard.pages.calibration.write_config_changed_event")
    @patch("algotrader.dashboard.pages.calibration.update_strategy_params")
    @patch("algotrader.dashboard.pages.calibration.get_session")
    def test_valid_yaml_saves(self, mock_get_session, mock_update, mock_write_event):
        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: s
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_session

        msg, color, is_open = save_strategy_params(1, "stat_arb:\n  enabled: true")
        assert "saved" in msg.lower()
        assert color == "success"
        assert is_open is True

    def test_no_clicks_returns_no_update(self):
        from dash import no_update

        result = save_strategy_params(None, "foo")
        assert result == (no_update, no_update, no_update)

    def test_invalid_yaml_returns_error(self):
        msg, color, is_open = save_strategy_params(1, "{invalid")
        assert "YAML" in msg or "error" in msg.lower()
        assert color == "danger"

    def test_non_dict_yaml_returns_error(self):
        msg, color, is_open = save_strategy_params(1, "just a string")
        assert "mapping" in msg.lower()
        assert color == "danger"


class TestReloadParams:
    @patch("algotrader.dashboard.pages.calibration.read_strategy_params")
    def test_returns_yaml_string(self, mock_read):
        mock_read.return_value = {"stat_arb": {"enabled": True}}

        result = reload_params(1)
        assert "stat_arb" in result

    @patch("algotrader.dashboard.pages.calibration.read_strategy_params")
    def test_error_returns_comment(self, mock_read):
        mock_read.side_effect = Exception("file missing")

        result = reload_params(1)
        assert "Error" in result


class TestApplyModeChange:
    @patch("algotrader.dashboard.pages.calibration.write_mode_changed_event")
    @patch("algotrader.dashboard.pages.calibration.update_system_config")
    @patch("algotrader.dashboard.pages.calibration.read_system_config")
    @patch("algotrader.dashboard.pages.calibration.get_session")
    def test_valid_mode_change(self, mock_get_session, mock_read, mock_update, mock_write):
        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: s
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_session
        mock_read.return_value = {"mode": "PAPER", "approval_mode": "HARD"}

        msg, color, is_open = apply_mode_change(1, "LIVE", "SOFT")
        assert "LIVE" in msg
        assert color == "success"
        assert is_open is True

    def test_no_clicks_returns_no_update(self):
        from dash import no_update

        result = apply_mode_change(None, "PAPER", "HARD")
        assert result == (no_update, no_update, no_update)


class TestUpdateBacktestDiff:
    @patch("algotrader.dashboard.pages.calibration.get_session")
    def test_fewer_than_two_runs_shows_alert(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: s
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_session

        mock_session.query.return_value.order_by.return_value.limit.return_value.all.return_value = []

        result = update_backtest_diff(0)
        assert result is not None

    @patch("algotrader.dashboard.pages.calibration.get_session")
    def test_two_runs_renders_table(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: s
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_session

        run1 = MagicMock()
        run1.created_at = datetime.datetime(2026, 4, 26, 12, 0, tzinfo=datetime.UTC)
        run1.sharpe = 1.0
        run1.sortino = 1.2
        run1.max_drawdown = -0.05
        run1.pbo = 0.1
        run1.deflated_sharpe = 0.9

        run2 = MagicMock()
        run2.created_at = datetime.datetime(2026, 4, 25, 12, 0, tzinfo=datetime.UTC)
        run2.sharpe = 0.8
        run2.sortino = 1.0
        run2.max_drawdown = -0.08
        run2.pbo = 0.15
        run2.deflated_sharpe = 0.7

        mock_session.query.return_value.order_by.return_value.limit.return_value.all.return_value = [run1, run2]

        result = update_backtest_diff(0)
        assert result is not None

    @patch("algotrader.dashboard.pages.calibration.get_session")
    def test_error_returns_alert(self, mock_get_session):
        mock_get_session.side_effect = Exception("DB failure")

        result = update_backtest_diff(0)
        assert result is not None
