"""
algotrader.backtest/metrics.py

Standalone performance metric computations used across all validation stages.
All functions are pure (no I/O) so they are trivially testable.
"""

from __future__ import annotations

import math

import pandas as pd
from scipy import stats


def sharpe_ratio(returns: pd.Series, periods_per_year: int = 252) -> float:
    """
    Annualised Sharpe ratio (assumes risk-free rate ≈ 0 for simplicity;
    backtest is measuring strategy alpha, not absolute return).

    Parameters
    ----------
    returns : daily return series
    periods_per_year : trading days in a year (252)
    """
    if len(returns) < 2:
        return 0.0
    std = returns.std(ddof=1)
    if std == 0.0:
        mean = float(returns.mean())
        if mean == 0.0:
            return 0.0                              # flat zero — no edge
        return math.copysign(100, mean)   # capped ±100.0
    return float((returns.mean() / std) * math.sqrt(periods_per_year))


def sortino_ratio(returns: pd.Series, periods_per_year: int = 252) -> float:
    """
    Annualised Sortino ratio using downside deviation (MAR = 0).
    """
    if len(returns) < 2:
        return 0.0
    downside = returns[returns < 0]
    if len(downside) == 0:
        return float("inf")
    downside_std = math.sqrt((downside ** 2).mean())
    if downside_std == 0.0:
        return 0.0
    return float((returns.mean() / downside_std) * math.sqrt(periods_per_year))


def max_drawdown(equity_curve: pd.Series) -> float:
    """
    Maximum peak-to-trough drawdown as a negative fraction (e.g. -0.25).
    """
    if len(equity_curve) == 0:
        return 0.0
    rolling_max = equity_curve.cummax()
    drawdowns = equity_curve / rolling_max - 1.0
    return float(drawdowns.min())


def equity_curve_from_returns(returns: pd.Series) -> pd.Series:
    """Convert a return series to a cumulative equity curve starting at 1.0."""
    return (1.0 + returns).cumprod()


def deflated_sharpe_ratio(
    sharpe_obs: float,
    n_trials: int,
    t: int,
    skew: float,
    kurt: float,
) -> float:
    """
    Compute the Deflated Sharpe Ratio (DSR) per López de Prado & Bailey (2014).

    DSR adjusts the observed Sharpe for the number of strategy trials tested,
    the length of the return series, and non-normality of returns.  A value
    near 1.0 indicates the observed Sharpe is unlikely to be a false positive.

    Parameters
    ----------
    sharpe_obs : annualised observed Sharpe ratio
    n_trials   : total number of parameter combinations / paths evaluated
    t          : number of OOS observations (trading days)
    skew       : third standardised moment of OOS returns
    kurt       : fourth standardised moment (excess kurtosis) of OOS returns
    """
    if n_trials <= 1 or t <= 1:
        return 0.0

    # Expected maximum Sharpe under IID normal returns
    euler_mascheroni = 0.5772156649
    expected_max = (
        (1.0 - euler_mascheroni) * stats.norm.ppf(1.0 - 1.0 / n_trials)
        + euler_mascheroni * stats.norm.ppf(1.0 - 1.0 / (n_trials * math.e))
    )

    # Variance correction for non-normality per Mertens (2002)
    sr_var = (
        (1.0 - skew * sharpe_obs + (kurt - 1.0) / 4.0 * sharpe_obs ** 2)
        / (t - 1)
    )

    if sr_var <= 0:
        return 0.0

    z = (sharpe_obs - expected_max) / math.sqrt(sr_var)
    return float(stats.norm.cdf(z))