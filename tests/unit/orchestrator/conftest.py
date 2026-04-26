"""
Shared fixtures for S1 unit tests.

All external dependencies (DB, config, subprocesses) are mocked so tests
run without a real database or IBKR connection.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.fixture()
def mock_system_cfg():
    """Minimal system config namespace mirroring SystemConfig fields."""
    return SimpleNamespace(
        mode="PAPER",
        approval_mode="HARD",
        db_url="postgresql://test:test@localhost/test",
        log_level="INFO",
        log_dir="logs/",
        data_dir_ssd="data/",
        data_dir_hdd="/mnt/hdd/algotrader/",
        allow_market_orders=False,
    )


@pytest.fixture()
def mock_risk_cfg():
    return SimpleNamespace(
        max_position_usd=5000.0,
        max_total_exposure_usd=50000.0,
        max_daily_loss_usd=1500.0,
        max_positions_open=40,
        halt_on_daily_loss=True,
        halt_on_data_failure=True,
    )


@pytest.fixture()
def mock_sentiment_cfg():
    return SimpleNamespace(
        sentiment_threshold_positive=0.30,
        sentiment_threshold_negative=-0.30,
    )


@pytest.fixture()
def mock_cfg(mock_system_cfg, mock_risk_cfg, mock_sentiment_cfg):
    return SimpleNamespace(
        system=mock_system_cfg,
        risk=mock_risk_cfg,
        sentiment=mock_sentiment_cfg,
    )


@pytest.fixture()
def mock_session():
    """A MagicMock that supports the context-manager protocol for get_session()."""
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    return session


@pytest.fixture()
def run_id():
    return str(uuid.uuid4())


@pytest.fixture()
def utcnow():
    return datetime.now(tz=UTC)
