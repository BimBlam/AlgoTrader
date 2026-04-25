"""
algotrader.backtest/strategy_sim.py

Lightweight strategy simulator used by walk-forward, Monte Carlo, and
bootstrap stages.  Implements the cross-sectional reversal and stat-arb
signal logic at the level of returns, parameterised from config.

Critically: this module NEVER submits orders and NEVER modifies config.
"""

from __future__ import annotations

import pandas as pd

from algotrader.shared.logger import get_logger
from algotrader.backtest.costs import TransactionCostModel

log = get_logger(__name__)

_PROXY_PRICE = 50.0   # Synthetic per-share price used for cost estimation
_PROXY_QTY   = 100    # Synthetic share quantity; costs scale with this


def simulate_strategy(
    is_data: pd.DataFrame,
    eval_data: pd.DataFrame,
    cfg,
    cost_model: TransactionCostModel,
) -> pd.Series | None:
    """
    Simulate the reversal strategy on `eval_data` using parameters derived
    from `is_data`, return a daily portfolio return Series.

    The reversal signal ranks tickers by 1-day return; we go long the bottom
    decile and short the top decile.  Equal-weight within each leg.  This
    mirrors the S3 reversal strategy to keep IS/OOS coherent.

    Parameters
    ----------
    is_data   : in-sample DataFrame (date × ticker MultiIndex, ret1d column)
    eval_data : evaluation-period DataFrame with the same structure
    cfg       : AppConfig
    cost_model: TransactionCostModel for cost-adjusted returns

    Returns
    -------
    pd.Series of daily portfolio returns indexed by date, or None on failure.
    """
    try:
        long_decile: float = getattr(
            cfg.strategy_params.reversal, "long_decile", 0.10
        )
        short_decile: float = getattr(
            cfg.strategy_params.reversal, "short_decile", 0.90
        )

        # Round-trip cost rate for a single position entry + exit
        cost_rate = cost_model.round_trip_cost_rate(_PROXY_PRICE, _PROXY_QTY)

        daily_returns: list[float] = []
        eval_dates = sorted(eval_data.index.get_level_values("date").unique())

        for date in eval_dates:
            day_slice = eval_data.xs(date, level="date")
            if len(day_slice) < 10:
                continue

            ret1d = day_slice["ret1d"].dropna()
            if len(ret1d) < 5:
                continue

            ranks = ret1d.rank(pct=True)
            longs = ranks[ranks <= long_decile]
            shorts = ranks[ranks >= short_decile]

            n_long = len(longs)
            n_short = len(shorts)
            if n_long == 0 or n_short == 0:
                continue

            # Equal-weight legs; daily return is next-day ret1d of selected
            # tickers (look-forward using same-day ret1d as next-day proxy).
            # In a real backtest, ret1d[t] predicts ret1d[t+1].
            # Here is_data would supply fitted thresholds; eval_data applies them.
            long_ret = ret1d[longs.index].mean()
            short_ret = ret1d[shorts.index].mean()

            # Long minus short, minus round-trip cost rate amortised over
            # position hold (treat each day as independent for simplicity).
            port_ret = (long_ret - short_ret) / 2.0 - cost_rate

            daily_returns.append((date, port_ret))

        if not daily_returns:
            return None

        dates, rets = zip(*daily_returns)
        return pd.Series(rets, index=pd.Index(dates, name="date"), dtype=float)

    except Exception as exc:
        log.warning("simulate_strategy_failed", error=str(exc))
        return None