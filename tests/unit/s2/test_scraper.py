"""Tests for scraper helpers — no real network calls."""

from __future__ import annotations

import datetime
import json
from unittest.mock import patch

import pytest

from s2_data_ingestion.scraper import (
    _find_mentioned_tickers,
    _load_json_safe,
    _merge_by_post_id,
    _merge_by_url,
    _unix_to_date,
    _write_json_safe,
    scrape_news,
    scrape_social,
)


class TestMergeHelpers:
    def test_merge_by_url_deduplicates(self):
        existing = [{"url": "http://a.com", "title": "old"}]
        new = [
            {"url": "http://a.com", "title": "duplicate"},
            {"url": "http://b.com", "title": "new"},
        ]
        merged = _merge_by_url(existing, new)
        assert sum(1 for i in merged if i["url"] == "http://a.com") == 1
        assert any(i["url"] == "http://b.com" for i in merged)

    def test_merge_by_post_id_deduplicates(self):
        existing = [{"post_id": "abc", "title": "old"}]
        new = [{"post_id": "abc", "title": "dupe"}, {"post_id": "xyz", "title": "new"}]
        merged = _merge_by_post_id(existing, new)
        assert sum(1 for i in merged if i["post_id"] == "abc") == 1

    def test_merge_appends_genuinely_new(self):
        existing = [{"url": "http://a.com"}]
        new = [{"url": "http://b.com"}]
        merged = _merge_by_url(existing, new)
        assert len(merged) == 2


class TestTickerMention:
    def test_dollar_sign_match(self):
        found = _find_mentioned_tickers("Bullish on $AAPL today", {"AAPL", "MSFT"})
        assert "AAPL" in found

    def test_word_boundary_match(self):
        found = _find_mentioned_tickers("TSLA is up.", {"TSLA"})
        assert "TSLA" in found

    def test_no_false_positive_on_substring(self):
        # 'TSLA' inside 'TSLAX' should NOT match 'TSLA' as a standalone ticker.
        found = _find_mentioned_tickers("TSLAX is a new thing", {"TSLA"})
        assert "TSLA" not in found

    def test_multiple_tickers_in_one_text(self):
        found = _find_mentioned_tickers("$AAPL and $MSFT both rising", {"AAPL", "MSFT", "TSLA"})
        assert "AAPL" in found and "MSFT" in found and "TSLA" not in found


class TestJsonIO:
    def test_write_and_load_roundtrip(self, tmp_path):
        path = tmp_path / "test.json"
        data = [{"ticker": "AAPL", "title": "Test headline"}]
        _write_json_safe(path, data)
        assert _load_json_safe(path) == data

    def test_load_returns_empty_list_for_missing_file(self, tmp_path):
        assert _load_json_safe(tmp_path / "missing.json") == []

    def test_load_returns_empty_list_for_corrupt_file(self, tmp_path):
        path = tmp_path / "corrupt.json"
        path.write_text("{not: valid json")
        assert _load_json_safe(path) == []

    def test_atomic_write_uses_tmp_then_rename(self, tmp_path):
        path = tmp_path / "out.json"
        _write_json_safe(path, [{"a": 1}])
        assert path.exists()
        assert not path.with_suffix(".tmp").exists()


class TestUnixToDate:
    def test_known_timestamp(self):
        # 2024-01-02 00:00:00 UTC
        assert _unix_to_date(1704153600) == datetime.date(2024, 1, 2)


class TestScrapeNews:
    def test_disabled_returns_path_without_writing(self, mock_cfg, today):
        mock_cfg.sentiment.sources["news"]["enabled"] = False
        path = scrape_news(["AAPL"], mock_cfg, today)
        assert not path.exists()

    def test_writes_news_json_when_enabled(self, mock_cfg, today):
        mock_cfg.sentiment.sources["news"]["enabled"] = True
        fake_news = [{"title": "AAPL soars", "link": "http://x.com", "publisher": "Test",
                      "providerPublishTime": 1710460800}]

        with patch("yfinance.Ticker") as mock_ticker:
            mock_ticker.return_value.news = fake_news
            path = scrape_news(["AAPL"], mock_cfg, today)

        assert path.exists()
        data = json.loads(path.read_text())
        assert len(data) == 1
        assert data[0]["ticker"] == "AAPL"

    def test_idempotent_second_call_does_not_duplicate(self, mock_cfg, today):
        mock_cfg.sentiment.sources["news"]["enabled"] = True
        fake_news = [{"title": "AAPL soars", "link": "http://x.com/a",
                      "publisher": "Test", "providerPublishTime": 1710460800}]

        with patch("yfinance.Ticker") as mock_ticker:
            mock_ticker.return_value.news = fake_news
            scrape_news(["AAPL"], mock_cfg, today)
            path = scrape_news(["AAPL"], mock_cfg, today)

        data = json.loads(path.read_text())
        assert len(data) == 1  # Not 2.


class TestScrapeSOcial:
    def test_twitter_enabled_raises_not_implemented(self, mock_cfg, today):
        mock_cfg.sentiment.sources["twitter"]["enabled"] = True
        with pytest.raises(NotImplementedError):
            scrape_social(["AAPL"], mock_cfg, today)

    def test_reddit_disabled_returns_path_without_writing(self, mock_cfg, today):
        mock_cfg.sentiment.sources["reddit"]["enabled"] = False
        path = scrape_social(["AAPL"], mock_cfg, today)
        assert not path.exists()
