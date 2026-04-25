"""Walk-forward tests."""
import pandas as pd
from algotrader.backtest.walk_forward import run_walk_forward, _build_monthly_boundaries
from algotrader.backtest.costs import TransactionCostModel

def test_monthly_boundaries_deduplicates():
    dates = pd.bdate_range("2022-01-01", periods=60).date.tolist()
    b = _build_monthly_boundaries(dates)
    months = [(d.year, d.month) for d in b]
    assert len(months) == len(set(months))

def test_walk_forward_returns_result(mock_cfg, make_returns_df):
    df = make_returns_df(400, 30)
    result = run_walk_forward(df, mock_cfg, TransactionCostModel(mock_cfg))
    assert isinstance(result.oos_sharpe, float)
    assert result.max_drawdown <= 0.0

def test_walk_forward_insufficient_months(mock_cfg, make_returns_df):
    df = make_returns_df(30, 10)
    result = run_walk_forward(df, mock_cfg, TransactionCostModel(mock_cfg))
    assert isinstance(result.oos_sharpe, float)