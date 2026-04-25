"""
Unit tests for s5_sentiment.main.

All external dependencies (DB, filesystem, GPU) are mocked.
Tests focus on control flow: correct degradation, correct event emission,
correct handling of missing files.
"""

from __future__ import annotations

import datetime
import json
from unittest.mock import MagicMock, patch

import pytest

from s5_sentiment.main import (
    _load_json_file,
    _load_attention_history,
    _load_sentiment_history,
)


# ---------------------------------------------------------------------------
# _load_json_file
# ---------------------------------------------------------------------------


class TestLoadJsonFile:
    def test_missing_file_returns_empty_list(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        result = _load_json_file(path, "news", "run-1")
        assert result == []

    def test_valid_list_json(self, tmp_path):
        path = tmp_path / "2025-01-15.json"
        data = [{"text": "AAPL up"}, {"text": "MSFT down"}]
        path.write_text(json.dumps(data))
        result = _load_json_file(path, "news", "run-1")
        assert result == data

    def test_dict_with_items_key(self, tmp_path):
        path = tmp_path / "2025-01-15.json"
        data = {"items": [{"text": "headline"}], "meta": "ignored"}
        path.write_text(json.dumps(data))
        result = _load_json_file(path, "news", "run-1")
        assert result == [{"text": "headline"}]

    def test_malformed_json_returns_empty(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not valid json")
        result = _load_json_file(path, "news", "run-1")
        assert result == []

    def test_unexpected_format_returns_empty(self, tmp_path):
        path = tmp_path / "weird.json"
        path.write_text('"just a string"')
        result = _load_json_file(path, "news", "run-1")
        assert result == []


# ---------------------------------------------------------------------------
# _load_attention_history
# ---------------------------------------------------------------------------


class TestLoadAttentionHistory:
    def _make_row(self, ticker, date_str, mentions):
        return (ticker, datetime.date.fromisoformat(date_str), mentions)

    def test_returns_dict_with_all_tickers(self):
        mock_session = MagicMock()
        mock_query = mock_session.query.return_value
        mock_query.filter.return_value.order_by.return_value.all.return_value = []

        result = _load_attention_history(
            mock_session, ["AAPL", "MSFT"], datetime.date(2025, 1, 15), 30
        )
        assert "AAPL" in result
        assert "MSFT" in result

    def test_maps_mention_counts_correctly(self):
        mock_session = MagicMock()
        rows = [
            ("AAPL", datetime.date(2025, 1, 13), 5),
            ("AAPL", datetime.date(2025, 1, 14), 8),
        ]
        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = rows

        result = _load_attention_history(
            mock_session, ["AAPL"], datetime.date(2025, 1, 15), 30
        )
        assert result["AAPL"] == [5, 8]

    def test_empty_db_returns_empty_lists(self):
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        result = _load_attention_history(
            mock_session, ["AAPL"], datetime.date(2025, 1, 15), 30
        )
        assert result["AAPL"] == []


# ---------------------------------------------------------------------------
# _load_sentiment_history
# ---------------------------------------------------------------------------


class TestLoadSentimentHistory:
    def test_returns_tuples(self):
        mock_session = MagicMock()
        rows = [("AAPL", datetime.date(2025, 1, 14), 0.3, 1.5)]
        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = rows

        result = _load_sentiment_history(
            mock_session, ["AAPL"], datetime.date(2025, 1, 15), lookback=5
        )
        assert result["AAPL"] == [(0.3, 1.5)]

    def test_no_history_returns_empty(self):
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        result = _load_sentiment_history(
            mock_session, ["AAPL"], datetime.date(2025, 1, 15), lookback=5
        )
        assert result["AAPL"] == []


# ---------------------------------------------------------------------------
# Full run() integration-style unit test
# ---------------------------------------------------------------------------


class TestRun:
    """
    Test run() end-to-end with all I/O mocked.
    Validates event emission, graceful degradation on missing files, and
    that a sentiment_scores row is written for every universe ticker.
    """

    def _build_mocks(self, mock_cfg, tmp_path, news_data=None, social_data=None):
        """Helper: write optional raw files and return patched env context."""
        date_str = "2025-01-15"

        # Write raw files if provided
        news_dir = tmp_path / "raw" / "news"
        social_dir = tmp_path / "raw" / "social"
        news_dir.mkdir(parents=True)
        social_dir.mkdir(parents=True)

        if news_data is not None:
            (news_dir / f"{date_str}.json").write_text(json.dumps(news_data))
        if social_data is not None:
            (social_dir / f"{date_str}.json").write_text(json.dumps(social_data))

        mock_cfg.system.data_dir_hdd = str(tmp_path)
        return mock_cfg

    @patch("s5_sentiment.main.utc_today", return_value=datetime.date(2025, 1, 15))
    def test_run_writes_event_for_every_ticker(self, mock_today, mock_cfg, tmp_path):
        self._build_mocks(mock_cfg, tmp_path, news_data=[], social_data=[])

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        # Return empty history
        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        executed_stmts = []

        def capture_execute(stmt):
            executed_stmts.append(stmt)

        mock_session.execute = capture_execute

        with (
            patch("s5_sentiment.main.get_config", return_value=mock_cfg),
            patch("s5_sentiment.main.init_db"),
            patch("s5_sentiment.main.get_session", return_value=mock_session),
            patch("s5_sentiment.scorer._load_finbert", return_value=None),
        ):
            from s5_sentiment.main import run
            run("test-run-id-001")

        # One upsert per universe ticker (AAPL, MSFT, TSLA)
        assert len(executed_stmts) == len(mock_cfg.universe.tickers)

    @patch("s5_sentiment.main.utc_today", return_value=datetime.date(2025, 1, 15))
    def test_run_raises_on_empty_universe(self, mock_today, mock_cfg, tmp_path):
        mock_cfg.universe.tickers = []
        mock_cfg.system.data_dir_hdd = str(tmp_path)

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        with (
            patch("s5_sentiment.main.get_config", return_value=mock_cfg),
            patch("s5_sentiment.main.init_db"),
            patch("s5_sentiment.main.get_session", return_value=mock_session),
        ):
            from shared.exceptions import SentimentError
            from s5_sentiment.main import run
            with pytest.raises(SentimentError):
                run("test-run-id-002")

    @patch("s5_sentiment.main.utc_today", return_value=datetime.date(2025, 1, 15))
    def test_run_degrades_gracefully_when_files_missing(self, mock_today, mock_cfg, tmp_path):
        """Missing news/social files must not raise; pipeline completes with model_used='none'."""
        mock_cfg.system.data_dir_hdd = str(tmp_path)
        # Do NOT create the raw files

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

        executed_stmts = []
        mock_session.execute = lambda stmt: executed_stmts.append(stmt)

        with (
            patch("s5_sentiment.main.get_config", return_value=mock_cfg),
            patch("s5_sentiment.main.init_db"),
            patch("s5_sentiment.main.get_session", return_value=mock_session),
            patch("s5_sentiment.scorer._load_finbert", return_value=None),
        ):
            from s5_sentiment.main import run
            run("test-run-id-003")  # must not raise

        # Even with no files, one upsert per ticker is written
        assert len(executed_stmts) == len(mock_cfg.universe.tickers)
