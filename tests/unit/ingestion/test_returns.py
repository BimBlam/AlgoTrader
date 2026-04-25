"""Tests for daily returns parquet computation."""

from __future__ import annotations

import datetime
import math
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from algotrader.ingestion.returns import (
    _build_return_row,
    compute_and_write_returns,
)
from algotrader.shared.exceptions import DataError


class TestBuildReturnRow:
    def test_ret_1d_is_correct_log_return(self, make_ohlcv_df, today):
        df = make_ohlcv_df(10)
        # Set today's row explicitly.
        today_ts = pd.Timestamp(today)
        if today_ts not in df.index:
            df = make_ohlcv_df(10, start="2024-03-04")  # lands on 2024-03-15
        row = _build_return_row("AAPL", df, df.index[-1].date(), {})
        expected = math.log(df["adj_close"].iloc[-1] / df["adj_close"].iloc[-2])
        assert abs(row["ret_1d"] - expected) < 1e-10

    def test_ret_5d_is_correct_log_return(self, make_ohlcv_df):
        df = make_ohlcv_df(10)
        today_d = df.index[-1].date()
        row = _build_return_row("AAPL", df, today_d, {})
        expected = math.log(df["adj_close"].iloc[-1] / df["adj_close"].iloc[-6])
        assert abs(row["ret_5d"] - expected) < 1e-10

    def test_returns_none_when_today_absent(self, make_ohlcv_df):
        df = make_ohlcv_df(5, start="2024-01-02")
        row = _build_return_row("AAPL", df, datetime.date(2030, 1, 1), {})
        assert row is None

    def test_sector_etf_populated_from_metadata(self, make_ohlcv_df):
        df = make_ohlcv_df(10)
        today_d = df.index[-1].date()
        meta = {"AAPL": {"sector_etf": "XLK", "shares_outstanding": 15_000_000_000.0}}
        row = _build_return_row("AAPL", df, today_d, meta)
        assert row["sector_etf"] == "XLK"

    def test_sector_etf_empty_when_not_in_metadata(self, make_ohlcv_df):
        df = make_ohlcv_df(10)
        today_d = df.index[-1].date()
        row = _build_return_row("AAPL", df, today_d, {})
        assert row["sector_etf"] == ""

    def test_turnover_nan_when_shares_unknown(self, make_ohlcv_df):
        df = make_ohlcv_df(10)
        today_d = df.index[-1].date()
        meta = {"AAPL": {"sector_etf": "XLK", "shares_outstanding": None}}
        row = _build_return_row("AAPL", df, today_d, meta)
        assert math.isnan(row["turnover"])

    def test_ret_1d_nan_when_insufficient_history(self, make_ohlcv_df):
        df = make_ohlcv_df(1)  # Only one row; can't compute 1d return.
        today_d = df.index[-1].date()
        row = _build_return_row("AAPL", df, today_d, {})
        assert row is not None and math.isnan(row["ret_1d"])

    def test_avg_vol_30_uses_available_rows(self, make_ohlcv_df):
        df = make_ohlcv_df(5)  # Fewer than 30 rows — should still compute.
        today_d = df.index[-1].date()
        row = _build_return_row("AAPL", df, today_d, {})
        assert not math.isnan(row["avg_vol_30"])


class TestComputeAndWriteReturns:
    def _setup_ohlcv(self, cfg, tickers, make_ohlcv_df, start="2024-03-04"):
        ohlcv_dir = Path(cfg.system.data_dir_ssd) / "processed" / "ohlcv"
        ohlcv_dir.mkdir(parents=True, exist_ok=True)
        for t in tickers:
            df = make_ohlcv_df(10, start=start)
            df.to_parquet(ohlcv_dir / f"{t}.parquet")
        return ohlcv_dir

    def test_writes_parquet_file(self, mock_cfg, make_ohlcv_df):
        tickers = ["AAPL"]
        self._setup_ohlcv(mock_cfg, tickers, make_ohlcv_df)
        today_d = pd.bdate_range("2024-03-04", periods=10)[-1].date()

        mock_info = {"sharesOutstanding": 15_000_000_000, "sector": "Technology"}
        with patch("yfinance.Ticker") as mock_ticker:
            mock_ticker.return_value.info = mock_info
            path = compute_and_write_returns(tickers, mock_cfg, today_d)

        assert path.exists()

    def test_schema_matches_spec(self, mock_cfg, make_ohlcv_df):
        """Parquet column names must match §4.4 exactly."""
        tickers = ["AAPL"]
        self._setup_ohlcv(mock_cfg, tickers, make_ohlcv_df)
        today_d = pd.bdate_range("2024-03-04", periods=10)[-1].date()

        with patch("yfinance.Ticker") as mock_ticker:
            mock_ticker.return_value.info = {"sharesOutstanding": 1e10, "sector": "Technology"}
            path = compute_and_write_returns(tickers, mock_cfg, today_d)

        df = pd.read_parquet(path)
        expected_cols = {"date", "ret_1d", "ret_5d", "volume", "avg_vol_30", "turnover", "sector_etf"}
        assert set(df.columns) == expected_cols
        assert df.index.name == "ticker"

    def test_idempotent_when_file_exists(self, mock_cfg, make_ohlcv_df, tmp_path):
        """Second call should not overwrite the file."""
        tickers = ["AAPL"]
        self._setup_ohlcv(mock_cfg, tickers, make_ohlcv_df)
        today_d = pd.bdate_range("2024-03-04", periods=10)[-1].date()

        returns_dir = Path(mock_cfg.system.data_dir_ssd) / "processed" / "returns"
        returns_dir.mkdir(parents=True, exist_ok=True)
        sentinel = returns_dir / f"{today_d.isoformat()}.parquet"
        sentinel.write_bytes(b"sentinel")  # Plant a fake file.

        with patch("yfinance.Ticker") as mock_ticker:
            mock_ticker.return_value.info = {}
            path = compute_and_write_returns(tickers, mock_cfg, today_d)

        assert path.read_bytes() == b"sentinel"  # Must not have been overwritten.

    def test_raises_data_error_when_no_rows(self, mock_cfg, today):
        """All tickers missing OHLCV → DataError."""
        with pytest.raises(DataError):
            compute_and_write_returns(["AAPL"], mock_cfg, today)
