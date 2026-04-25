"""
OHLCV data-quality validation.

Three rules per the S2 contract:
  1. No negative prices in any OHLC column.
  2. No zero-volume trading sessions.
  3. No gap > 3 consecutive NYSE trading days.

Returns a list of issue strings; empty list means the ticker is clean.
The NYSE calendar (via pandas_market_calendars) is used for gap detection
so weekends and public holidays are not counted.
"""

from __future__ import annotations

import datetime

import pandas as pd
import pandas_market_calendars as mcal

from algotrader.shared.logger import get_logger

log = get_logger(__name__)

_NYSE = mcal.get_calendar("NYSE")
_MAX_GAP_DAYS: int = 3


def validate_ohlcv(df: pd.DataFrame, ticker: str) -> list[str]:
    """
    Run all three quality checks on *ticker*'s OHLCV DataFrame.

    Args:
        df:     DataFrame indexed by date with §4.4 columns.
        ticker: Uppercase ticker string (used for log and issue context).

    Returns:
        List of human-readable issue descriptions. Empty → data is valid.
    """
    if df.empty:
        return [f"{ticker}: DataFrame is empty."]

    issues: list[str] = []
    issues.extend(_check_negative_prices(df, ticker))
    issues.extend(_check_zero_volume(df, ticker))
    issues.extend(_check_trading_day_gaps(df, ticker))
    return issues


def _check_negative_prices(df: pd.DataFrame, ticker: str) -> list[str]:
    price_cols = ["open", "high", "low", "close", "adj_close"]
    mask = (df[price_cols] < 0).any(axis=1)
    if mask.any():
        bad = [str(d.date()) if hasattr(d, "date") else str(d) for d in df.index[mask]]
        return [f"{ticker}: Negative prices on {bad}."]
    return []


def _check_zero_volume(df: pd.DataFrame, ticker: str) -> list[str]:
    """
    Zero volume always indicates a feed error, not a genuine trading halt.
    Even halted stocks report fractional odd-lot volume in practice.
    """
    mask = df["volume"] == 0
    if mask.any():
        bad = [str(d.date()) if hasattr(d, "date") else str(d) for d in df.index[mask]]
        return [f"{ticker}: Zero-volume sessions on {bad}."]
    return []


def _check_trading_day_gaps(df: pd.DataFrame, ticker: str) -> list[str]:
    if len(df) < 2:
        return []

    start = df.index.min()
    end = df.index.max()
    # Normalise to date for calendar lookup.
    start_d = start.date() if hasattr(start, "date") else start
    end_d = end.date() if hasattr(end, "date") else end

    schedule = _NYSE.schedule(
        start_date=start_d.isoformat(),
        end_date=end_d.isoformat(),
    )
    all_trading_days = {d.date() for d in schedule.index}
    present_days = {
        idx.date() if hasattr(idx, "date") else idx for idx in df.index
    }
    missing = sorted(all_trading_days - present_days)
    if not missing:
        return []

    gaps = _find_consecutive_runs(sorted(all_trading_days), missing)
    long_gaps = [g for g in gaps if len(g) > _MAX_GAP_DAYS]
    return [
        f"{ticker}: Gap of {len(g)} consecutive trading days starting {g[0]}."
        for g in long_gaps
    ]


def _find_consecutive_runs(
    all_days: list[datetime.date],
    missing: list[datetime.date],
) -> list[list[datetime.date]]:
    """
    Group missing dates into runs of consecutive trading days.

    Two missing days are 'consecutive' if no trading day between them
    is present in the data — i.e., they are adjacent in the NYSE calendar.
    """
    missing_set = set(missing)
    runs: list[list[datetime.date]] = []
    current: list[datetime.date] = []

    for d in all_days:
        if d in missing_set:
            current.append(d)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs
