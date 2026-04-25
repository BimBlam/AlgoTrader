"""TransactionCostModel unit tests."""
import pytest
from types import SimpleNamespace
from s4_backtest_validator.costs import TransactionCostModel

def _cfg(slippage=0.0015, include_costs=True):
    return SimpleNamespace(backtest=SimpleNamespace(
        slippage_rate=slippage, include_costs=include_costs))

def test_zero_costs_when_disabled():
    assert TransactionCostModel(_cfg(include_costs=False)).estimate(50.0, 100).total_usd == 0.0

def test_minimum_commission():
    est = TransactionCostModel(_cfg()).estimate(50.0, 1)
    assert est.commission_usd == pytest.approx(0.35)

def test_commission_cap():
    est = TransactionCostModel(_cfg()).estimate(100.0, 100_000)
    assert est.commission_usd <= 100_000 * 0.01

def test_slippage_proportional():
    est = TransactionCostModel(_cfg(slippage=0.001)).estimate(100.0, 200)
    assert est.slippage_usd == pytest.approx(20.0)

def test_round_trip_positive():
    assert TransactionCostModel(_cfg()).round_trip_cost_rate(50.0, 100) > 0.0