"""Stationary bootstrap tests."""
import numpy as np
import pandas as pd

from algotrader.backtest.bootstrap import (
    _stationary_bootstrap_dates,
    run_stationary_bootstrap,
)
from algotrader.backtest.costs import TransactionCostModel


def test_bootstrap_date_length():
    dates = pd.bdate_range("2022-01-01", periods=50).date.tolist()
    rng = np.random.default_rng(0)
    result = _stationary_bootstrap_dates(dates, 50, 10, rng)
    assert len(result) == 50
    assert all(d in dates for d in result)


def test_bootstrap_produces_list(mock_cfg, make_returns_df):
    mock_cfg.backtest.n_bootstrap_paths = 5
    df = make_returns_df(300, 20)
    result = run_stationary_bootstrap(df, mock_cfg, TransactionCostModel(mock_cfg))
    assert isinstance(result.block_sharpes, list)


def test_bootstrap_no_dead_code_date_to_idx(mock_cfg, make_returns_df):
    """Ensure _rebuild_df_with_resampled_dates has no references to date_to_idx."""
    import inspect

    from algotrader.backtest.bootstrap import _rebuild_df_with_resampled_dates
    src = inspect.getsource(_rebuild_df_with_resampled_dates)
    assert "date_to_idx" not in src, "Dead variable date_to_idx was not removed"
