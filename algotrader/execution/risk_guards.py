"""
algotrader.execution/risk_guards.py

Pre-flight risk guard battery (§7.1).

Guards
------
1. check_daily_loss       — realised P&L today < -max_daily_loss_usd → HALT
2. check_max_positions    — open positions >= max_positions_open      → deny
3. clip_position_size     — target > max_position_usd                 → clip + WARNING (never raises)
4. check_total_exposure   — current + new > max_total_exposure_usd    → deny
5. check_extreme_vix      — cfg.risk.extreme_vol_halt AND regime=EXTREME → deny
6. check_market_hours     — outside 09:25–15:55 ET                    → deny
7. check_margin           — IBKR reports insufficient margin           → deny

Guard 1 is HALT-class: it is called *once* before the signal loop in main.py and
its RiskBreach is allowed to propagate (triggering system HALT).

Guards 2–7 are called per-signal via run_per_signal_guards(); their RiskBreach is
caught by the caller, the signal is denied, and execution continues.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from algotrader.shared.config_loader import AppConfig
from algotrader.shared.constants import PositionStatus
from algotrader.shared.exceptions import RiskBreach
from algotrader.shared.logger import get_logger
from algotrader.shared.models import Position, Signal

log = get_logger(__name__)

_ET = ZoneInfo("America/New_York")
# Inclusive bounds: orders may be submitted 09:25–15:55 ET.
_OPEN_MINUTES  = 9 * 60 + 25
_CLOSE_MINUTES = 15 * 60 + 55


def _et_now() -> datetime:
    return datetime.now(tz=_ET)


# ── Individual guards ─────────────────────────────────────────────────────────

def check_daily_loss(
    session: Session,
    cfg: AppConfig,
    account_type: str,
) -> None:
    """
    Guard 1 (HALT): raise RiskBreach if today's realised P&L is below the
    configured daily loss limit.
    """
    today_start = datetime.now(tz=timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    positions_closed_today = (
        session.query(Position)
        .filter(
            Position.status == PositionStatus.CLOSED.value,
            Position.account_type == account_type,
            Position.exit_time >= today_start,
        )
        .all()
    )
    pnl_today = sum(p.realised_pnl or 0.0 for p in positions_closed_today)
    if pnl_today < -cfg.risk.max_daily_loss_usd:
        raise RiskBreach(
            f"Daily loss limit breached: realised_pnl_today={pnl_today:.2f} "
            f"< -{cfg.risk.max_daily_loss_usd:.2f}."
        )


def check_max_positions(
    session: Session,
    cfg: AppConfig,
    signal: Signal,
    account_type: str,
) -> None:
    """
    Guard 2: deny new positions when the open-position count is at the limit.
    Close signals (covered by the strategy exiting) are always allowed.
    """
    open_count = (
        session.query(Position)
        .filter(
            Position.status == PositionStatus.OPEN.value,
            Position.account_type == account_type,
        )
        .count()
    )
    if open_count >= cfg.risk.max_positions_open:
        raise RiskBreach(
            f"Max open positions reached ({open_count}/{cfg.risk.max_positions_open}). "
            f"Denied signal for {signal.ticker}."
        )


def clip_position_size(target_usd: float, cfg: AppConfig, ticker: str) -> float:
    """
    Guard 3: clip *target_usd* to max_position_usd; emit a WARNING if clipped.
    Returns the (possibly clipped) value.  Never raises.
    """
    if target_usd > cfg.risk.max_position_usd:
        log.warning(
            "position_size_clipped",
            ticker=ticker,
            original=round(target_usd, 2),
            clipped=cfg.risk.max_position_usd,
        )
        return cfg.risk.max_position_usd
    return target_usd


def check_total_exposure(
    session: Session,
    cfg: AppConfig,
    signal: Signal,
    target_usd: float,
    account_type: str,
) -> None:
    """
    Guard 4: deny if adding *target_usd* would exceed the total exposure limit.
    """
    open_positions = (
        session.query(Position)
        .filter(
            Position.status == PositionStatus.OPEN.value,
            Position.account_type == account_type,
        )
        .all()
    )
    current_exposure = sum(p.entry_price * p.quantity for p in open_positions)
    if current_exposure + target_usd > cfg.risk.max_total_exposure_usd:
        raise RiskBreach(
            f"Total exposure limit exceeded: current={current_exposure:.2f} "
            f"+ new={target_usd:.2f} > max={cfg.risk.max_total_exposure_usd:.2f}. "
            f"Denied signal for {signal.ticker}."
        )


def check_extreme_vix(signal: Signal, cfg: AppConfig) -> None:
    """
    Guard 5: deny all signals if extreme_vol_halt is enabled and this signal's
    regime is EXTREME.
    """
    if cfg.risk.extreme_vol_halt and signal.regime == "EXTREME":
        log.warning(
            "extreme_vix_halt_guard",
            ticker=signal.ticker,
            regime=signal.regime,
        )
        raise RiskBreach(
            f"Extreme VIX halt active. Denied signal for {signal.ticker} "
            f"(regime={signal.regime})."
        )


def check_market_hours() -> None:
    """
    Guard 6: deny if the current ET time is outside 09:25–15:55.
    """
    now_et = _et_now()
    current_minutes = now_et.hour * 60 + now_et.minute
    if not (_OPEN_MINUTES <= current_minutes <= _CLOSE_MINUTES):
        raise RiskBreach(
            f"Order submission outside market hours (09:25–15:55 ET). "
            f"Current ET time: {now_et.strftime('%H:%M')}."
        )


def check_margin(ibkr_client, signal: Signal, quantity: int, limit_price: float) -> None:
    """
    Guard 7: deny if IBKR reports insufficient margin for the proposed order.
    """
    if not ibkr_client.check_margin_ok(signal.ticker, quantity, limit_price):
        raise RiskBreach(
            f"Insufficient margin for {signal.ticker}: "
            f"quantity={quantity}, limit_price={limit_price:.2f}."
        )


# ── Combined per-signal pre-flight ────────────────────────────────────────────

def run_per_signal_guards(
    signal: Signal,
    session: Session,
    cfg: AppConfig,
    ibkr_client,
    account_type: str,
    target_usd: float,
    quantity: int,
    limit_price: float,
) -> tuple[float, int]:
    """
    Run guards 2–7 for a single signal.

    Returns the (possibly clipped) ``(target_usd, quantity)`` on success.
    Raises ``RiskBreach`` on any guard failure — the caller should catch this,
    log a warning, and skip to the next signal.

    Guard 1 (daily loss) is **not** called here; it is checked once before
    the signal loop in ``main.py``.
    """
    check_max_positions(session, cfg, signal, account_type)

    target_usd = clip_position_size(target_usd, cfg, signal.ticker)

    check_total_exposure(session, cfg, signal, target_usd, account_type)
    check_extreme_vix(signal, cfg)
    check_market_hours()

    # Recompute quantity after potential clip
    if target_usd < limit_price:
        raise RiskBreach(
            f"Clipped target_usd ({target_usd:.2f}) is less than limit_price "
            f"({limit_price:.2f}) for {signal.ticker} — cannot buy a fractional share."
        )
    quantity = math.floor(target_usd / limit_price)
    if quantity <= 0:
        raise RiskBreach(
            f"Computed quantity=0 for {signal.ticker} after sizing. Skipping."
        )

    check_margin(ibkr_client, signal, quantity, limit_price)

    return target_usd, quantity
