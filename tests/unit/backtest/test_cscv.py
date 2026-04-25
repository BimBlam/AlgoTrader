"""CSCV PBO tests."""
from algotrader.backtest.cscv import compute_cscv_pbo

def test_pbo_in_range():
    pbo = compute_cscv_pbo([0.5, 1.2, -0.3, 0.8, 1.5, -0.1, 0.9, 0.4])
    assert 0.0 <= pbo <= 1.0

def test_pbo_too_few_variants():
    assert compute_cscv_pbo([1.0, 0.5]) == 1.0
    assert compute_cscv_pbo([]) == 1.0

def test_pbo_all_positive():
    pbo = compute_cscv_pbo([1.0 + i * 0.01 for i in range(20)])
    assert isinstance(pbo, float)

def test_pbo_all_negative():
    pbo = compute_cscv_pbo([-1.0 - i * 0.01 for i in range(20)])
    assert isinstance(pbo, float)