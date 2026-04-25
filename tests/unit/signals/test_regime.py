"""
Unit tests for regime.py — VIX regime classification.
"""
import datetime
import types

import pandas as pd

from algotrader.signals.regime import classify_regime, _parse_vix


TODAY = datetime.date(2025, 1, 15)


def _make_vix_df(closes: list[float], start="2024-06-01"):
    dates = pd.date_range(start, periods=len(closes), freq="B")
    return pd.DataFrame({"close": closes, "adj_close": closes}, index=dates)


def _make_cfg(tmp_path, vix_sma_lookback=50):
    return types.SimpleNamespace(
        system=types.SimpleNamespace(data_dir_ssd=str(tmp_path)),
        strategy_params=types.SimpleNamespace(
            regime_combo=types.SimpleNamespace(
                vix_sma_lookback=vix_sma_lookback,
            )
        ),
    )


class TestClassifyRegime:
    def test_low_vol_when_vix_below_sma(self, tmp_path):
        # SMA ≈ 20, today = 18 → LOW_VOL
        closes = [20.0] * 49 + [18.0]
        df = _make_vix_df(closes)
        ohlcv_dir = tmp_path / "processed" / "ohlcv"
        ohlcv_dir.mkdir(parents=True)
        df.to_parquet(ohlcv_dir / "VIX.parquet")

        cfg = _make_cfg(tmp_path)
        result = classify_regime(TODAY, cfg)
        assert result == "LOW_VOL"

    def test_med_vol_when_vix_slightly_above_sma(self, tmp_path):
        # SMA ≈ 20, today = 21 → MED_VOL (< 20 * 1.20 = 24)
        closes = [20.0] * 49 + [21.0]
        df = _make_vix_df(closes)
        ohlcv_dir = tmp_path / "processed" / "ohlcv"
        ohlcv_dir.mkdir(parents=True)
        df.to_parquet(ohlcv_dir / "VIX.parquet")

        cfg = _make_cfg(tmp_path)
        result = classify_regime(TODAY, cfg)
        assert result == "MED_VOL"

    def test_high_vol_when_vix_significantly_above_sma(self, tmp_path):
        # SMA ≈ 20, today = 26 → HIGH_VOL (>= 24, < 30)
        closes = [20.0] * 49 + [26.0]
        df = _make_vix_df(closes)
        ohlcv_dir = tmp_path / "processed" / "ohlcv"
        ohlcv_dir.mkdir(parents=True)
        df.to_parquet(ohlcv_dir / "VIX.parquet")

        cfg = _make_cfg(tmp_path)
        result = classify_regime(TODAY, cfg)
        assert result == "HIGH_VOL"

    def test_extreme_when_vix_far_above_sma(self, tmp_path):
        # SMA ≈ 20, today = 35 → EXTREME (>= 30)
        closes = [20.0] * 49 + [35.0]
        df = _make_vix_df(closes)
        ohlcv_dir = tmp_path / "processed" / "ohlcv"
        ohlcv_dir.mkdir(parents=True)
        df.to_parquet(ohlcv_dir / "VIX.parquet")

        cfg = _make_cfg(tmp_path)
        result = classify_regime(TODAY, cfg)
        assert result == "EXTREME"

    def test_defaults_to_med_vol_when_vix_missing(self, tmp_path):
        cfg = _make_cfg(tmp_path)
        result = classify_regime(TODAY, cfg)
        assert result == "MED_VOL"

    def test_boundary_exactly_at_sma_is_med_vol(self, tmp_path):
        # VIX exactly equals SMA → not LOW_VOL (< SMA required for LOW_VOL)
        closes = [20.0] * 50
        df = _make_vix_df(closes)
        ohlcv_dir = tmp_path / "processed" / "ohlcv"
        ohlcv_dir.mkdir(parents=True)
        df.to_parquet(ohlcv_dir / "VIX.parquet")

        cfg = _make_cfg(tmp_path)
        result = classify_regime(TODAY, cfg)
        assert result == "MED_VOL"


class TestParseVix:
    def test_returns_none_on_empty_df(self, tmp_path):
        df = pd.DataFrame({"close": []}, index=pd.DatetimeIndex([]))
        path = tmp_path / "VIX.parquet"
        df.to_parquet(path)
        close, sma = _parse_vix(path, TODAY, 50)
        assert close is None
        assert sma is None

    def test_returns_today_close_correctly(self, tmp_path):
        closes = [15.0] * 9 + [18.0]  # last close = 18
        df = _make_vix_df(closes, start="2025-01-01")
        # Align so today matches the last business day
        path = tmp_path / "VIX.parquet"
        df.to_parquet(path)
        close, sma = _parse_vix(path, df.index[-1].date(), 10)
        assert close is not None
        assert abs(close - 18.0) < 1e-9
