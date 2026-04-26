"""
Unit tests for loaders.py — I/O layer for S3.
"""
import datetime
import types
from unittest.mock import MagicMock

import pandas as pd
import pytest

from algotrader.shared.exceptions import DataError
from algotrader.signals.loaders import (
    load_prior_ou_params,
    load_returns,
    load_sentiment_scores,
)

TODAY = datetime.date(2025, 1, 15)


def _make_cfg(tmp_path):
    return types.SimpleNamespace(
        system=types.SimpleNamespace(data_dir_ssd=str(tmp_path))
    )


def _make_returns_df(tickers=None):
    tickers = tickers or ["AAPL", "MSFT"]
    n = len(tickers)
    return pd.DataFrame(
        {
            "ret_1d": [0.01] * n,
            "ret_5d": [0.02] * n,
            "volume": [1_000_000] * n,
            "avg_vol_30": [500_000.0] * n,
            "turnover": [0.01] * n,
            "sector_etf": ["XLK"] * n,
        },
        index=tickers,
    )


class TestLoadReturns:
    def test_loads_parquet_successfully(self, tmp_path):
        df = _make_returns_df()
        parquet_dir = tmp_path / "processed" / "returns"
        parquet_dir.mkdir(parents=True)
        df.to_parquet(parquet_dir / f"{TODAY}.parquet")

        result = load_returns(TODAY, _make_cfg(tmp_path))
        assert list(result.index) == ["AAPL", "MSFT"]

    def test_raises_data_error_on_missing_file(self, tmp_path):
        with pytest.raises(DataError, match="not found"):
            load_returns(TODAY, _make_cfg(tmp_path))

    def test_raises_data_error_on_missing_columns(self, tmp_path):
        df = pd.DataFrame({"ret_1d": [0.01]}, index=["AAPL"])
        parquet_dir = tmp_path / "processed" / "returns"
        parquet_dir.mkdir(parents=True)
        df.to_parquet(parquet_dir / f"{TODAY}.parquet")

        with pytest.raises(DataError, match="missing columns"):
            load_returns(TODAY, _make_cfg(tmp_path))

    def test_raises_data_error_on_empty_file(self, tmp_path):
        df = pd.DataFrame(
            {c: [] for c in ["ret_1d", "ret_5d", "volume", "avg_vol_30", "turnover", "sector_etf"]}
        )
        parquet_dir = tmp_path / "processed" / "returns"
        parquet_dir.mkdir(parents=True)
        df.to_parquet(parquet_dir / f"{TODAY}.parquet")

        with pytest.raises(DataError, match="no rows"):
            load_returns(TODAY, _make_cfg(tmp_path))

    def test_tickers_uppercased(self, tmp_path):
        df = _make_returns_df(["aapl", "msft"])
        parquet_dir = tmp_path / "processed" / "returns"
        parquet_dir.mkdir(parents=True)
        df.to_parquet(parquet_dir / f"{TODAY}.parquet")

        result = load_returns(TODAY, _make_cfg(tmp_path))
        assert all(t == t.upper() for t in result.index)


class TestLoadPriorOUParams:
    def test_returns_empty_dict_on_no_rows(self):
        session = MagicMock()
        session.scalars.return_value.all.return_value = []
        result = load_prior_ou_params(session, TODAY)
        assert result == {}

    def test_returns_most_recent_per_ticker(self):
        session = MagicMock()
        row1 = MagicMock()
        row1.ticker = "AAPL"
        row1.date = datetime.date(2025, 1, 14)
        row1.kappa = 12.0
        row1.mu = 0.01
        row1.sigma_eq = 0.05
        row1.beta = 0.8

        row2 = MagicMock()
        row2.ticker = "AAPL"
        row2.date = datetime.date(2025, 1, 13)
        row2.kappa = 10.0
        row2.mu = 0.00
        row2.sigma_eq = 0.04
        row2.beta = 0.7

        session.scalars.return_value.all.return_value = [row1, row2]
        result = load_prior_ou_params(session, TODAY)
        assert "AAPL" in result
        assert result["AAPL"]["kappa"] == 12.0  # most recent wins

    def test_deduplicates_tickers(self):
        session = MagicMock()
        rows = []
        for date in [datetime.date(2025, 1, 14), datetime.date(2025, 1, 13)]:
            r = MagicMock()
            r.ticker = "MSFT"
            r.date = date
            r.kappa = 11.0
            r.mu = 0.0
            r.sigma_eq = 0.05
            r.beta = 0.9
            rows.append(r)
        session.scalars.return_value.all.return_value = rows
        result = load_prior_ou_params(session, TODAY)
        assert len(result) == 1  # deduplicated


class TestLoadSentimentScores:
    def test_returns_empty_dict_on_no_rows(self):
        session = MagicMock()
        session.scalars.return_value.all.return_value = []
        result = load_sentiment_scores(session, TODAY)
        assert result == {}

    def test_maps_ticker_to_fields(self):
        session = MagicMock()
        row = MagicMock()
        row.ticker = "AAPL"
        row.sentiment_res = 0.25
        row.abn_attention = 1.5
        row.model_used = "finbert"
        session.scalars.return_value.all.return_value = [row]

        result = load_sentiment_scores(session, TODAY)
        assert "AAPL" in result
        assert result["AAPL"]["sentiment_res"] == 0.25
        assert result["AAPL"]["model_used"] == "finbert"
