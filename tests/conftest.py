"""
Shared pytest fixtures for the AlgoTrader test suite.

All external dependencies (yfinance, PRAW, DB, config) are mocked here.
No test ever calls a real API, connects to a database, or reads from disk
unless it explicitly receives a tmp_path fixture.
"""

from __future__ import annotations

import datetime
import types
from pathlib import Path

import pandas as pd
import pytest

# ── Config fixture ────────────────────────────────────────────────────────────

@pytest.fixture()
def mock_cfg(tmp_path):
    """
    Return a minimal AppConfig-like namespace that satisfies every S2 code path.
    Uses SimpleNamespace so attribute access mirrors Pydantic model access.
    """
    cfg = types.SimpleNamespace(
        system=types.SimpleNamespace(
            db_url="postgresql://localhost/algotrader_test",
            data_dir_ssd=str(tmp_path / "ssd"),
            data_dir_hdd=str(tmp_path / "hdd"),
            log_level="DEBUG",
        ),
        universe=types.SimpleNamespace(
            tickers=["AAPL", "MSFT"],
            sector_etf_map={
                "Technology": "XLK",
                "Financials": "XLF",
            },
        ),
        sentiment_params=types.SimpleNamespace(
            sources={
                "news": {"enabled": True, "provider": "yahoo_finance"},
                "reddit": {
                    "enabled": False,
                    "subreddits": ["wallstreetbets"],
                },
                "twitter": {"enabled": False},
            }
        ),
    )
    # Create required directories.
    Path(cfg.system.data_dir_ssd).mkdir(parents=True, exist_ok=True)
    Path(cfg.system.data_dir_hdd).mkdir(parents=True, exist_ok=True)
    return cfg


# ── Date fixture ──────────────────────────────────────────────────────────────

@pytest.fixture()
def today():
    return datetime.date(2024, 3, 15)  # A Friday; safe test anchor date.


# ── OHLCV DataFrame factory ───────────────────────────────────────────────────

@pytest.fixture()
def make_ohlcv_df():
    """Factory that returns a clean OHLCV DataFrame of *n* business days."""
    def _factory(n: int = 10, start: str = "2024-01-02", base_price: float = 100.0) -> pd.DataFrame:
        dates = pd.bdate_range(start, periods=n)
        prices = [base_price + float(i) for i in range(n)]
        df = pd.DataFrame(
            {
                "open":      prices,
                "high":      [p + 1.0 for p in prices],
                "low":       [p - 1.0 for p in prices],
                "close":     prices,
                "volume":    [1_000_000] * n,
                "adj_close": prices,
            },
            index=dates,
        )
        df.index.name = "date"
        return df
    return _factory
