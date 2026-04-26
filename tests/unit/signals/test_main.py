"""
Integration-style unit tests for main.py — full pipeline with mocked I/O.
"""
import datetime
import types
from unittest.mock import MagicMock, patch

import pytest

from algotrader.signals import main as s3_main

RUN_ID = "test-run-main-001"
TODAY = datetime.date(2025, 1, 15)


def _make_cfg():
    return types.SimpleNamespace(
        system=types.SimpleNamespace(db_url="postgresql://test/test", data_dir_ssd="/tmp"),
        strategy_params=types.SimpleNamespace(
            stat_arb=types.SimpleNamespace(enabled=True),
            reversal=types.SimpleNamespace(enabled=True),
            regime_combo=types.SimpleNamespace(),
        ),
        risk=types.SimpleNamespace(extreme_vol_halt=True),
        sentiment_params=types.SimpleNamespace(),
    )


class TestRunPipeline:
    @patch("algotrader.signals.main.write_event")
    @patch("algotrader.signals.main.write_signals")
    @patch("algotrader.signals.main.resolve_competition", return_value=[])
    @patch("algotrader.signals.main.compute_reversal_signals", return_value=[])
    @patch("algotrader.signals.main.compute_stat_arb_signals", return_value=[])
    @patch("algotrader.signals.main.load_sentiment_scores", return_value={})
    @patch("algotrader.signals.main.classify_regime", return_value="LOW_VOL")
    @patch("algotrader.signals.main.write_ou_params")
    @patch("algotrader.signals.main.fit_ou_params", return_value=[])
    @patch("algotrader.signals.main.load_sector_etf_returns", return_value={})
    @patch("algotrader.signals.main.load_returns")
    @patch("algotrader.signals.main.get_session")
    @patch("algotrader.signals.main.init_db")
    @patch("algotrader.signals.main.get_config")
    def test_happy_path_calls_all_stages(
        self, mock_get_config, mock_init_db, mock_get_session,
        mock_load_returns, mock_load_etf, mock_fit_ou, mock_write_ou,
        mock_regime, mock_sentiment, mock_stat_arb, mock_reversal,
        mock_competition, mock_write_signals, mock_write_event,
    ):
        mock_get_config.return_value = _make_cfg()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_session

        s3_main.run(RUN_ID)

        mock_init_db.assert_called_once()
        mock_load_returns.assert_called_once()
        mock_fit_ou.assert_called_once()
        mock_write_ou.assert_called_once()
        mock_regime.assert_called_once()
        mock_sentiment.assert_called_once()
        mock_stat_arb.assert_called_once()
        mock_reversal.assert_called_once()
        mock_competition.assert_called_once()
        mock_write_signals.assert_called_once()
        mock_write_event.assert_called()

    @patch("algotrader.signals.main.write_event")
    @patch("algotrader.signals.main.load_returns")
    @patch("algotrader.signals.main.get_session")
    @patch("algotrader.signals.main.init_db")
    @patch("algotrader.signals.main.get_config")
    def test_data_error_exits_with_signal_error_event(
        self, mock_get_config, mock_init_db, mock_get_session,
        mock_load_returns, mock_write_event,
    ):
        from algotrader.shared.exceptions import DataError
        mock_get_config.return_value = _make_cfg()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_session
        mock_load_returns.side_effect = DataError("missing file")

        with pytest.raises(SystemExit) as exc_info:
            s3_main.run(RUN_ID)

        assert exc_info.value.code == 1
        # S3 must not emit a non-spec event like SIGNAL_ERROR; leave JOB_FAILED to S1
        mock_write_event.assert_not_called()

    @patch("algotrader.signals.main.write_event")
    @patch("algotrader.signals.main.load_returns")
    @patch("algotrader.signals.main.get_session")
    @patch("algotrader.signals.main.init_db")
    @patch("algotrader.signals.main.get_config")
    def test_unexpected_exception_exits_cleanly(
        self, mock_get_config, mock_init_db, mock_get_session,
        mock_load_returns, mock_write_event,
    ):
        mock_get_config.return_value = _make_cfg()
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_session
        mock_load_returns.side_effect = RuntimeError("unexpected")

        with pytest.raises(SystemExit) as exc_info:
            s3_main.run(RUN_ID)

        assert exc_info.value.code == 1
