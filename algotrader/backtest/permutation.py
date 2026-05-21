"""
algotrader.backtest/permutation.py

Permutation test battery:
  1. Circular shift  – shift all date labels by a random offset
  2. Sign flip       – randomly flip sign of each return
  3. Jitter ±2 bars  – shift the IS/OOS split boundary by ±2 days
  4. Noise injection – add N(0, σ_ret) noise to every return
  5. Parameter stab  – ±10 % perturbation of reversal decile thresholds

Each test produces a p-value: fraction of permutations whose Sharpe ≥
the observed Sharpe.  A small p-value means the edge is hard to replicate
by chance under that specific null.

Changes from audit:
  - _circular_shift_test fixed: after remapping dates, the shifted DataFrame
    is split on its OWN sorted date range (first-half IS / second-half OOS),
    not on the original IS/OOS date sets. Using the original sets produced
    empty DataFrames because the shifted dates no longer matched.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from algotrader.backtest.costs import TransactionCostModel
from algotrader.backtest.metrics import sharpe_ratio
from algotrader.backtest.strategy_sim import simulate_strategy
from algotrader.shared.logger import get_logger

log = get_logger(__name__)

_N_PERMUTATIONS = 200


@dataclass
class PermutationResult:
    p_values: dict[str, float] = field(default_factory=dict)


def run_permutation_battery(
    returns_df: pd.DataFrame,
    cfg,
    cost_model: TransactionCostModel,
) -> PermutationResult:
    """
    Run the full permutation test battery and return a p-value for each test.

    Parameters
    ----------
    returns_df : MultiIndex (date, ticker) DataFrame
    cfg        : AppConfig
    cost_model : TransactionCostModel
    """
    n_perms: int = getattr(cfg.backtest, "n_permutations", _N_PERMUTATIONS)
    rng = np.random.default_rng(
        seed=getattr(cfg.backtest, "random_seed", 42) + 2
    )

    dates = sorted(returns_df.index.get_level_values("date").unique())
    split_idx = len(dates) * 3 // 4
    is_set   = set(dates[:split_idx])
    oos_set  = set(dates[split_idx:])
    is_df    = returns_df[returns_df.index.get_level_values("date").isin(is_set)]
    oos_df   = returns_df[returns_df.index.get_level_values("date").isin(oos_set)]

    base_ret = simulate_strategy(is_df, oos_df, cfg, cost_model)
    observed_sharpe = sharpe_ratio(base_ret) if base_ret is not None else 0.0

    result = PermutationResult()
    result.p_values["circular_shift"] = _circular_shift_test(
        returns_df, dates, split_idx, cfg, cost_model,
        observed_sharpe, n_perms, rng,
    )
    result.p_values["sign_flip"] = _sign_flip_test(
        returns_df, is_df, oos_df, cfg, cost_model,
        observed_sharpe, n_perms, rng,
    )
    result.p_values["jitter"] = _jitter_test(
        returns_df, dates, split_idx, cfg, cost_model,
        observed_sharpe, n_perms, rng,
    )
    result.p_values["noise_injection"] = _noise_injection_test(
        returns_df, is_df, oos_df, cfg, cost_model,
        observed_sharpe, n_perms, rng,
    )
    result.p_values["parameter_stability"] = _parameter_stability_test(
        returns_df, dates, split_idx, cfg, cost_model,
        observed_sharpe, n_perms, rng,
    )
    log.info("permutation_battery_complete", p_values=result.p_values)
    return result


# ---------------------------------------------------------------------------
# Individual test implementations
# ---------------------------------------------------------------------------

def _circular_shift_test(
    returns_df, dates, split_idx, cfg, cost_model,
    observed_sharpe, n_perms, rng,
) -> float:
    """
    Randomly shift all date labels by a circular offset, destroying the
    timing relationship between signals and returns.

    After remapping, the shifted DataFrame is split on its own first/second
    half (not the original IS/OOS partition) so IS and OOS are never empty.
    """
    n = len(dates)
    beat = 0
    for _ in range(n_perms):
        shift = int(rng.integers(1, n))
        shifted_dates = dates[shift:] + dates[:shift]
        date_map = dict(zip(dates, shifted_dates, strict=True))
        shifted_df = _remap_dates(returns_df, date_map)

        # Split on the shifted df\'s own sorted date range
        shifted_sorted = sorted(shifted_df.index.get_level_values("date").unique())
        s_split = len(shifted_sorted) * 3 // 4
        s_is_set  = set(shifted_sorted[:s_split])
        s_oos_set = set(shifted_sorted[s_split:])
        s_is  = shifted_df[shifted_df.index.get_level_values("date").isin(s_is_set)]
        s_oos = shifted_df[shifted_df.index.get_level_values("date").isin(s_oos_set)]

        if s_is.empty or s_oos.empty:
            continue
        ret = simulate_strategy(s_is, s_oos, cfg, cost_model)
        if ret is not None and sharpe_ratio(ret) >= observed_sharpe:
            beat += 1
    return beat / n_perms


def _sign_flip_test(
    returns_df, is_df, oos_df, cfg, cost_model,
    observed_sharpe, n_perms, rng,
) -> float:
    """Randomly flip sign of ret1d for each ticker-day."""
    beat = 0
    for _ in range(n_perms):
        flipped = returns_df.copy()
        signs = rng.choice([-1.0, 1.0], size=len(flipped))
        flipped["ret1d"] = flipped["ret1d"] * signs
        f_is  = flipped[flipped.index.get_level_values("date").isin(
            set(is_df.index.get_level_values("date")))]
        f_oos = flipped[flipped.index.get_level_values("date").isin(
            set(oos_df.index.get_level_values("date")))]
        ret = simulate_strategy(f_is, f_oos, cfg, cost_model)
        if ret is not None and sharpe_ratio(ret) >= observed_sharpe:
            beat += 1
    return beat / n_perms


def _jitter_test(
    returns_df, dates, split_idx, cfg, cost_model,
    observed_sharpe, n_perms, rng,
) -> float:
    """Shift the IS/OOS split boundary by ±2 bars."""
    n = len(dates)
    beat = 0
    for _ in range(n_perms):
        offset = int(rng.integers(-2, 3))
        jitter_split = max(5, min(n - 5, split_idx + offset))
        is_set  = set(dates[:jitter_split])
        oos_set = set(dates[jitter_split:])
        j_is  = returns_df[returns_df.index.get_level_values("date").isin(is_set)]
        j_oos = returns_df[returns_df.index.get_level_values("date").isin(oos_set)]
        ret = simulate_strategy(j_is, j_oos, cfg, cost_model)
        if ret is not None and sharpe_ratio(ret) >= observed_sharpe:
            beat += 1
    return beat / n_perms


def _noise_injection_test(
    returns_df, is_df, oos_df, cfg, cost_model,
    observed_sharpe, n_perms, rng,
) -> float:
    """Add IID N(0, σ_ret) noise to all returns."""
    sigma = float(returns_df["ret1d"].std())
    beat = 0
    for _ in range(n_perms):
        noisy = returns_df.copy()
        noisy["ret1d"] = noisy["ret1d"] + rng.normal(0, sigma, size=len(noisy))
        n_is  = noisy[noisy.index.get_level_values("date").isin(
            set(is_df.index.get_level_values("date")))]
        n_oos = noisy[noisy.index.get_level_values("date").isin(
            set(oos_df.index.get_level_values("date")))]
        ret = simulate_strategy(n_is, n_oos, cfg, cost_model)
        if ret is not None and sharpe_ratio(ret) >= observed_sharpe:
            beat += 1
    return beat / n_perms


def _parameter_stability_test(
    returns_df, dates, split_idx, cfg, cost_model,
    observed_sharpe, n_perms, rng,
) -> float:
    """Perturb reversal decile thresholds by ±10 % and measure Sharpe stability."""
    is_set  = set(dates[:split_idx])
    oos_set = set(dates[split_idx:])
    p_is    = returns_df[returns_df.index.get_level_values("date").isin(is_set)]
    p_oos   = returns_df[returns_df.index.get_level_values("date").isin(oos_set)]
    beat = 0
    for _ in range(n_perms):
        perturbed_cfg = copy.deepcopy(cfg)
        try:
            factor = float(rng.uniform(0.9, 1.1))
            orig_ld = perturbed_cfg.strategy_params.reversal.long_decile
            orig_sd = perturbed_cfg.strategy_params.reversal.short_decile
            perturbed_cfg.strategy_params.reversal.long_decile = max(
                0.01, min(0.49, orig_ld * factor))
            perturbed_cfg.strategy_params.reversal.short_decile = max(
                0.51, min(0.99, orig_sd * factor))
        except AttributeError:
            pass
        ret = simulate_strategy(p_is, p_oos, perturbed_cfg, cost_model)
        if ret is not None and sharpe_ratio(ret) >= observed_sharpe:
            beat += 1
    return beat / n_perms


def _remap_dates(df: pd.DataFrame, date_map: dict) -> pd.DataFrame:
    """Return a copy of df with index dates remapped via date_map."""
    new_dates = [date_map.get(d, d) for d in df.index.get_level_values("date")]
    new_index = pd.MultiIndex.from_arrays(
        [new_dates, df.index.get_level_values("ticker")],
        names=["date", "ticker"],
    )
    return df.set_axis(new_index)
