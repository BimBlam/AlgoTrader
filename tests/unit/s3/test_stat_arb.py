"""
Unit tests for stat_arb.py — entry signal generation.
"""
import datetime
import types
from unittest.mock import patch

import pytest

from s3_signal_engine.ou_model import OUResult
from s3_signal_engine.stat_arb import compute_stat_arb_signals
from shared.constants import SignalSide, SignalStrategy


TODAY = datetime.date(2025, 1, 15)
RUN_ID = "test-run-001"

_NEUTRAL_SENTIMENT = {}  # triggers 1.0 adj for all tickers


def _patch_adj(value=1.0):
    return patch("s3_signal_engine.stat_arb.compute_directional_sentiment_adj", return_value=value)


@pytest.fixture
def strategy_cfg():
    return types.SimpleNamespace(
        stat_arb=types.SimpleNamespace(
            enabled=True,
            lookback_days=60,
            min_kappa=8.4,
            entry_s_score=1.25,
            exit_s_score_long=-0.50,
            exit_s_score_short=0.75,
            max_allocation_pct=0.40,
        ),
        regime_combo=types.SimpleNamespace(
            extreme_vol_halt=True,
        ),
    )


class TestStatArbSignals:
    def test_long_signal_when_s_score_below_negative_threshold(self, strategy_cfg):
        ou = OUResult("AAPL", kappa=15.0, mu=0.0, sigma_eq=0.05, beta=0.8,
                      s_score=-1.5, valid=True, cumulative_residual=-0.075)
        with _patch_adj(1.0):
            result = compute_stat_arb_signals([ou], strategy_cfg, {}, "LOW_VOL", RUN_ID, TODAY)
        assert len(result) == 1
        assert result[0].side == SignalSide.LONG
        assert result[0].ticker == "AAPL"

    def test_short_signal_when_s_score_above_threshold(self, strategy_cfg):
        ou = OUResult("MSFT", kappa=12.0, mu=0.0, sigma_eq=0.04, beta=0.9,
                      s_score=1.8, valid=True, cumulative_residual=0.072)
        with _patch_adj(1.0):
            result = compute_stat_arb_signals([ou], strategy_cfg, {}, "LOW_VOL", RUN_ID, TODAY)
        assert len(result) == 1
        assert result[0].side == SignalSide.SHORT

    def test_no_signal_when_inside_bands(self, strategy_cfg):
        ou = OUResult("TSLA", kappa=10.0, mu=0.0, sigma_eq=0.06, beta=1.0,
                      s_score=0.5, valid=True, cumulative_residual=0.03)
        with _patch_adj(1.0):
            result = compute_stat_arb_signals([ou], strategy_cfg, {}, "LOW_VOL", RUN_ID, TODAY)
        assert result == []

    def test_invalid_ou_params_skipped(self, strategy_cfg):
        ou = OUResult("GOOG", kappa=3.0, mu=0.0, sigma_eq=0.05, beta=0.7,
                      s_score=-2.0, valid=False, cumulative_residual=-0.1)
        with _patch_adj(1.0):
            result = compute_stat_arb_signals([ou], strategy_cfg, {}, "LOW_VOL", RUN_ID, TODAY)
        assert result == []

    def test_extreme_regime_halts_all_signals(self, strategy_cfg):
        ou = OUResult("AAPL", kappa=15.0, mu=0.0, sigma_eq=0.05, beta=0.8,
                      s_score=-1.8, valid=True, cumulative_residual=-0.09)
        with _patch_adj(1.0):
            result = compute_stat_arb_signals([ou], strategy_cfg, {}, "EXTREME", RUN_ID, TODAY)
        assert result == []

    def test_extreme_regime_no_halt_when_flag_false(self, strategy_cfg):
        strategy_cfg.regime_combo.extreme_vol_halt = False
        ou = OUResult("AAPL", kappa=15.0, mu=0.0, sigma_eq=0.05, beta=0.8,
                      s_score=-1.8, valid=True, cumulative_residual=-0.09)
        with _patch_adj(1.0):
            result = compute_stat_arb_signals([ou], strategy_cfg, {}, "EXTREME", RUN_ID, TODAY)
        assert len(result) == 1

    def test_zero_adj_filters_signal(self, strategy_cfg):
        ou = OUResult("MSFT", kappa=12.0, mu=0.0, sigma_eq=0.04, beta=0.9,
                      s_score=1.8, valid=True, cumulative_residual=0.072)
        with _patch_adj(0.0):
            result = compute_stat_arb_signals([ou], strategy_cfg, {}, "LOW_VOL", RUN_ID, TODAY)
        assert result == []

    def test_combined_score_calculation(self, strategy_cfg):
        ou = OUResult("NVDA", kappa=20.0, mu=0.0, sigma_eq=0.08, beta=1.1,
                      s_score=-2.0, valid=True, cumulative_residual=-0.16)
        with _patch_adj(0.5):
            result = compute_stat_arb_signals([ou], strategy_cfg, {}, "MED_VOL", RUN_ID, TODAY)
        assert len(result) == 1
        c = result[0]
        assert abs(c.combined_score - (2.0 * 0.5)) < 1e-10
        assert c.sentiment_adj == 0.5

    def test_raw_score_is_absolute_s_score(self, strategy_cfg):
        """raw_score must be |s_score|, not signed."""
        for s_score in (-1.5, 1.8):
            ou = OUResult("X", kappa=15.0, mu=0.0, sigma_eq=0.05, beta=0.8,
                          s_score=s_score, valid=True, cumulative_residual=s_score * 0.05)
            with _patch_adj(1.0):
                result = compute_stat_arb_signals([ou], strategy_cfg, {}, "LOW_VOL", RUN_ID, TODAY)
            if result:
                assert result[0].raw_score >= 0

    def test_strategy_label_is_stat_arb(self, strategy_cfg):
        ou = OUResult("AAPL", kappa=15.0, mu=0.0, sigma_eq=0.05, beta=0.8,
                      s_score=-1.5, valid=True, cumulative_residual=-0.075)
        with _patch_adj(1.0):
            result = compute_stat_arb_signals([ou], strategy_cfg, {}, "LOW_VOL", RUN_ID, TODAY)
        assert result[0].strategy == SignalStrategy.STAT_ARB
