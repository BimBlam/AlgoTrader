"""
Shared fixtures for S3 unit tests.

Provides:
  - mock_cfg: minimal AppConfig-like namespace
  - sample_returns_df: realistic returns parquet DataFrame
  - sample_ou_results: pre-built OUResult list
  - sample_sentiment_map: ticker → sentiment dict
  - mock_session: SQLAlchemy session mock
"""
import datetime
import types
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from s3_signal_engine.ou_model import OUResult


# ── Strategy config helpers ──────────────────────────────────────────────────

def _make_strategy_cfg(
    stat_arb_enabled=True,
    reversal_enabled=True,
    entry_s_score=1.25,
    exit_s_score_long=-0.50,
    exit_s_score_short=0.75,
    long_decile=0.10,
    short_decile=0.90,
    turnover_split=True,
    min_kappa=8.4,
    lookback=60,
    high_vol_reduce_pct=0.50,
):
    stat_arb = types.SimpleNamespace(
        enabled=stat_arb_enabled,
        lookback_days=lookback,
        min_kappa=min_kappa,
        entry_s_score=entry_s_score,
        exit_s_score_long=exit_s_score_long,
        exit_s_score_short=exit_s_score_short,
        max_allocation_pct=0.40,
    )
    reversal = types.SimpleNamespace(
        enabled=reversal_enabled,
        lookback_days=1,
        long_decile=long_decile,
        short_decile=short_decile,
        turnover_split=turnover_split,
        max_allocation_pct=0.30,
    )
    regime_combo = types.SimpleNamespace(
        enabled=True,
        vix_sma_lookback=50,
        low_vol_strategy="stat_arb",
        med_vol_strategy="reversal",
        high_vol_reduce_pct=high_vol_reduce_pct,
        max_allocation_pct=0.30,
    )
    return types.SimpleNamespace(
        stat_arb=stat_arb,
        reversal=reversal,
        regime_combo=regime_combo,
    )


def _make_sentiment_cfg():
    return types.SimpleNamespace(
        model="finbert",
        sentiment_threshold_positive=0.30,
        sentiment_threshold_negative=-0.30,
        attention_z_threshold=2.0,
        attention_lookback_days=30,
    )


def _make_system_cfg(tmp_path=None):
    import tempfile
    root = str(tmp_path or tempfile.mkdtemp())
    return types.SimpleNamespace(
        data_dir_ssd=root,
        data_dir_hdd=root,
        db_url="postgresql://test/test",
    )


@pytest.fixture
def strategy_cfg():
    return _make_strategy_cfg()


@pytest.fixture
def mock_cfg(tmp_path):
    cfg = types.SimpleNamespace(
        system=_make_system_cfg(tmp_path),
        strategy_params=_make_strategy_cfg(),
        sentiment_params=_make_sentiment_cfg(),
        risk=types.SimpleNamespace(
            max_position_usd=5000,
            max_total_exposure_usd=50000,
            max_positions_open=40,
            kelly_fraction=0.25,
            extreme_vol_halt=True,
        ),
    )
    return cfg


@pytest.fixture
def today():
    return datetime.date(2025, 1, 15)


@pytest.fixture
def run_id():
    return "test-run-00000000-0000-0000-0000-000000000001"


@pytest.fixture
def sample_returns_df():
    """10-ticker returns DataFrame matching the §4.4 parquet schema."""
    tickers = ["AAPL", "MSFT", "GOOG", "AMZN", "META", "NVDA", "TSLA", "JPM", "GS", "BAC"]
    rng = np.random.default_rng(42)
    n = len(tickers)
    return pd.DataFrame(
        {
            "ret_1d": rng.normal(0, 0.015, n),
            "ret_5d": rng.normal(0, 0.030, n),
            "volume": rng.integers(1_000_000, 50_000_000, n),
            "avg_vol_30": rng.integers(500_000, 20_000_000, n).astype(float),
            "turnover": rng.uniform(0.001, 0.05, n),
            "sector_etf": ["XLK"] * 7 + ["XLF"] * 3,
        },
        index=tickers,
    )


@pytest.fixture
def sample_ou_results():
    """Mix of valid and invalid OU params."""
    return [
        OUResult("AAPL", kappa=15.0, mu=-0.01, sigma_eq=0.05, beta=0.8, s_score=-1.5, valid=True, cumulative_residual=-0.075),
        OUResult("MSFT", kappa=12.0, mu=0.00, sigma_eq=0.04, beta=0.9, s_score=1.8, valid=True, cumulative_residual=0.072),
        OUResult("GOOG", kappa=5.0, mu=0.00, sigma_eq=0.06, beta=0.7, s_score=0.5, valid=False, cumulative_residual=0.03),  # invalid kappa
        OUResult("NVDA", kappa=20.0, mu=0.01, sigma_eq=0.08, beta=1.1, s_score=-2.1, valid=True, cumulative_residual=-0.168),
        OUResult("TSLA", kappa=9.0, mu=-0.02, sigma_eq=0.10, beta=1.3, s_score=0.3, valid=True, cumulative_residual=0.03),  # inside bands
    ]


@pytest.fixture
def sample_sentiment_map():
    return {
        "AAPL": {"sentiment_res": 0.10, "abn_attention": 0.5, "model_used": "finbert"},
        "MSFT": {"sentiment_res": -0.40, "abn_attention": 2.5, "model_used": "finbert"},  # strong bearish
        "GOOG": {"sentiment_res": 0.0, "abn_attention": 0.0, "model_used": "none"},
        "NVDA": {"sentiment_res": 0.50, "abn_attention": 1.0, "model_used": "finbert"},  # bullish
        "TSLA": {"sentiment_res": -0.10, "abn_attention": 0.3, "model_used": "finbert"},
    }


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    return session
