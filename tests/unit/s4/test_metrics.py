"""Pure metric function tests — no I/O."""
import numpy as np
import pandas as pd
from s4_backtest_validator.metrics import (
    sharpe_ratio, sortino_ratio, max_drawdown,
    equity_curve_from_returns, deflated_sharpe_ratio,
)

def test_sharpe_positive():
    assert sharpe_ratio(pd.Series([0.01] * 252)) > 0

def test_sharpe_zero_std():
    assert sharpe_ratio(pd.Series([0.0] * 100)) == 0.0

def test_sharpe_empty():
    assert sharpe_ratio(pd.Series(dtype=float)) == 0.0

def test_sortino_no_downside():
    assert sortino_ratio(pd.Series([0.01] * 50)) == float("inf")

def test_sortino_mixed():
    ret = pd.Series(np.random.default_rng(1).normal(0.001, 0.01, 252))
    assert isinstance(sortino_ratio(ret), float)

def test_max_drawdown_flat():
    assert max_drawdown(pd.Series([1.0] * 10)) == 0.0

def test_max_drawdown_declining():
    dd = max_drawdown(pd.Series([1.0, 0.9, 0.8, 0.7]))
    assert dd < 0
    assert abs(dd - (-0.3)) < 1e-6

def test_equity_curve_starts_correctly():
    eq = equity_curve_from_returns(pd.Series([0.01, -0.01, 0.02]))
    assert abs(eq.iloc[0] - 1.01) < 1e-9

def test_deflated_sharpe_range():
    dsr = deflated_sharpe_ratio(1.5, 500, 252, 0.0, 0.0)
    assert 0.0 <= dsr <= 1.0

def test_deflated_sharpe_trivial():
    assert deflated_sharpe_ratio(0.0, 1, 1, 0.0, 0.0) == 0.0