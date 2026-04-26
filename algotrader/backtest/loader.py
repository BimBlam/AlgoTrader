"""
algotrader.backtest/loader.py

Reads the processed returns parquets written by S2 and returns a single
multi-index DataFrame (date × ticker) with the columns S4 needs.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import pandas as pd

from algotrader.shared.exceptions import DataError
from algotrader.shared.logger import get_logger

log = get_logger(__name__)


def load_returns_history(cfg) -> pd.DataFrame:
    """
    Scan all returns parquets under data/processed/returns/ and concatenate
    into a single DataFrame indexed by (date, ticker).

    Returns
    -------
    pd.DataFrame
        Columns: ret1d, ret5d, volume, avg_vol30, turnover, sector_etf
        Index:   MultiIndex[date (datetime.date), ticker (str)]

    Raises
    ------
    DataError
        If no parquet files are found or if the combined frame is empty.
    """
    returns_dir = Path(cfg.system.data_dir_ssd) / "processed" / "returns"
    parquet_files = sorted(returns_dir.glob("*.parquet"))

    if not parquet_files:
        raise DataError(
            f"No returns parquets found in {returns_dir}. "
            "Ensure S2 has completed at least one ingest run."
        )

    frames = []
    for fp in parquet_files:
        try:
            df = pd.read_parquet(fp)
            frames.append(df)
        except Exception as exc:
            # A single corrupt file is a warning; we proceed with the rest.
            log.warning("returns_parquet_unreadable", path=str(fp), error=str(exc))

    if not frames:
        raise DataError("All returns parquets were unreadable.")

    combined = pd.concat(frames)

    # Normalise index: S2 writes ticker as index column named "ticker",
    # date as a column named "date". Reconstruct MultiIndex.
    if not isinstance(combined.index, pd.MultiIndex):
        if "date" in combined.columns and "ticker" in combined.columns:
            combined = combined.set_index(["date", "ticker"])
        elif "date" in combined.columns:
            combined = combined.reset_index().set_index(["date", "ticker"])
        else:
            raise DataError(
                "Returns parquets do not have expected date/ticker index structure."
            )

    combined.index.names = ["date", "ticker"]

    # Enforce date type – S2 may write dates as strings on some platforms.
    if not isinstance(combined.index.get_level_values("date")[0], datetime.date):
        dates = pd.to_datetime(
            combined.index.get_level_values("date")
        ).date
        combined.index = pd.MultiIndex.from_arrays(
            [dates, combined.index.get_level_values("ticker")],
            names=["date", "ticker"],
        )

    # Tickers must be uppercase per spec.
    tickers = combined.index.get_level_values("ticker").str.upper()
    combined.index = pd.MultiIndex.from_arrays(
        [combined.index.get_level_values("date"), tickers],
        names=["date", "ticker"],
    )

    combined = combined.sort_index()
    log.info(
        "returns_loaded",
        n_dates=len(combined.index.get_level_values("date").unique()),
        n_tickers=len(combined.index.get_level_values("ticker").unique()),
    )
    return combined
