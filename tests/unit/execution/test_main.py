"""tests/unit/s6/test_main.py"""
from __future__ import annotations

import datetime
import os
import uuid
from unittest.mock import MagicMock, patch

import pytest

from algotrader.shared.constants import EventType
from algotrader.shared.exceptions import DataError, ExecutionError, RiskBreach
from algotrader.shared.models import Signal
from algotrader.execution import main as s6_main


def _make_approved_signal(ticker: str = "AAPL") -> Signal:
    return Signal(
        id=1,
        run_id=uuid.uuid4(),
        created_at=datetime.datetime.now(tz=datetime.timezone.utc),
        ticker=ticker,
        strategy="STAT_ARB",
        side="LONG",
        raw_score=-2.1,
        sentiment_adj=1.0,
        regime="LOW_VOL",
        target_size_usd=0.0,
        status="APPROVED",
    )


@pytest.fixture
def patched_env(mock_cfg, mock_session):
    """Patch all shared dependencies used by main.run()."""
    with (
        patch("algotrader.execution.main.get_config", return_value=mock_cfg),
        patch("algotrader.execution.main.init_db"),
        patch("algotrader.execution.main.get_session") as mock_gs,
    ):
        mock_gs.return_value.__enter__ = lambda s: mock_session
        mock_gs.return_value.__exit__ = MagicMock(return_value=False)
        yield mock_session


class TestRunIBKRConnectionFailure:
    def test_exits_1_and_emits_halt_on_connection_failure(self, patched_env, mock_cfg):
        mock_ibkr = MagicMock()
        mock_ibkr.connect.side_effect = ExecutionError("TWS not running")

        with (
            patch("algotrader.execution.main.IBKRClient", return_value=mock_ibkr),
            patch.dict(os.environ, {"ACCOUNT_TYPE": "PAPER"}),
            pytest.raises(SystemExit) as exc_info,
        ):
            s6_main.run("test-run-id")

        assert exc_info.value.code == 1


class TestRunDailyLossHalt:
    def test_exits_1_on_daily_loss_breach(self, patched_env, mock_cfg, mock_session):
        mock_ibkr = MagicMock()
        mock_ibkr.connect.return_value = None

        with (
            patch("algotrader.execution.main.IBKRClient", return_value=mock_ibkr),
            patch("algotrader.execution.main.check_daily_loss",
                  side_effect=RiskBreach("Daily loss limit breached")),
            patch.dict(os.environ, {"ACCOUNT_TYPE": "PAPER"}),
            pytest.raises(SystemExit) as exc_info,
        ):
            s6_main.run("test-run-id")

        assert exc_info.value.code == 1
        mock_ibkr.cancel_all_pending.assert_called_once()


class TestRunNoSignals:
    def test_exits_0_when_no_approved_signals(self, patched_env, mock_cfg, mock_session):
        mock_session.query.return_value.filter.return_value.all.return_value = []
        mock_ibkr = MagicMock()
        mock_ibkr.connect.return_value = None

        with (
            patch("algotrader.execution.main.IBKRClient", return_value=mock_ibkr),
            patch("algotrader.execution.main.check_daily_loss"),
            patch.dict(os.environ, {"ACCOUNT_TYPE": "PAPER"}),
        ):
            # Should complete without raising
            s6_main.run("test-run-id")

        mock_ibkr.disconnect.assert_called_once()


class TestProcessSignal:
    def test_submits_order_for_valid_signal(self, patched_env, mock_cfg, mock_session):
        signal = _make_approved_signal()
        mock_ibkr = MagicMock()
        mock_ibkr.submit_order.return_value = MagicMock(order=MagicMock(orderId=42))

        tracker = MagicMock()
        tracker._pending = {}

        with (
            patch("algotrader.execution.main.get_limit_price", return_value=150.0),
            patch("algotrader.execution.main.compute_position_size", return_value=(1500.0, 10)),
            patch("algotrader.execution.main.run_per_signal_guards", return_value=(1500.0, 10)),
            patch("algotrader.execution.main.build_contract", return_value=MagicMock()),
            patch("algotrader.execution.main.build_order", return_value=MagicMock()),
            patch("algotrader.execution.main.write_order", return_value=MagicMock(id=1)),
            patch("algotrader.execution.main.update_order_submitted"),
            patch("algotrader.execution.main.mark_signal_executed"),
            patch("algotrader.execution.main.write_event"),
        ):
            s6_main._process_signal(
                signal=signal,
                session=mock_session,
                cfg=mock_cfg,
                ibkr=mock_ibkr,
                account_type="PAPER",
                account_equity=100_000.0,
                run_id="run-1",
                tracker=tracker,
            )

        mock_ibkr.submit_order.assert_called_once()

    def test_skips_signal_on_risk_breach(self, patched_env, mock_cfg, mock_session):
        signal = _make_approved_signal()
        mock_ibkr = MagicMock()
        tracker = MagicMock()
        tracker._pending = {}

        with (
            patch("algotrader.execution.main.get_limit_price", return_value=150.0),
            patch("algotrader.execution.main.compute_position_size", return_value=(1500.0, 10)),
            patch("algotrader.execution.main.run_per_signal_guards",
                  side_effect=RiskBreach("max positions hit")),
        ):
            # Should not raise — guard denies are caught and signal is skipped
            s6_main._process_signal(
                signal=signal,
                session=mock_session,
                cfg=mock_cfg,
                ibkr=mock_ibkr,
                account_type="PAPER",
                account_equity=100_000.0,
                run_id="run-1",
                tracker=tracker,
            )

        mock_ibkr.submit_order.assert_not_called()

    def test_skips_signal_on_data_error(self, patched_env, mock_cfg, mock_session):
        signal = _make_approved_signal()
        mock_ibkr = MagicMock()
        tracker = MagicMock()
        tracker._pending = {}

        with patch("algotrader.execution.main.get_limit_price",
                   side_effect=DataError("parquet not found")):
            s6_main._process_signal(
                signal=signal,
                session=mock_session,
                cfg=mock_cfg,
                ibkr=mock_ibkr,
                account_type="PAPER",
                account_equity=100_000.0,
                run_id="run-1",
                tracker=tracker,
            )

        mock_ibkr.submit_order.assert_not_called()

    def test_writes_rejected_event_on_submission_failure(
        self, patched_env, mock_cfg, mock_session
    ):
        signal = _make_approved_signal()
        mock_ibkr = MagicMock()
        mock_ibkr.submit_order.side_effect = ExecutionError("TWS rejected")
        tracker = MagicMock()
        tracker._pending = {}

        with (
            patch("algotrader.execution.main.get_limit_price", return_value=150.0),
            patch("algotrader.execution.main.compute_position_size", return_value=(1500.0, 10)),
            patch("algotrader.execution.main.run_per_signal_guards", return_value=(1500.0, 10)),
            patch("algotrader.execution.main.build_contract", return_value=MagicMock()),
            patch("algotrader.execution.main.build_order", return_value=MagicMock()),
            patch("algotrader.execution.main.write_order", return_value=MagicMock(id=1)),
            patch("algotrader.execution.main.write_event") as mock_write_event,
            patch("algotrader.execution.main.update_order_submitted"),
            patch("algotrader.execution.main.mark_signal_executed"),
        ):
            s6_main._process_signal(
                signal=signal,
                session=mock_session,
                cfg=mock_cfg,
                ibkr=mock_ibkr,
                account_type="PAPER",
                account_equity=100_000.0,
                run_id="run-1",
                tracker=tracker,
            )

        event_types = [c.kwargs["event_type"] for c in mock_write_event.call_args_list]
        assert EventType.ORDER_REJECTED in event_types


class TestEmitHalt:
    def test_writes_critical_halt_event(self, patched_env, mock_cfg, mock_session):
        with patch("algotrader.execution.main.write_event") as mock_write_event:
            s6_main._emit_halt("run-1", "test halt message")

        call_kwargs = mock_write_event.call_args.kwargs
        assert call_kwargs["event_type"] == EventType.RISK_HALT
        assert call_kwargs["severity"].value == "CRITICAL"

    def test_does_not_raise_if_db_fails(self, patched_env, mock_cfg):
        with patch("algotrader.execution.main.get_session") as mock_gs:
            mock_gs.side_effect = RuntimeError("DB down")
            # Should log the error but not propagate
            s6_main._emit_halt("run-1", "test halt")
