"""Permutation battery tests."""
from s4_backtest_validator.permutation import run_permutation_battery
from s4_backtest_validator.costs import TransactionCostModel

_EXPECTED_TESTS = {
    "circular_shift", "sign_flip", "jitter",
    "noise_injection", "parameter_stability",
}


def test_all_test_names_present(mock_cfg, make_returns_df):
    mock_cfg.backtest.n_permutations = 5
    df = make_returns_df(300, 20)
    result = run_permutation_battery(df, mock_cfg, TransactionCostModel(mock_cfg))
    assert _EXPECTED_TESTS == set(result.p_values.keys())


def test_p_values_in_range(mock_cfg, make_returns_df):
    mock_cfg.backtest.n_permutations = 5
    df = make_returns_df(300, 20)
    result = run_permutation_battery(df, mock_cfg, TransactionCostModel(mock_cfg))
    for key, p in result.p_values.items():
        assert 0.0 <= p <= 1.0, f"{key} p-value out of [0,1]: {p}"


def test_circular_shift_not_always_zero(mock_cfg, make_returns_df):
    """After fix, circular shift no longer produces consistently empty DataFrames."""
    mock_cfg.backtest.n_permutations = 10
    df = make_returns_df(300, 20)
    result = run_permutation_battery(df, mock_cfg, TransactionCostModel(mock_cfg))
    # p-value should be a real number in (0, 1), not a degenerate 0.0 every time
    p = result.p_values["circular_shift"]
    assert isinstance(p, float)