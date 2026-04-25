"""
tests/unit/s7/conftest.py

Shared fixtures for S7 unit tests.
"""
from __future__ import annotations

import datetime
import uuid
from unittest.mock import MagicMock

import pytest

from shared.models import Signal


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.__enter__ = lambda s: s
    session.__exit__ = MagicMock(return_value=False)
    return session


@pytest.fixture
def pending_signal():
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
        status="PENDING",
    )


@pytest.fixture
def approved_signal():
    return Signal(
        id=2,
        run_id=uuid.uuid4(),
        created_at=datetime.datetime.now(tz=datetime.timezone.utc),
        ticker="MSFT",
        strategy="REVERSAL",
        side="SHORT",
        raw_score=0.4,
        sentiment_adj=0.5,
        regime="MED_VOL",
        target_size_usd=0.0,
        status="APPROVED",
    )
