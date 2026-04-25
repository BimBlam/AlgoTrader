"""
Unit tests for reversal.py — cross-sectional reversal signals.
"""
import datetime
import types
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from algotrader.signals.reversal import compute_reversal_signals
from algotrader.shared.constants import SignalSide, SignalStrategy


TODAY = datetime.date(2025, 1, 15)
RUN_ID = "test-run-002"


def _patch_adj(value=1.0):
    return patch("algotrader.signals.reversal.compute_directional_sentiment_adj", return_value=value)


@pytest.fixture
def strategy_cfg():
    return types.SimpleNamespace(
        reversal=types.SimpleNamespace(
            enabled=True,
            lookback_days=1,
            long_decile=0.10,
            short_decile=0.90,
            turnover_split=False,
            max_allocation_pct=0.30,
        ),
    )


@pytest.fixture
def returns_df():
    """20 tickers with predictable ranking."""
    n = 20
    rng = np.random.default_rng(1)
    # Deliberately spread returns so bottom/top decile are clear
    ret = np.linspace(-0.05, 0.05, n)
    np.random.shuffle(ret)  # shuffle so tickers aren't alphabetically sorted by return
    tickers = [f"T{i:02d}" for i in range(n)]
    return pd.DataFrame(
        {
            "ret_1d": ret,
            "ret_5d": rng.normal(0, 0.02, n),
            "volume": rng.integers(1_000_000, 10_000_000, n),
            "avg_vol_30": rng.integers(500_000, 5_000_000, n).astype(float),
            "turnover": rng.uniform(0.001, 0.05, n),
            "sector_etf": ["XLK"] * n,
        },
        index=tickers,
    )


class TestReversalSignals:
    def test_bottom_decile_get_long(self, strategy_cfg, returns_df):
        with _patch_adj(1.0):
            signals = compute_reversal_signals(returns_df, strategy_cfg, {}, "LOW_VOL", RUN_ID, TODAY)
        long_signals = [s for s in signals if s.side == SignalSide.LONG]
        assert len(long_signals) > 0
        # All LONG tickers should come from the bottom 10% by ret_1d
        long_tickers = {s.ticker for s in long_signals}
        ranked = returns_df["ret_1d"].rank(pct=True)
        for ticker in long_tickers:
            assert ranked[ticker] <= 0.10 + 1e-9  # rank ≤ long_decile

    def test_top_decile_get_short(self, strategy_cfg, returns_df):
        with _patch_adj(1.0):
            signals = compute_reversal_signals(returns_df, strategy_cfg, {}, "LOW_VOL", RUN_ID, TODAY)
        short_signals = [s for s in signals if s.side == SignalSide.SHORT]
        assert len(short_signals) > 0
        ranked = returns_df["ret_1d"].rank(pct=True)
        short_tickers = {s.ticker for s in short_signals}
        for ticker in short_tickers:
            assert ranked[ticker] >= 0.90 - 1e-9

    def test_extreme_regime_halts(self, strategy_cfg, returns_df):
        with _patch_adj(1.0):
            signals = compute_reversal_signals(returns_df, strategy_cfg, {}, "EXTREME", RUN_ID, TODAY)
        assert signals == []

    def test_extreme_no_halt_when_flag_false(self, strategy_cfg, returns_df):
        with _patch_adj(1.0):
            signals = compute_reversal_signals(returns_df, strategy_cfg, {}, "EXTREME", RUN_ID, TODAY,
                                                 extreme_vol_halt=False)
        assert len(signals) > 0

    def test_zero_volume_tickers_excluded(self, strategy_cfg, returns_df):
        returns_df_copy = returns_df.copy()
        # Zero out avg_vol_30 for all tickers
        returns_df_copy["avg_vol_30"] = 0.0
        with _patch_adj(1.0):
            signals = compute_reversal_signals(returns_df_copy, strategy_cfg, {}, "LOW_VOL", RUN_ID, TODAY)
        assert signals == []

    def test_turnover_split_produces_signals_from_both_buckets(self, strategy_cfg, returns_df):
        strategy_cfg.reversal.turnover_split = True
        with _patch_adj(1.0):
            signals = compute_reversal_signals(returns_df, strategy_cfg, {}, "LOW_VOL", RUN_ID, TODAY)
        # With 20 tickers, each bucket has ~10 tickers → both should yield signals
        assert len(signals) >= 2

    def test_raw_score_in_zero_one_range(self, strategy_cfg, returns_df):
        with _patch_adj(1.0):
            signals = compute_reversal_signals(returns_df, strategy_cfg, {}, "LOW_VOL", RUN_ID, TODAY)
        for s in signals:
            assert 0.0 <= s.raw_score <= 1.0 + 1e-9

    def test_strategy_label_is_reversal(self, strategy_cfg, returns_df):
        with _patch_adj(1.0):
            signals = compute_reversal_signals(returns_df, strategy_cfg, {}, "LOW_VOL", RUN_ID, TODAY)
        for s in signals:
            assert s.strategy == SignalStrategy.REVERSAL

    def test_zero_adj_filters_signals(self, strategy_cfg, returns_df):
        with _patch_adj(0.0):
            signals = compute_reversal_signals(returns_df, strategy_cfg, {}, "LOW_VOL", RUN_ID, TODAY)
        assert signals == []
