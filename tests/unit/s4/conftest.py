"""Shared fixtures for all S4 unit tests."""
from __future__ import annotations
import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def mock_cfg():
    backtest = SimpleNamespace(
        is_window_months=6, n_mc_paths=20, n_bootstrap_paths=20,
        bootstrap_block_mean=5, n_permutations=10, slippage_rate=0.0015,
        include_costs=True, random_seed=0,
    )
    reversal    = SimpleNamespace(long_decile=0.10, short_decile=0.90, enabled=True)
    statarb     = SimpleNamespace(enabled=False)
    regimecombo = SimpleNamespace(enabled=False)
    strategy_params = SimpleNamespace(
        reversal=reversal, statarb=statarb, regimecombo=regimecombo,
        active_strategy="REVERSAL",
    )
    system = SimpleNamespace(
        data_dir_ssd="/tmp/ssd", data_dir_hdd="/tmp/hdd",
        db_url="postgresql://test/test",
    )
    return SimpleNamespace(
        backtest=backtest, strategy_params=strategy_params, system=system,
        universe_hash="aabbcc", strategy_params_hash="ddeeff",
    )


@pytest.fixture
def make_returns_df():
    def _factory(n_days: int = 300, n_tickers: int = 20) -> pd.DataFrame:
        rng = np.random.default_rng(42)
        start = datetime.date(2022, 1, 3)
        dates = pd.bdate_range(start=start, periods=n_days).date.tolist()
        tickers = [f"T{i:03d}" for i in range(n_tickers)]
        rows = []
        for d in dates:
            for t in tickers:
                rows.append({
                    "date": d, "ticker": t,
                    "ret1d": float(rng.normal(0.0002, 0.015)),
                    "ret5d": float(rng.normal(0.001,  0.030)),
                    "volume": int(rng.integers(500_000, 5_000_000)),
                    "avg_vol30": float(rng.integers(500_000, 5_000_000)),
                    "turnover": float(rng.uniform(0.001, 0.05)),
                    "sector_etf": "XLK",
                })
        return pd.DataFrame(rows).set_index(["date", "ticker"])
    return _factory


@pytest.fixture
def mock_session():
    s = MagicMock()
    s.__enter__ = lambda self: self
    s.__exit__ = MagicMock(return_value=False)
    return s