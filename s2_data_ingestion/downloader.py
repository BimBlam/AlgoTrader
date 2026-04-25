"""
OHLCV downloader.

One parquet file per ticker at data/processed/ohlcv/<TICKER>.parquet.
Appends only rows not already present (never overwrites). Uses
yfinance auto_adjust=True so Close is already split+dividend adjusted —
adj_close is stored as a copy of close per §4.4.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

from shared.config_loader import AppConfig
from shared.exceptions import DataError
from shared.logger import get_logger

log = get_logger(__name__)

_OHLCV_COLUMNS = ["open", "high", "low", "close", "volume", "adj_close"]
# On cold start, fetch 2 years so S3/S4 have sufficient history immediately.
_COLD_START_DAYS = 730
# Overlap on warm fetch to absorb retroactive split/dividend adjustments.
_WARM_OVERLAP_DAYS = 5


def download_and_persist_ohlcv(
    ticker: str,
    cfg: AppConfig,
    today: datetime.date,
) -> pd.DataFrame:
    """
    Download OHLCV for *ticker* via yfinance and append new rows to its parquet.

    Returns the full combined DataFrame (existing + new rows) after writing.

    Raises:
        DataError: If yfinance returns an empty response for the ticker.
    """
    ohlcv_dir = Path(cfg.system.data_dir_ssd) / "processed" / "ohlcv"
    ohlcv_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = ohlcv_dir / f"{ticker}.parquet"

    existing_df = _load_existing(parquet_path)
    fetch_start = _determine_fetch_start(existing_df, today)

    raw = yf.download(
        ticker,
        start=fetch_start.isoformat(),
        # end is exclusive in yfinance; +1 day captures today's close.
        end=(today + datetime.timedelta(days=1)).isoformat(),
        auto_adjust=True,
        progress=False,
        actions=False,
    )

    if raw.empty:
        raise DataError(
            f"yfinance returned no data for {ticker} "
            f"(start={fetch_start}, end={today})."
        )

    new_df = _normalise(raw)

    if existing_df.empty:
        combined = new_df
    else:
        new_rows = new_df[~new_df.index.isin(existing_df.index)]
        combined = pd.concat([existing_df, new_rows]).sort_index()

    combined.to_parquet(parquet_path, engine="pyarrow", index=True)
    log.debug(
        "s2.ohlcv.written",
        ticker=ticker,
        rows=len(combined),
        path=str(parquet_path),
    )
    return combined


def _load_existing(path: Path) -> pd.DataFrame:
    """Return existing parquet as a DataFrame, or empty if not yet created."""
    if path.exists():
        df = pd.read_parquet(path, engine="pyarrow")
        df.index = pd.to_datetime(df.index).normalize()
        return df
    return pd.DataFrame(columns=_OHLCV_COLUMNS)


def _determine_fetch_start(existing_df: pd.DataFrame, today: datetime.date) -> datetime.date:
    """
    Cold start: fetch full 2-year history.
    Warm: overlap by 5 days to pick up retroactive corporate-action adjustments.
    """
    if existing_df.empty:
        return today - datetime.timedelta(days=_COLD_START_DAYS)
    last_date: datetime.date = existing_df.index.max().date()
    return last_date - datetime.timedelta(days=_WARM_OVERLAP_DAYS)


def _normalise(raw: pd.DataFrame) -> pd.DataFrame:
    """
    Map yfinance column names → §4.4 canonical schema and enforce dtypes.

    With auto_adjust=True, yfinance applies split/dividend adjustments to all
    OHLC columns in-place. Storing close as adj_close is therefore correct.
    """
    # yfinance returns MultiIndex columns when given a list of tickers;
    # single-ticker downloads may also return MultiIndex — flatten either way.
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    col_map = {
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    }
    df = raw.rename(columns=col_map)[list(col_map.values())].copy()
    df["adj_close"] = df["close"]
    df.index = pd.to_datetime(df.index).normalize()
    df.index.name = "date"

    for col in ("open", "high", "low", "close", "adj_close"):
        df[col] = df[col].astype("float64")
    df["volume"] = df["volume"].astype("int64")
    return df
