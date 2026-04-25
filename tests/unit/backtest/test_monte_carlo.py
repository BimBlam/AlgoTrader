"""Monte Carlo tests — small path count for speed."""
import numpy as np
from algotrader.backtest.monte_carlo import run_monte_carlo, _simulate_garch_manual
from algotrader.backtest.costs import TransactionCostModel


def test_mc_produces_list(mock_cfg, make_returns_df):
    mock_cfg.backtest.n_mc_paths = 5
    df = make_returns_df(300, 20)
    result = run_monte_carlo(df, mock_cfg, TransactionCostModel(mock_cfg))
    assert isinstance(result.path_sharpes, list)
    assert all(isinstance(s, float) for s in result.path_sharpes)


def test_mc_insufficient_data(mock_cfg, make_returns_df):
    df = make_returns_df(30, 5)
    result = run_monte_carlo(df, mock_cfg, TransactionCostModel(mock_cfg))
    assert result.path_sharpes == []


def test_garch_manual_length():
    rng = np.random.default_rng(0)
    path = _simulate_garch_manual(0.0, 1e-4, 0.05, 0.90, 100, rng)
    assert len(path) == 100


def test_garch_manual_deterministic():
    """Same seed produces identical paths."""
    p1 = _simulate_garch_manual(0.0, 1e-4, 0.05, 0.90, 50, np.random.default_rng(7))
    p2 = _simulate_garch_manual(0.0, 1e-4, 0.05, 0.90, 50, np.random.default_rng(7))
    assert np.allclose(p1, p2)


def test_garch_manual_different_seeds_differ():
    p1 = _simulate_garch_manual(0.0, 1e-4, 0.05, 0.90, 50, np.random.default_rng(1))
    p2 = _simulate_garch_manual(0.0, 1e-4, 0.05, 0.90, 50, np.random.default_rng(2))
    assert not np.allclose(p1, p2)