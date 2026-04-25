"""
Unit tests for config_schema.py — pydantic v2 validation.
"""
import pytest
from pydantic import ValidationError

from s3_signal_engine.config_schema import (
    StatArbConfig,
    ReversalConfig,
    RegimeComboConfig,
    StrategyParamsConfig,
)


class TestStatArbConfig:
    def test_valid_config_parses(self):
        cfg = StatArbConfig(
            enabled=True,
            lookback_days=60,
            min_kappa=8.4,
            entry_s_score=1.25,
            exit_s_score_long=-0.50,
            exit_s_score_short=0.75,
            max_allocation_pct=0.40,
        )
        assert cfg.min_kappa == 8.4

    def test_lookback_below_minimum_raises(self):
        with pytest.raises(ValidationError):
            StatArbConfig(
                enabled=True, lookback_days=5, min_kappa=8.4,
                entry_s_score=1.25, exit_s_score_long=-0.5,
                exit_s_score_short=0.75, max_allocation_pct=0.40,
            )

    def test_allocation_pct_above_one_raises(self):
        with pytest.raises(ValidationError):
            StatArbConfig(
                enabled=True, lookback_days=60, min_kappa=8.4,
                entry_s_score=1.25, exit_s_score_long=-0.5,
                exit_s_score_short=0.75, max_allocation_pct=1.5,
            )


class TestReversalConfig:
    def test_valid_config_parses(self):
        cfg = ReversalConfig(
            enabled=True, lookback_days=1,
            long_decile=0.10, short_decile=0.90,
            turnover_split=True, max_allocation_pct=0.30,
        )
        assert cfg.turnover_split is True

    def test_short_decile_must_be_above_long_decile(self):
        with pytest.raises(ValidationError):
            ReversalConfig(
                enabled=True, lookback_days=1,
                long_decile=0.50, short_decile=0.40,
                turnover_split=True, max_allocation_pct=0.30,
            )

    def test_long_decile_above_half_raises(self):
        with pytest.raises(ValidationError):
            ReversalConfig(
                enabled=True, lookback_days=1,
                long_decile=0.60, short_decile=0.90,
                turnover_split=True, max_allocation_pct=0.30,
            )


class TestRegimeComboConfig:
    def test_valid_config_parses(self):
        cfg = RegimeComboConfig(
            enabled=True,
            vix_sma_lookback=50,
            low_vol_strategy="stat_arb",
            med_vol_strategy="reversal",
            high_vol_reduce_pct=0.50,
            extreme_vol_halt=True,
            max_allocation_pct=0.30,
        )
        assert cfg.vix_sma_lookback == 50

    def test_high_vol_reduce_above_one_raises(self):
        with pytest.raises(ValidationError):
            RegimeComboConfig(
                enabled=True, vix_sma_lookback=50,
                low_vol_strategy="stat_arb", med_vol_strategy="reversal",
                high_vol_reduce_pct=1.5, extreme_vol_halt=True,
                max_allocation_pct=0.30,
            )


class TestStrategyParamsConfig:
    def test_full_config_parses(self):
        cfg = StrategyParamsConfig(
            stat_arb=StatArbConfig(
                enabled=True, lookback_days=60, min_kappa=8.4,
                entry_s_score=1.25, exit_s_score_long=-0.5,
                exit_s_score_short=0.75, max_allocation_pct=0.40,
            ),
            reversal=ReversalConfig(
                enabled=True, lookback_days=1, long_decile=0.10,
                short_decile=0.90, turnover_split=True, max_allocation_pct=0.30,
            ),
            regime_combo=RegimeComboConfig(
                enabled=True, vix_sma_lookback=50, low_vol_strategy="stat_arb",
                med_vol_strategy="reversal", high_vol_reduce_pct=0.50,
                extreme_vol_halt=True, max_allocation_pct=0.30,
            ),
        )
        assert cfg.stat_arb.entry_s_score == 1.25
