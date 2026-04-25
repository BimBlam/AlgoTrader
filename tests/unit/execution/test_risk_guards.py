"""tests/unit/s6/test_risk_guards.py"""
from __future__ import annotations

import datetime

import pytest
from freezegun import freeze_time

from algotrader.shared.exceptions import RiskBreach
from algotrader.shared.models import Position
from algotrader.execution.risk_guards import (
    check_daily_loss,
    check_extreme_vix,
    check_margin,
    check_market_hours,
    check_max_positions,
    check_total_exposure,
    clip_position_size,
    run_per_signal_guards,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _closed_position(pnl: float, account_type: str = "PAPER") -> Position:
    return Position(
        ticker="AAPL",
        side="BUY",
        entry_price=100.0,
        quantity=10,
        entry_time=datetime.datetime.now(tz=datetime.timezone.utc),
        exit_time=datetime.datetime.now(tz=datetime.timezone.utc),
        realised_pnl=pnl,
        status="CLOSED",
        account_type=account_type,
    )


def _open_position(entry_price: float = 100.0, quantity: int = 10, account_type: str = "PAPER") -> Position:
    return Position(
        ticker="AAPL",
        side="BUY",
        entry_price=entry_price,
        quantity=quantity,
        entry_time=datetime.datetime.now(tz=datetime.timezone.utc),
        status="OPEN",
        account_type=account_type,
    )


# ── Guard 1: daily loss ───────────────────────────────────────────────────────

class TestCheckDailyLoss:
    def test_passes_when_pnl_above_limit(self, mock_session, mock_cfg):
        mock_session.query.return_value.filter.return_value.all.return_value = [
            _closed_position(-500.0)
        ]
        # Should not raise
        check_daily_loss(mock_session, mock_cfg, "PAPER")

    def test_raises_when_pnl_below_limit(self, mock_session, mock_cfg):
        mock_session.query.return_value.filter.return_value.all.return_value = [
            _closed_position(-2000.0)
        ]
        with pytest.raises(RiskBreach, match="Daily loss limit breached"):
            check_daily_loss(mock_session, mock_cfg, "PAPER")

    def test_passes_when_no_closed_positions(self, mock_session, mock_cfg):
        mock_session.query.return_value.filter.return_value.all.return_value = []
        check_daily_loss(mock_session, mock_cfg, "PAPER")

    def test_exactly_at_limit_does_not_halt(self, mock_session, mock_cfg):
        # pnl = -max_daily_loss_usd is NOT a breach (strict less-than)
        mock_session.query.return_value.filter.return_value.all.return_value = [
            _closed_position(-1500.0)
        ]
        check_daily_loss(mock_session, mock_cfg, "PAPER")


# ── Guard 2: max positions ────────────────────────────────────────────────────

class TestCheckMaxPositions:
    def test_passes_when_under_limit(self, mock_session, mock_cfg, sample_signal):
        mock_session.query.return_value.filter.return_value.count.return_value = 10
        check_max_positions(mock_session, mock_cfg, sample_signal, "PAPER")

    def test_raises_when_at_limit(self, mock_session, mock_cfg, sample_signal):
        mock_session.query.return_value.filter.return_value.count.return_value = 40
        with pytest.raises(RiskBreach, match="Max open positions"):
            check_max_positions(mock_session, mock_cfg, sample_signal, "PAPER")

    def test_raises_when_over_limit(self, mock_session, mock_cfg, sample_signal):
        mock_session.query.return_value.filter.return_value.count.return_value = 45
        with pytest.raises(RiskBreach):
            check_max_positions(mock_session, mock_cfg, sample_signal, "PAPER")


# ── Guard 3: clip position size ───────────────────────────────────────────────

class TestClipPositionSize:
    def test_no_clip_when_under_max(self, mock_cfg):
        result = clip_position_size(3000.0, mock_cfg, "AAPL")
        assert result == 3000.0

    def test_clips_to_max_when_over(self, mock_cfg):
        result = clip_position_size(8000.0, mock_cfg, "AAPL")
        assert result == 5000.0

    def test_no_clip_when_exactly_at_max(self, mock_cfg):
        result = clip_position_size(5000.0, mock_cfg, "AAPL")
        assert result == 5000.0


# ── Guard 4: total exposure ───────────────────────────────────────────────────

class TestCheckTotalExposure:
    def test_passes_within_limit(self, mock_session, mock_cfg, sample_signal):
        # current: 2 positions × $100 × 10 shares = $2000; adding $3000 = $5000 < $50000
        mock_session.query.return_value.filter.return_value.all.return_value = [
            _open_position(100.0, 10),
            _open_position(100.0, 10),
        ]
        check_total_exposure(mock_session, mock_cfg, sample_signal, 3000.0, "PAPER")

    def test_raises_when_would_exceed_limit(self, mock_session, mock_cfg, sample_signal):
        # current: 490 × $100 = $49000; adding $2000 = $51000 > $50000
        mock_session.query.return_value.filter.return_value.all.return_value = [
            _open_position(100.0, 490),
        ]
        with pytest.raises(RiskBreach, match="Total exposure limit exceeded"):
            check_total_exposure(mock_session, mock_cfg, sample_signal, 2000.0, "PAPER")

    def test_passes_when_no_open_positions(self, mock_session, mock_cfg, sample_signal):
        mock_session.query.return_value.filter.return_value.all.return_value = []
        check_total_exposure(mock_session, mock_cfg, sample_signal, 5000.0, "PAPER")


# ── Guard 5: extreme VIX ──────────────────────────────────────────────────────

class TestCheckExtremeVix:
    def test_passes_when_halt_disabled(self, mock_cfg, sample_signal):
        sample_signal.regime = "EXTREME"
        mock_cfg.risk.extreme_vol_halt = False
        check_extreme_vix(sample_signal, mock_cfg)  # no exception

    def test_passes_when_regime_not_extreme(self, mock_cfg, sample_signal):
        sample_signal.regime = "HIGH_VOL"
        mock_cfg.risk.extreme_vol_halt = True
        check_extreme_vix(sample_signal, mock_cfg)  # no exception

    def test_raises_when_halt_enabled_and_regime_extreme(self, mock_cfg, sample_signal):
        sample_signal.regime = "EXTREME"
        mock_cfg.risk.extreme_vol_halt = True
        with pytest.raises(RiskBreach, match="Extreme VIX halt"):
            check_extreme_vix(sample_signal, mock_cfg)


# ── Guard 6: market hours ─────────────────────────────────────────────────────

class TestCheckMarketHours:
    @freeze_time("2026-03-27 14:00:00", tz_offset=0)  # 14:00 UTC = 10:00 ET
    def test_passes_during_market_hours(self):
        check_market_hours()  # should not raise

    @freeze_time("2026-03-27 13:25:00", tz_offset=0)  # 13:25 UTC = 09:25 ET (boundary)
    def test_passes_at_open_boundary(self):
        check_market_hours()

    @freeze_time("2026-03-27 19:55:00", tz_offset=0)  # 19:55 UTC = 15:55 ET (boundary)
    def test_passes_at_close_boundary(self):
        check_market_hours()

    @freeze_time("2026-03-27 12:00:00", tz_offset=0)  # 12:00 UTC = 08:00 ET
    def test_raises_before_market_open(self):
        with pytest.raises(RiskBreach, match="market hours"):
            check_market_hours()

    @freeze_time("2026-03-27 21:00:00", tz_offset=0)  # 21:00 UTC = 17:00 ET
    def test_raises_after_market_close(self):
        with pytest.raises(RiskBreach, match="market hours"):
            check_market_hours()


# ── Guard 7: margin ───────────────────────────────────────────────────────────

class TestCheckMargin:
    def test_passes_when_margin_ok(self, mock_ibkr, sample_signal):
        mock_ibkr.check_margin_ok.return_value = True
        check_margin(mock_ibkr, sample_signal, 10, 150.0)  # no exception

    def test_raises_when_insufficient_margin(self, mock_ibkr, sample_signal):
        mock_ibkr.check_margin_ok.return_value = False
        with pytest.raises(RiskBreach, match="Insufficient margin"):
            check_margin(mock_ibkr, sample_signal, 10, 150.0)


# ── Combined pre-flight ───────────────────────────────────────────────────────

class TestRunPerSignalGuards:
    @freeze_time("2026-03-27 14:00:00", tz_offset=0)  # 10:00 ET — inside market hours
    def test_all_guards_pass(self, mock_session, mock_cfg, mock_ibkr, sample_signal):
        mock_session.query.return_value.filter.return_value.count.return_value = 0
        mock_session.query.return_value.filter.return_value.all.return_value = []

        target_usd, qty = run_per_signal_guards(
            signal=sample_signal,
            session=mock_session,
            cfg=mock_cfg,
            ibkr_client=mock_ibkr,
            account_type="PAPER",
            target_usd=1500.0,
            quantity=10,
            limit_price=150.0,
        )
        assert qty == 10
        assert target_usd == 1500.0

    @freeze_time("2026-03-27 14:00:00", tz_offset=0)
    def test_clip_reduces_quantity(self, mock_session, mock_cfg, mock_ibkr, sample_signal):
        mock_session.query.return_value.filter.return_value.count.return_value = 0
        mock_session.query.return_value.filter.return_value.all.return_value = []
        # target_usd=8000 > max_position_usd=5000; should clip to 5000
        target_usd, qty = run_per_signal_guards(
            signal=sample_signal,
            session=mock_session,
            cfg=mock_cfg,
            ibkr_client=mock_ibkr,
            account_type="PAPER",
            target_usd=8000.0,
            quantity=53,
            limit_price=150.0,
        )
        assert target_usd == 5000.0
        assert qty == 33  # floor(5000 / 150)

    @freeze_time("2026-03-27 14:00:00", tz_offset=0)
    def test_raises_when_max_positions_hit(self, mock_session, mock_cfg, mock_ibkr, sample_signal):
        mock_session.query.return_value.filter.return_value.count.return_value = 40
        with pytest.raises(RiskBreach, match="Max open positions"):
            run_per_signal_guards(
                signal=sample_signal,
                session=mock_session,
                cfg=mock_cfg,
                ibkr_client=mock_ibkr,
                account_type="PAPER",
                target_usd=1500.0,
                quantity=10,
                limit_price=150.0,
            )
