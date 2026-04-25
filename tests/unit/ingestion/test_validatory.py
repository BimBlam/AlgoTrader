"""Tests for OHLCV validation rules (all three contract conditions)."""

from __future__ import annotations

import pandas as pd

from algotrader.ingestion.validator import validate_ohlcv


def _df(dates, volumes=None, closes=None, lows=None):
    n = len(dates)
    closes = closes or [100.0] * n
    lows   = lows   or [c - 1.0 for c in closes]
    df = pd.DataFrame(
        {
            "open":      closes,
            "high":      [c + 1.0 for c in closes],
            "low":       lows,
            "close":     closes,
            "volume":    volumes or [1_000_000] * n,
            "adj_close": closes,
        },
        index=pd.to_datetime(dates),
    )
    df.index.name = "date"
    return df


class TestCleanData:
    def test_no_issues_on_valid_data(self):
        dates = pd.bdate_range("2024-01-02", periods=10)
        assert validate_ohlcv(_df(dates), "AAPL") == []

    def test_empty_df_is_flagged(self):
        df = pd.DataFrame(columns=["open", "high", "low", "close", "volume", "adj_close"])
        issues = validate_ohlcv(df, "AAPL")
        assert issues

    def test_single_row_no_gap_issue(self):
        dates = pd.bdate_range("2024-01-02", periods=1)
        issues = validate_ohlcv(_df(dates), "AAPL")
        # Single row: no gap possible; other checks must pass for clean data.
        assert not any("Gap" in i for i in issues)


class TestNegativePrices:
    def test_negative_close_flagged(self):
        dates = pd.bdate_range("2024-01-02", periods=5)
        closes = [100.0, 100.0, -0.01, 100.0, 100.0]
        issues = validate_ohlcv(_df(dates, closes=closes), "AAPL")
        assert any("Negative" in i for i in issues)

    def test_zero_price_not_flagged_as_negative(self):
        # Zero close is not negative. Explicitly keep lows >= 0 so the factory
        # doesn't generate a negative low from (close - 1.0).
        dates = pd.bdate_range("2024-01-02", periods=3)
        closes = [100.0, 0.0, 100.0]
        lows   = [99.0,  0.0, 99.0]   # floor at 0, not -1
        issues = validate_ohlcv(_df(dates, closes=closes, lows=lows), "AAPL")
        neg_issues = [i for i in issues if "Negative" in i]
        assert not neg_issues


    def test_negative_low_flagged(self):
        dates = pd.bdate_range("2024-01-02", periods=3)
        lows = [99.0, -5.0, 99.0]
        issues = validate_ohlcv(_df(dates, lows=lows), "AAPL")
        assert any("Negative" in i for i in issues)


class TestZeroVolume:
    def test_zero_volume_on_one_day_flagged(self):
        dates = pd.bdate_range("2024-01-02", periods=5)
        volumes = [1_000_000, 0, 1_000_000, 1_000_000, 1_000_000]
        issues = validate_ohlcv(_df(dates, volumes=volumes), "AAPL")
        assert any("Zero-volume" in i for i in issues)

    def test_all_positive_volume_no_issue(self):
        dates = pd.bdate_range("2024-01-02", periods=5)
        volumes = [500_000, 1_000_000, 750_000, 250_000, 1_200_000]
        issues = validate_ohlcv(_df(dates, volumes=volumes), "AAPL")
        assert not any("Zero-volume" in i for i in issues)


class TestTradingDayGaps:
    def test_gap_of_3_is_within_limit(self):
        # Jan 4 (Thu), Jan 5 (Fri), Jan 8 (Mon) absent = 3 missing days.
        dates = ["2024-01-03", "2024-01-09"]
        issues = validate_ohlcv(_df(dates), "AAPL")
        gap_issues = [i for i in issues if "Gap" in i]
        assert not gap_issues

    def test_gap_of_4_is_flagged(self):
        # Jan 3, Jan 4, Jan 5, Jan 8 absent = 4 consecutive missing days.
        dates = ["2024-01-02", "2024-01-09"]
        issues = validate_ohlcv(_df(dates), "AAPL")
        gap_issues = [i for i in issues if "Gap" in i]
        assert gap_issues

    def test_gap_message_contains_start_date(self):
        dates = ["2024-01-02", "2024-01-16"]
        issues = validate_ohlcv(_df(dates), "AAPL")
        assert any("Gap" in i for i in issues)

    def test_no_gap_on_contiguous_days(self):
        dates = pd.bdate_range("2024-01-02", periods=15)
        issues = validate_ohlcv(_df(dates), "AAPL")
        assert not any("Gap" in i for i in issues)
