"""
Daily returns parquet computation.

Output: data/processed/returns/<DATE>.parquet  (§4.4 schema)

Columns:
  ticker      STRING  (index)
  date        DATE
  ret_1d      FLOAT64  log return
  ret_5d      FLOAT64  log return
  volume      INT64
  avg_vol_30  FLOAT64
  turnover    FLOAT64  volume / shares_outstanding
  sector_etf  STRING

Log returns are used (ln P_t / P_{t-1}) because they are time-additive
and are what the OU/stat-arb fitting in S3 expects.

Ticker metadata (shares outstanding, sector) is fetched once per run via
a single yfinance .info call per ticker, cached in a dict to avoid
redundant network round-trips.
"""

from __future__ import annotations

import datetime
import math
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf

from shared.config_loader import AppConfig
from shared.exceptions import DataError
from shared.logger import get_logger

log = get_logger(__name__)

_AVG_VOL_LOOKBACK: int = 30


def compute_and_write_returns(
    tickers: list[str],
    cfg: AppConfig,
    today: datetime.date,
) -> Path:
    """
    Build and persist the daily returns parquet for *today*.

    Only tickers that passed OHLCV validation are passed in. Skips the
    write entirely (idempotent) if the file already exists for today —
    this prevents re-runs from overwriting a parquet S3 may already be
    reading.

    Raises:
        DataError: If no tickers could produce a return row for today.
    """
    ohlcv_dir = Path(cfg.system.data_dir_ssd) / "processed" / "ohlcv"
    returns_dir = Path(cfg.system.data_dir_ssd) / "processed" / "returns"
    returns_dir.mkdir(parents=True, exist_ok=True)

    out_path = returns_dir / f"{today.isoformat()}.parquet"
    if out_path.exists():
        log.warning("s2.returns.already_exists", path=str(out_path))
        return out_path

    # Prefetch all ticker metadata in one pass so we hit yfinance once per
    # ticker, not twice (once for shares, once for sector).
    metadata = _prefetch_ticker_metadata(tickers, cfg)

    rows: list[dict] = []
    for ticker in tickers:
        parquet_path = ohlcv_dir / f"{ticker}.parquet"
        if not parquet_path.exists():
            log.warning("s2.returns.missing_ohlcv", ticker=ticker)
            continue

        df = pd.read_parquet(parquet_path, engine="pyarrow")
        df.index = pd.to_datetime(df.index).normalize()
        df = df.sort_index()

        row = _build_return_row(ticker, df, today, metadata)
        if row is not None:
            rows.append(row)

    if not rows:
        raise DataError(
            f"No return rows could be produced for {today}. "
            "All valid tickers are missing today's OHLCV data."
        )

    returns_df = (
        pd.DataFrame(rows)
        .set_index("ticker")
        .astype(
            {
                "ret_1d": "float64",
                "ret_5d": "float64",
                "volume": "int64",
                "avg_vol_30": "float64",
                "turnover": "float64",
                "sector_etf": "string",
            }
        )
    )
    returns_df.to_parquet(out_path, engine="pyarrow", index=True)
    log.info("s2.returns.written", path=str(out_path), rows=len(returns_df))
    return out_path


def _build_return_row(
    ticker: str,
    df: pd.DataFrame,
    today: datetime.date,
    metadata: dict[str, dict],
) -> Optional[dict]:
    """
    Compute one returns row for *ticker* on *today*.

    Returns None if today's row is absent from the OHLCV data.
    """
    today_ts = pd.Timestamp(today)
    if today_ts not in df.index:
        log.warning("s2.returns.no_today_row", ticker=ticker, date=str(today))
        return None

    today_idx = df.index.get_loc(today_ts)

    def _log_ret(n: int) -> float:
        if today_idx < n:
            return float("nan")
        p_now = df.iloc[today_idx]["adj_close"]
        p_prev = df.iloc[today_idx - n]["adj_close"]
        if p_prev <= 0 or p_now <= 0:
            return float("nan")
        return math.log(p_now / p_prev)

    volume_today = int(df.iloc[today_idx]["volume"])
    lookback_start = max(0, today_idx - _AVG_VOL_LOOKBACK + 1)
    avg_vol_30 = float(df.iloc[lookback_start : today_idx + 1]["volume"].mean())

    meta = metadata.get(ticker, {})
    shares_out = meta.get("shares_outstanding")
    turnover = (
        volume_today / shares_out
        if shares_out and shares_out > 0
        else float("nan")
    )

    return {
        "ticker": ticker,
        "date": today,
        "ret_1d": _log_ret(1),
        "ret_5d": _log_ret(5),
        "volume": volume_today,
        "avg_vol_30": avg_vol_30,
        "turnover": turnover,
        "sector_etf": meta.get("sector_etf", ""),
    }


def _prefetch_ticker_metadata(
    tickers: list[str],
    cfg: AppConfig,
) -> dict[str, dict]:
    """
    Fetch shares_outstanding and sector_etf for every ticker in one pass.

    Builds the sector→ETF lookup from universe.yaml so we never hardcode
    sector strings in code. Falls back to empty strings on any failure.
    """
    sector_etf_map: dict[str, str] = {
        k.replace(" ", "_"): v
        for k, v in cfg.universe.sector_etf_map.items()
    }
    result: dict[str, dict] = {}

    for ticker in tickers:
        try:
            info = yf.Ticker(ticker).info
            raw_sector = info.get("sector", "")
            normalised_sector = raw_sector.replace(" ", "_")
            result[ticker] = {
                "shares_outstanding": float(info.get("sharesOutstanding") or 0) or None,
                "sector_etf": sector_etf_map.get(normalised_sector, ""),
            }
        except Exception as exc:
            log.warning("s2.metadata.error", ticker=ticker, error=str(exc))
            result[ticker] = {"shares_outstanding": None, "sector_etf": ""}

    return result
