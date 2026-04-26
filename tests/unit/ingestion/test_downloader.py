"""Tests for OHLCV download + normalisation logic."""

from __future__ import annotations

import datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from algotrader.ingestion.downloader import (
    _determine_fetch_start,
    _load_existing,
    _normalise,
    download_and_persist_ohlcv,
)
from algotrader.shared.exceptions import DataError


def _raw_df(n: int = 3) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-02", periods=n)
    return pd.DataFrame(
        {"Open": [100.0] * n, "High": [101.0] * n, "Low": [99.0] * n,
         "Close": [100.5] * n, "Volume": [500_000] * n},
        index=dates,
    )


class TestNormalise:
    def test_column_names_match_schema(self):
        df = _normalise(_raw_df())
        assert set(df.columns) == {"open", "high", "low", "close", "volume", "adj_close"}

    def test_adj_close_equals_close(self):
        df = _normalise(_raw_df())
        pd.testing.assert_series_equal(df["close"], df["adj_close"], check_names=False)

    def test_volume_is_int64(self):
        assert _normalise(_raw_df())["volume"].dtype == "int64"

    def test_price_columns_are_float64(self):
        df = _normalise(_raw_df())
        for col in ("open", "high", "low", "close", "adj_close"):
            assert df[col].dtype == "float64", f"{col} should be float64"

    def test_index_name_is_date(self):
        assert _normalise(_raw_df()).index.name == "date"

    def test_multiindex_columns_flattened(self):
        raw = _raw_df()
        raw.columns = pd.MultiIndex.from_tuples(
            [(c, "AAPL") for c in raw.columns]
        )
        df = _normalise(raw)
        assert isinstance(df.columns, pd.Index) and not isinstance(df.columns, pd.MultiIndex)


class TestFetchStart:
    def test_cold_start_is_730_days_back(self):
        today = datetime.date(2024, 6, 1)
        empty = pd.DataFrame(columns=["open"])
        start = _determine_fetch_start(empty, today)
        assert start == today - datetime.timedelta(days=730)

    def test_warm_start_overlaps_5_days(self):
        today = datetime.date(2024, 6, 1)
        last = datetime.date(2024, 5, 28)
        df = pd.DataFrame({"close": [100.0]}, index=pd.to_datetime([last]))
        start = _determine_fetch_start(df, today)
        assert start == last - datetime.timedelta(days=5)


class TestLoadExisting:
    def test_returns_empty_if_no_file(self, tmp_path):
        df = _load_existing(tmp_path / "NONEXISTENT.parquet")
        assert df.empty

    def test_loads_existing_parquet(self, tmp_path, make_ohlcv_df):
        path = tmp_path / "AAPL.parquet"
        make_ohlcv_df(5).to_parquet(path)
        df = _load_existing(path)
        assert len(df) == 5


class TestDownloadAndPersist:
    def test_raises_data_error_on_empty_yfinance_response(self, mock_cfg, today):
        with patch("yfinance.download", return_value=pd.DataFrame()), pytest.raises(DataError, match="no data"):
            download_and_persist_ohlcv("AAPL", mock_cfg, today)

    def test_appends_new_rows_without_duplicate(self, mock_cfg, make_ohlcv_df, today):
        ohlcv_dir = Path(mock_cfg.system.data_dir_ssd) / "processed" / "ohlcv"
        ohlcv_dir.mkdir(parents=True, exist_ok=True)

        existing = make_ohlcv_df(5, start="2024-01-02")
        existing.to_parquet(ohlcv_dir / "AAPL.parquet")

        # Simulate yfinance returning 3 new days (overlap + 2 genuinely new).
        new_raw = make_ohlcv_df(3, start="2024-01-08")
        raw_yf = new_raw.rename(columns={
            "open": "Open", "high": "High", "low": "Low",
            "close": "Close", "volume": "Volume",
        })[["Open", "High", "Low", "Close", "Volume"]]

        with patch("yfinance.download", return_value=raw_yf):
            combined = download_and_persist_ohlcv("AAPL", mock_cfg, today)

        # No duplicate dates.
        assert combined.index.is_unique

    def test_creates_parquet_file(self, mock_cfg, today):
        raw_yf = pd.DataFrame(
            {"Open": [100.0], "High": [101.0], "Low": [99.0],
             "Close": [100.5], "Volume": [500_000]},
            index=pd.to_datetime(["2024-03-15"]),
        )
        with patch("yfinance.download", return_value=raw_yf):
            download_and_persist_ohlcv("AAPL", mock_cfg, today)

        parquet_path = (
            Path(mock_cfg.system.data_dir_ssd) / "processed" / "ohlcv" / "AAPL.parquet"
        )
        assert parquet_path.exists()
