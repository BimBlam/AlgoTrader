"""Unit tests for algotrader.sentiment.preprocessor."""

from algotrader.sentiment.preprocessor import (
    build_ticker_patterns,
    clean_text,
    extract_ticker_mentions,
    preprocess_item,
)


class TestCleanText:
    def test_strips_http_url(self):
        result = clean_text("Buy AAPL now https://example.com/news today")
        assert "http" not in result
        assert "AAPL" in result

    def test_strips_www_url(self):
        result = clean_text("See www.example.com for details")
        assert "www." not in result

    def test_removes_non_ascii(self):
        result = clean_text("Earnings report — great résumé")
        assert "é" not in result
        assert "—" not in result

    def test_collapses_whitespace(self):
        result = clean_text("AAPL  is   up")
        assert "  " not in result

    def test_non_string_returns_empty(self):
        assert clean_text(None) == ""   # type: ignore
        assert clean_text(42) == ""     # type: ignore
        assert clean_text([]) == ""     # type: ignore

    def test_empty_string_returns_empty(self):
        assert clean_text("") == ""


class TestExtractTickerMentions:
    def test_bare_ticker(self):
        patterns = build_ticker_patterns(["AAPL"])
        result = extract_ticker_mentions("AAPL earnings were strong", patterns)
        assert result == ["AAPL"]

    def test_cashtag_form(self):
        patterns = build_ticker_patterns(["AAPL"])
        result = extract_ticker_mentions("$AAPL is up 5%", patterns)
        assert result == ["AAPL"]

    def test_no_substring_match(self):
        # APPS must not match when looking for APP
        patterns = build_ticker_patterns(["APP"])
        result = extract_ticker_mentions("APPS is a different company", patterns)
        assert result == []

    def test_multiple_mentions_counted(self):
        patterns = build_ticker_patterns(["AAPL"])
        result = extract_ticker_mentions("AAPL AAPL AAPL", patterns)
        assert len(result) == 3

    def test_multiple_tickers(self):
        patterns = build_ticker_patterns(["AAPL", "MSFT"])
        result = extract_ticker_mentions("AAPL and MSFT both rose", patterns)
        assert "AAPL" in result
        assert "MSFT" in result

    def test_case_insensitive(self):
        patterns = build_ticker_patterns(["AAPL"])
        result = extract_ticker_mentions("aapl is trending", patterns)
        assert "AAPL" in result


class TestPreprocessItem:
    def test_combines_title_and_text(self):
        patterns = build_ticker_patterns(["AAPL"])
        item = {"title": "AAPL beats", "text": "Strong revenue growth"}
        cleaned, tickers = preprocess_item(item, patterns)
        assert "AAPL" in cleaned
        assert "AAPL" in tickers

    def test_falls_back_to_text_only(self):
        patterns = build_ticker_patterns(["MSFT"])
        item = {"text": "MSFT earnings miss"}
        cleaned, tickers = preprocess_item(item, patterns)
        assert "MSFT" in tickers

    def test_falls_back_to_title_only(self):
        patterns = build_ticker_patterns(["TSLA"])
        item = {"title": "TSLA deliveries up"}
        cleaned, tickers = preprocess_item(item, patterns)
        assert "TSLA" in tickers

    def test_empty_item_returns_empty(self):
        patterns = build_ticker_patterns(["AAPL"])
        cleaned, tickers = preprocess_item({}, patterns)
        assert cleaned == ""
        assert tickers == []

    def test_url_stripped_before_ticker_match(self):
        # Ticker should not be found inside a URL path segment
        patterns = build_ticker_patterns(["COM"])
        item = {"text": "Visit https://example.com/help for info"}
        cleaned, tickers = preprocess_item(item, patterns)
        # .com in URL is stripped; "com" does not appear in cleaned text
        assert "COM" not in tickers
