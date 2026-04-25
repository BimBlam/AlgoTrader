"""
algotrader.backtest/walk_forward.py

Rolling walk-forward validation: N-month in-sample window, 1-month OOS.
Evaluates each OOS window using the strategy\'s signal from the in-sample
fitted parameters and accumulates the OOS return stream used for all
downstream metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import pandas as pd
from scipy import stats

from algotrader.shared.logger import get_logger
from algotrader.backtest.metrics import (
    sharpe_ratio,
    sortino_ratio,
    max_drawdown,
    equity_curve_from_returns,
)
from algotrader.backtest.strategy_sim import simulate_strategy
from algotrader.backtest.costs import TransactionCostModel

log = get_logger(__name__)


@dataclass
class WalkForwardResult:
    oos_returns: pd.Series
    oos_equity_curve: pd.Series
    oos_sharpe: float
    oos_sortino: float
    max_drawdown: float
    oos_skew: float
    oos_kurt: float
    oos_n_obs: int
    # Per-window Sharpe variants used later by CSCV
    oos_sharpe_variants: List[float] = field(default_factory=list)


def run_walk_forward(
    returns_df: pd.DataFrame,
    cfg,
    cost_model: TransactionCostModel,
) -> WalkForwardResult:
    """
    Execute rolling walk-forward backtests across the full history.

    Uses cfg.backtest.is_window_months for the in-sample window length
    (default 12) and a fixed 1-month OOS window per spec.

    Parameters
    ----------
    returns_df : MultiIndex (date, ticker) DataFrame from loader.py
    cfg        : AppConfig from get_config()
    cost_model : pre-built TransactionCostModel

    Returns
    -------
    WalkForwardResult
        Aggregated OOS statistics and the full concatenated OOS return stream.
    """
    is_months: int = getattr(cfg.backtest, "is_window_months", 12)
    dates = sorted(returns_df.index.get_level_values("date").unique())

    # Convert date list to monthly boundaries for rolling windows
    monthly_boundaries = _build_monthly_boundaries(dates)

    if len(monthly_boundaries) < is_months + 2:
        log.warning(
            "walk_forward_too_few_months",
            available=len(monthly_boundaries),
            required=is_months + 2,
        )

    oos_returns_all: list[pd.Series] = []
    oos_sharpe_variants: list[float] = []

    for i in range(is_months, len(monthly_boundaries) - 1):
        is_start = monthly_boundaries[i - is_months]
        is_end = monthly_boundaries[i]
        oos_start = monthly_boundaries[i]
        oos_end = monthly_boundaries[i + 1]

        is_mask = (
            (returns_df.index.get_level_values("date") >= is_start)
            & (returns_df.index.get_level_values("date") < is_end)
        )
        oos_mask = (
            (returns_df.index.get_level_values("date") >= oos_start)
            & (returns_df.index.get_level_values("date") < oos_end)
        )

        is_data = returns_df[is_mask]
        oos_data = returns_df[oos_mask]

        if is_data.empty or oos_data.empty:
            continue

        # Fit strategy on IS, evaluate on OOS
        oos_ret = simulate_strategy(
            is_data=is_data,
            eval_data=oos_data,
            cfg=cfg,
            cost_model=cost_model,
        )

        if oos_ret is not None and len(oos_ret) > 0:
            oos_returns_all.append(oos_ret)
            window_sharpe = sharpe_ratio(oos_ret)
            oos_sharpe_variants.append(window_sharpe)

            log.debug(
                "walk_forward_window_done",
                is_start=str(is_start),
                oos_start=str(oos_start),
                oos_end=str(oos_end),
                window_sharpe=round(window_sharpe, 3),
            )

    if not oos_returns_all:
        log.warning("walk_forward_no_oos_windows_produced")
        empty = pd.Series(dtype=float)
        return WalkForwardResult(
            oos_returns=empty,
            oos_equity_curve=empty,
            oos_sharpe=0.0,
            oos_sortino=0.0,
            max_drawdown=0.0,
            oos_skew=0.0,
            oos_kurt=0.0,
            oos_n_obs=0,
            oos_sharpe_variants=[],
        )

    combined_oos = pd.concat(oos_returns_all).sort_index()
    equity = equity_curve_from_returns(combined_oos)

    return WalkForwardResult(
        oos_returns=combined_oos,
        oos_equity_curve=equity,
        oos_sharpe=sharpe_ratio(combined_oos),
        oos_sortino=sortino_ratio(combined_oos),
        max_drawdown=max_drawdown(equity),
        oos_skew=float(stats.skew(combined_oos)),
        oos_kurt=float(stats.kurtosis(combined_oos)),
        oos_n_obs=len(combined_oos),
        oos_sharpe_variants=oos_sharpe_variants,
    )


def _build_monthly_boundaries(dates: list) -> list:
    """
    Extract unique (year, month) month-start boundaries from a sorted date list.
    Returns a list of datetime.date objects representing the first trading day
    of each calendar month present in the data.
    """
    seen: set = set()
    boundaries: list = []
    for d in dates:
        key = (d.year, d.month)
        if key not in seen:
            seen.add(key)
            boundaries.append(d)
    return sorted(boundaries)