"""
Shared fixtures for S5 unit tests.

Follows the same pattern as S2's conftest: a single patched_env fixture
neutralises all external dependencies (config, DB, GPU) so tests run
hermetically without a PostgreSQL instance or GPU.
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def today() -> datetime.date:
    return datetime.date(2025, 1, 15)


@pytest.fixture
def tickers() -> list[str]:
    return ["AAPL", "MSFT", "TSLA"]


@pytest.fixture
def mock_cfg(tickers):
    """Minimal AppConfig-shaped namespace for S5."""
    return SimpleNamespace(
        system=SimpleNamespace(
            db_url="postgresql://test/test",
            data_dir_hdd="/mnt/hdd/algotrader",
            gpu_device="cpu",
            log_level="INFO",
            log_dir="logs/",
            data_dir_ssd="data/",
        ),
        sentiment=SimpleNamespace(
            model="finbert",
            finbert_model_id="ProsusAI/finbert",
            openai_model="gpt-4o-mini",
            llama_host="http://localhost:11434",
            sentiment_threshold_positive=0.30,
            sentiment_threshold_negative=-0.30,
            attention_z_threshold=2.0,
            attention_lookback_days=30,
            sources=SimpleNamespace(
                reddit=SimpleNamespace(enabled=True, subreddits=["wallstreetbets"]),
                twitter=SimpleNamespace(enabled=False),
                news=SimpleNamespace(enabled=True, provider="yahoo_finance"),
            ),
        ),
        universe=SimpleNamespace(
            tickers=tickers,
        ),
    )


@pytest.fixture
def patched_env(mock_cfg):
    """
    Patch get_config, init_db, get_session, and SystemEvent so unit tests
    never touch a real database or GPU.
    """
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)

    with (
        patch("s5_sentiment.main.get_config", return_value=mock_cfg),
        patch("s5_sentiment.main.init_db"),
        patch("s5_sentiment.main.get_session", return_value=mock_session),
    ):
        yield mock_cfg, mock_session
