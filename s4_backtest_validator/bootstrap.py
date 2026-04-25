"""
s4_backtest_validator/bootstrap.py

Stationary bootstrap (Politis & Romano, 1994) over historical returns.
Average block length = 10 trading days per spec contract.

Changes from audit:
  - Removed unused `date_to_idx` variable from _rebuild_df_with_resampled_dates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np
import pandas as pd

from shared.logger import get_logger
from s4_backtest_validator.strategy_sim import simulate_strategy
from s4_backtest_validator.metrics import sharpe_ratio
from s4_backtest_validator.costs import TransactionCostModel

log = get_logger(__name__)

_STATIONARY_BOOTSTRAP_BLOCK_MEAN = 10


@dataclass
class BootstrapResult:
    block_sharpes: List[float]


def run_stationary_bootstrap(
    returns_df: pd.DataFrame,
    cfg,
    cost_model: TransactionCostModel,
) -> BootstrapResult:
    """
    Generate `n_bootstrap_paths` alternative return histories via the stationary
    bootstrap and evaluate strategy Sharpe on each.

    Parameters
    ----------
    returns_df : MultiIndex (date, ticker) DataFrame
    cfg        : AppConfig
    cost_model : TransactionCostModel
    """
    n_paths: int = getattr(cfg.backtest, "n_bootstrap_paths", 500)
    block_mean: int = getattr(cfg.backtest, "bootstrap_block_mean",
                              _STATIONARY_BOOTSTRAP_BLOCK_MEAN)
    rng = np.random.default_rng(
        seed=getattr(cfg.backtest, "random_seed", 42) + 1
    )

    dates = sorted(returns_df.index.get_level_values("date").unique())
    n_dates = len(dates)
    split_idx = n_dates * 3 // 4
    block_sharpes: list[float] = []

    for _ in range(n_paths):
        resampled_dates = _stationary_bootstrap_dates(dates, n_dates,
                                                       block_mean, rng)
        boot_df = _rebuild_df_with_resampled_dates(returns_df, dates,
                                                    resampled_dates)
        is_set  = set(resampled_dates[:split_idx])
        oos_set = set(resampled_dates[split_idx:])
        is_df  = boot_df[boot_df.index.get_level_values("date").isin(is_set)]
        oos_df = boot_df[boot_df.index.get_level_values("date").isin(oos_set)]

        if is_df.empty or oos_df.empty:
            continue

        oos_ret = simulate_strategy(is_df, oos_df, cfg, cost_model)
        if oos_ret is not None and len(oos_ret) > 1:
            block_sharpes.append(sharpe_ratio(oos_ret))

    log.info("stationary_bootstrap_complete", n_paths=n_paths,
             n_successful=len(block_sharpes), block_mean=block_mean)
    return BootstrapResult(block_sharpes=block_sharpes)


def _stationary_bootstrap_dates(
    dates: list,
    n: int,
    block_mean: int,
    rng: np.random.Generator,
) -> list:
    """
    Stationary bootstrap index sequence (Politis & Romano 1994).

    Geometric block length (p = 1/block_mean) preserves short-range
    autocorrelation structure better than fixed-block bootstrap.
    """
    p = 1.0 / block_mean
    indices: list[int] = []
    idx = int(rng.integers(0, n))
    while len(indices) < n:
        indices.append(idx)
        if rng.random() < p:
            idx = int(rng.integers(0, n))
        else:
            idx = (idx + 1) % n
    return [dates[i] for i in indices[:n]]


def _rebuild_df_with_resampled_dates(
    returns_df: pd.DataFrame,
    original_dates: list,
    resampled_dates: list,
) -> pd.DataFrame:
    """
    Build a new DataFrame whose rows come from `returns_df` in the order
    specified by `resampled_dates`, re-indexed onto the original date sequence
    so the resulting index is monotone (required by simulate_strategy).
    """
    frames = []
    for new_date, src_date in zip(original_dates, resampled_dates):
        try:
            day_data = returns_df.xs(src_date, level="date").copy()
        except KeyError:
            continue
        day_data = day_data.reset_index()
        day_data["date"] = new_date
        frames.append(day_data.set_index(["date", "ticker"]))

    if not frames:
        return returns_df.iloc[:0].copy()
    return pd.concat(frames).sort_index()