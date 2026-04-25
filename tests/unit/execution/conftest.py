"""
tests/unit/s6/conftest.py

Shared fixtures for all S6 unit tests.

- ``mock_cfg``          SimpleNamespace mirroring AppConfig (no file I/O).
- ``mock_session``      MagicMock SQLAlchemy session.
- ``mock_ibkr``         MagicMock IBKRClient.
- ``sample_signal``     A minimal APPROVED Signal ORM object.
- ``sample_order``      A minimal PENDING Order ORM object.
- ``sample_position``   A minimal OPEN Position ORM object.
"""
from __future__ import annotations

import datetime
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from algotrader.shared.models import Order, Position, Signal


@pytest.fixture
def mock_cfg():
    return SimpleNamespace(
        system=SimpleNamespace(
            mode="PAPER",
            ibkr_paper_port=7497,
            ibkr_live_port=7496,
            ibkr_client_id=1,
            data_dir_ssd="data/",
            allow_market_orders=False,
            db_url="postgresql://test/algotrader",
        ),
        risk=SimpleNamespace(
            max_position_usd=5000.0,
            max_total_exposure_usd=50000.0,
            max_daily_loss_usd=1500.0,
            max_positions_open=40,
            kelly_fraction=0.25,
            atr_lookback_days=14,
            extreme_vol_halt=False,
            halt_on_daily_loss=True,
            halt_on_data_failure=True,
        ),
        strategy_params=SimpleNamespace(
            regime_combo=SimpleNamespace(),
        ),
    )


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.__enter__ = lambda s: s
    session.__exit__ = MagicMock(return_value=False)
    return session


@pytest.fixture
def mock_ibkr():
    client = MagicMock()
    client.check_margin_ok.return_value = True
    client.get_account_equity.return_value = 100_000.0
    return client


@pytest.fixture
def sample_signal():
    return Signal(
        id=1,
        run_id=uuid.uuid4(),
        created_at=datetime.datetime.now(tz=datetime.timezone.utc),
        ticker="AAPL",
        strategy="STAT_ARB",
        side="LONG",
        raw_score=-2.1,
        sentiment_adj=1.0,
        regime="LOW_VOL",
        target_size_usd=0.0,
        status="APPROVED",
    )


@pytest.fixture
def sample_order():
    return Order(
        id=1,
        signal_id=1,
        ticker="AAPL",
        side="BUY",
        order_type="LIMIT",
        quantity=10,
        limit_price=150.0,
        status="PENDING",
        account_type="PAPER",
    )


@pytest.fixture
def sample_position():
    return Position(
        id=1,
        ticker="AAPL",
        side="BUY",
        entry_price=150.0,
        quantity=10,
        entry_time=datetime.datetime.now(tz=datetime.timezone.utc),
        status="OPEN",
        order_id=1,
        account_type="PAPER",
    )
