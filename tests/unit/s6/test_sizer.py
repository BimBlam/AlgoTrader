"""tests/unit/s6/test_sizer.py"""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from shared.exceptions import DataError
from s6_execution.sizer import compute_atr, compute_position_size


def _make_ohlcv(n: int, high_base: float = 105.0, low_base: float = 95.0, close_base: float = 100.0) -> pd.DataFrame:
    """Create a synthetic OHLCV DataFrame with *n* rows."""
    return pd.DataFrame(
        {
            "open":      [close_base] * n,
            "high":      [high_base] * n,
            "low":       [low_base] * n,
            "close":     [close_base] * n,
            "adj_close": [close_base] * n,
            "volume":    [1_000_000] * n,
        }
    )


# ── compute_atr ───────────────────────────────────────────────────────────────

class TestComputeATR:
    def test_known_constant_series(self):
        # high=105, low=95, close=100 → TR = max(10, 5, 5) = 10 every row
        df = _make_ohlcv(20)
        atr = compute_atr(df, lookback_days=14)
        assert atr == pytest.approx(10.0, rel=1e-6)

    def test_raises_insufficient_history(self):
        df = _make_ohlcv(10)
        with pytest.raises(DataError, match="Insufficient OHLCV history"):
            compute_atr(df, lookback_days=14)

    def test_requires_lookback_plus_one_rows(self):
        # Exactly lookback+1 rows should work
        df = _make_ohlcv(15)
        atr = compute_atr(df, lookback_days=14)
        assert atr > 0

    def test_raises_on_zero_atr(self):
        # Degenerate series: all prices identical → True Range = 0
        df = pd.DataFrame(
            {
                "open":      [100.0] * 20,
                "high":      [100.0] * 20,
                "low":       [100.0] * 20,
                "close":     [100.0] * 20,
                "adj_close": [100.0] * 20,
                "volume":    [0] * 20,
            }
        )
        with pytest.raises(DataError, match="non-positive or NaN"):
            compute_atr(df, lookback_days=14)


# ── compute_position_size ─────────────────────────────────────────────────────

class TestComputePositionSize:
    def _make_mock_cfg(self, data_dir="data/", lookback=14, kelly=0.25, max_pos=5000.0):
        return SimpleNamespace(
            system=SimpleNamespace(data_dir_ssd=data_dir),
            risk=SimpleNamespace(
                atr_lookback_days=lookback,
                kelly_fraction=kelly,
                max_position_usd=max_pos,
            ),
        )

    def test_basic_sizing(self, tmp_path, sample_signal):
        # ATR = 10, account_equity = 100_000, kelly = 0.25
        # dollar_risk = 25_000, base_qty = floor(25000/10) = 2500
        # sentiment_adj = 1.0 → adj_qty = 2500
        # target_usd = 2500 * 100.0 = 250_000 (before clipping)
        df = _make_ohlcv(20)
        ohlcv_dir = tmp_path / "processed" / "ohlcv"
        ohlcv_dir.mkdir(parents=True)
        df.to_parquet(ohlcv_dir / "AAPL.parquet", engine="pyarrow")

        cfg = self._make_mock_cfg(data_dir=str(tmp_path))
        target_usd, qty = compute_position_size(
            sample_signal, cfg, account_equity=100_000.0, limit_price=100.0
        )
        assert qty == 2500
        assert target_usd == pytest.approx(250_000.0)

    def test_sentiment_adj_halves_quantity(self, tmp_path, sample_signal):
        sample_signal.sentiment_adj = 0.5
        df = _make_ohlcv(20)
        ohlcv_dir = tmp_path / "processed" / "ohlcv"
        ohlcv_dir.mkdir(parents=True)
        df.to_parquet(ohlcv_dir / "AAPL.parquet", engine="pyarrow")

        cfg = self._make_mock_cfg(data_dir=str(tmp_path))
        _, qty = compute_position_size(
            sample_signal, cfg, account_equity=100_000.0, limit_price=100.0
        )
        # base=2500 * 0.5 = 1250
        assert qty == 1250

    def test_raises_when_sentiment_adj_is_zero(self, tmp_path, sample_signal):
        sample_signal.sentiment_adj = 0.0
        df = _make_ohlcv(20)
        ohlcv_dir = tmp_path / "processed" / "ohlcv"
        ohlcv_dir.mkdir(parents=True)
        df.to_parquet(ohlcv_dir / "AAPL.parquet", engine="pyarrow")

        cfg = self._make_mock_cfg(data_dir=str(tmp_path))
        with pytest.raises(DataError, match="quantity=0"):
            compute_position_size(
                sample_signal, cfg, account_equity=100_000.0, limit_price=100.0
            )

    def test_raises_when_parquet_missing(self, tmp_path, sample_signal):
        cfg = self._make_mock_cfg(data_dir=str(tmp_path))
        with pytest.raises(DataError, match="OHLCV parquet not found"):
            compute_position_size(
                sample_signal, cfg, account_equity=100_000.0, limit_price=100.0
            )

    def test_raises_when_account_equity_too_low(self, tmp_path, sample_signal):
        # ATR=10, equity=0 → dollar_risk=0, base_qty=0
        df = _make_ohlcv(20)
        ohlcv_dir = tmp_path / "processed" / "ohlcv"
        ohlcv_dir.mkdir(parents=True)
        df.to_parquet(ohlcv_dir / "AAPL.parquet", engine="pyarrow")

        cfg = self._make_mock_cfg(data_dir=str(tmp_path))
        with pytest.raises(DataError, match="Base quantity=0"):
            compute_position_size(
                sample_signal, cfg, account_equity=0.0, limit_price=100.0
            )
