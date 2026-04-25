"""
VIX regime classification.

Regimes are derived by comparing today's VIX close to its 50-day SMA:
  LOW_VOL   : VIX < SMA
  MED_VOL   : SMA <= VIX < SMA * 1.20  (within 20% above the SMA)
  HIGH_VOL  : SMA * 1.20 <= VIX < SMA * 1.50
  EXTREME   : VIX >= SMA * 1.50

These thresholds map to the strategy preference table in §5.4:
  low_vol_strategy  → stat_arb  (mean reversion reliable when VIX stable)
  med_vol_strategy  → reversal  (short-horizon reversal survives mild vol)
  HIGH_VOL          → reduce positions by high_vol_reduce_pct
  EXTREME           → halt if extreme_vol_halt=True

VIX data is read from the OHLCV parquet for ticker 'VIX' (or '^VIX'
depending on the yfinance download; S2 normalises to 'VIX').
"""
import datetime
import pathlib
from typing import Literal

import pandas as pd

from shared.logger import get_logger

log = get_logger(__name__)

RegimeLabel = Literal["LOW_VOL", "MED_VOL", "HIGH_VOL", "EXTREME"]

# Multipliers relative to the VIX SMA that define regime boundaries.
_MED_UPPER = 1.20
_HIGH_UPPER = 1.50


def classify_regime(date: datetime.date, cfg) -> str:
    """
    Classify today's volatility regime from VIX data.

    Falls back to 'MED_VOL' if VIX data is unavailable — the least
    aggressive default that neither halts trading nor over-concentrates
    into one strategy.
    """
    strategy_cfg = cfg.strategy_params
    lookback = int(strategy_cfg.regime_combo.vix_sma_lookback)

    vix_close, vix_sma = _read_vix(date, cfg, lookback)

    if vix_close is None or vix_sma is None:
        log.warning("vix_unavailable_defaulting_med_vol", date=str(date))
        return "MED_VOL"

    if vix_sma <= 0:
        log.warning("vix_sma_zero_defaulting_med_vol", date=str(date))
        return "MED_VOL"

    log.info("vix_regime_inputs", vix_close=round(vix_close, 2), vix_sma=round(vix_sma, 2), date=str(date))

    if vix_close < vix_sma:
        return "LOW_VOL"
    elif vix_close < vix_sma * _MED_UPPER:
        return "MED_VOL"
    elif vix_close < vix_sma * _HIGH_UPPER:
        return "HIGH_VOL"
    else:
        return "EXTREME"


def _read_vix(date: datetime.date, cfg, lookback: int) -> tuple[float | None, float | None]:
    """
    Read VIX close and its `lookback`-day SMA from the OHLCV parquet.

    Returns (None, None) on any I/O or schema failure so the caller
    can degrade gracefully.
    """
    data_dir = pathlib.Path(cfg.system.data_dir_ssd)

    # S2 stores the VIX index under the ticker it downloads from yfinance.
    # Try 'VIX' first (cleaned ticker), then '^VIX' as a fallback.
    for ticker in ("VIX", "^VIX"):
        path = data_dir / "processed" / "ohlcv" / f"{ticker}.parquet"
        if path.exists():
            return _parse_vix(path, date, lookback)

    return None, None


def _parse_vix(
    path: pathlib.Path,
    date: datetime.date,
    lookback: int,
) -> tuple[float | None, float | None]:
    """Parse VIX close and SMA from a parquet file."""
    try:
        df = pd.read_parquet(path)
        df.index = pd.to_datetime(df.index)
        df = df.sort_index()

        # Get all rows up to and including today
        df_to_date = df[df.index.date <= date]
        if df_to_date.empty:
            return None, None

        today_row = df_to_date[df_to_date.index.date == date]
        if today_row.empty:
            # Use the most recent available close if today is not yet written
            today_close = float(df_to_date["close"].iloc[-1])
        else:
            today_close = float(today_row["close"].iloc[0])

        # SMA computed on the last `lookback` rows (including today)
        recent = df_to_date.tail(lookback)
        if len(recent) < 2:
            return today_close, today_close  # flat regime when no history

        sma = float(recent["close"].mean())
        return today_close, sma

    except Exception as exc:
        log.warning("vix_parse_failed", path=str(path), error=str(exc))
        return None, None
