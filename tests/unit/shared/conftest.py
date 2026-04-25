"""
Pytest fixtures shared across all shared/ unit tests.
"""
from pathlib import Path

import pytest
import yaml

from algotrader.shared.config_loader import invalidate_cache


@pytest.fixture(autouse=True)
def clear_config_cache():
    """Ensure every test starts with a clean config cache."""
    invalidate_cache()
    yield
    invalidate_cache()


@pytest.fixture()
def config_dir(tmp_path: Path) -> Path:
    """Write minimal valid YAML config files into a temp directory."""
    system = {
        "mode": "PAPER",
        "approval_mode": "HARD",
        "db_url": "postgresql://user:pass@localhost/test",
        "ibkr_paper_port": 7497,
        "ibkr_live_port": 7496,
        "ibkr_client_id": 1,
        "log_level": "INFO",
        "log_dir": str(tmp_path / "logs"),
        "data_dir_ssd": "data/",
        "data_dir_hdd": "/mnt/hdd/",
        "gpu_device": "cpu",
        "allow_market_orders": False,
    }
    risk = {
        "max_position_usd": 5000.0,
        "max_total_exposure_usd": 50000.0,
        "max_daily_loss_usd": 1500.0,
        "max_positions_open": 40,
        "kelly_fraction": 0.25,
        "atr_lookback_days": 14,
        "extreme_vol_halt": True,
        "halt_on_daily_loss": True,
        "halt_on_data_failure": True,
    }
    universe = {
        "min_market_cap_usd": 1_000_000_000,
        "min_avg_daily_volume": 500_000,
        "sector_etf_map": {"Technology": "XLK"},
        "tickers": [],
    }
    strategy_params = {
        "stat_arb": {
            "enabled": True,
            "lookback_days": 60,
            "min_kappa": 8.4,
            "entry_s_score": 1.25,
            "exit_s_score_long": -0.50,
            "exit_s_score_short": 0.75,
            "max_allocation_pct": 0.40,
        },
        "reversal": {
            "enabled": True,
            "lookback_days": 1,
            "long_decile": 0.10,
            "short_decile": 0.90,
            "turnover_split": True,
            "max_allocation_pct": 0.30,
        },
        "regime_combo": {
            "enabled": True,
            "vix_sma_lookback": 50,
            "low_vol_strategy": "stat_arb",
            "med_vol_strategy": "reversal",
            "high_vol_reduce_pct": 0.50,
            "max_allocation_pct": 0.30,
        },
    }
    sentiment_params = {
        "model": "finbert",
        "finbert_model_id": "ProsusAI/finbert",
        "openai_model": "gpt-4o-mini",
        "llama_host": "http://localhost:11434",
        "sentiment_threshold_positive": 0.30,
        "sentiment_threshold_negative": -0.30,
        "attention_z_threshold": 2.0,
        "attention_lookback_days": 30,
        "sources": {
            "reddit": {"enabled": True, "subreddits": ["investing"]},
            "twitter": {"enabled": False},
            "news": {"enabled": True, "provider": "yahoo_finance"},
        },
    }

    for name, data in [
        ("system.yaml", system),
        ("risk.yaml", risk),
        ("universe.yaml", universe),
        ("strategy_params.yaml", strategy_params),
        ("sentiment_params.yaml", sentiment_params),
    ]:
        (tmp_path / name).write_text(yaml.dump(data), encoding="utf-8")

    return tmp_path
