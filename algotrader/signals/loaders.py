"""
Data loaders for S3.

All I/O is isolated here so the compute modules (ou_model, stat_arb,
reversal, regime) stay pure and easily testable.
"""
import datetime
import pathlib

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from algotrader.shared.exceptions import DataError
from algotrader.shared.logger import get_logger
from algotrader.shared.models import OUParam, SentimentScore

log = get_logger(__name__)


def load_returns(date: datetime.date, cfg) -> pd.DataFrame:
    """
    Load the returns parquet for *date*.

    Returns a DataFrame indexed by ticker with columns from the parquet
    schema (ret_1d, ret_5d, volume, avg_vol_30, turnover, sector_etf).

    Raises DataError on missing file or schema mismatch — callers treat
    this as a terminal failure per spec §10 S3 failure mode.
    """
    data_dir = pathlib.Path(cfg.system.data_dir_ssd)
    path = data_dir / "processed" / "returns" / f"{date}.parquet"

    if not path.exists():
        raise DataError(f"Returns parquet not found: {path}")

    try:
        df = pd.read_parquet(path)
    except Exception as exc:
        raise DataError(f"Failed to read returns parquet {path}: {exc}") from exc

    _validate_returns_schema(df, path)
    df.index = df.index.str.upper()  # ensure uppercase tickers
    return df


def _validate_returns_schema(df: pd.DataFrame, path: pathlib.Path) -> None:
    """Raise DataError if required columns are absent."""
    required = {"ret_1d", "ret_5d", "volume", "avg_vol_30", "turnover", "sector_etf"}
    missing = required - set(df.columns)
    if missing:
        raise DataError(f"Returns parquet {path} is missing columns: {missing}")
    if df.empty:
        raise DataError(f"Returns parquet {path} contains no rows")


def load_sector_etf_returns(date: datetime.date, cfg) -> dict[str, float]:
    """
    Build a mapping {sector_etf_ticker: ret_1d} for all ETFs referenced
    in the returns parquet.

    ETF returns are read from the same returns parquet: ETF rows have a
    sector_etf value equal to their own ticker (set by S2). Falls back
    to the OHLCV parquet for each ETF if the parquet row is absent.

    Returns an empty dict if no ETF data is available — OU fitting will
    degrade gracefully (zero-beta residuals).
    """
    data_dir = pathlib.Path(cfg.system.data_dir_ssd)
    returns_path = data_dir / "processed" / "returns" / f"{date}.parquet"

    try:
        df = pd.read_parquet(returns_path)
    except Exception:
        log.warning("sector_etf_returns_unavailable", date=str(date))
        return {}

    df.index = df.index.str.upper()
    # ETFs appear as rows where the index ticker equals their sector_etf value
    etf_rows = df[df.index == df["sector_etf"]]
    result = etf_rows["ret_1d"].to_dict()

    if not result:
        # Fallback: scan individual OHLCV parquets for known ETF tickers
        etf_tickers = set(df["sector_etf"].dropna().unique())
        for ticker in etf_tickers:
            ohlcv_path = data_dir / "processed" / "ohlcv" / f"{ticker}.parquet"
            if ohlcv_path.exists():
                try:
                    ohlcv = pd.read_parquet(ohlcv_path)
                    ohlcv.index = pd.to_datetime(ohlcv.index)
                    row = ohlcv[ohlcv.index.date == date]
                    if not row.empty:
                        prev = ohlcv[ohlcv.index.date < date].tail(1)
                        if not prev.empty:
                            import numpy as np
                            result[ticker] = float(np.log(row["adj_close"].iloc[0] / prev["adj_close"].iloc[0]))
                except Exception:
                    log.warning("etf_ohlcv_fallback_failed", ticker=ticker, date=str(date))

    return result


def load_prior_ou_params(session: Session, today: datetime.date) -> dict[str, dict]:
    """
    Warm-start: fetch the most recent valid OU params per ticker from
    rows with date < today.  Provides κ, μ, σ_eq, β for the AR(1)
    initialisation so the fitter doesn't start from scratch each day.

    Returns a mapping {ticker: {kappa, mu, sigma_eq, beta}}.
    Empty dict is a safe fallback — the fitter initialises from data.
    """
    yesterday = today - datetime.timedelta(days=1)
    stmt = (
        select(OUParam)
        .where(OUParam.date <= yesterday)
        .where(OUParam.valid.is_(True))
        .order_by(OUParam.date.desc())
    )
    rows = session.scalars(stmt).all()

    # Keep only the most recent row per ticker
    seen: dict[str, dict] = {}
    for row in rows:
        if row.ticker not in seen:
            seen[row.ticker] = {
                "kappa": row.kappa,
                "mu": row.mu,
                "sigma_eq": row.sigma_eq,
                "beta": row.beta,
            }
    return seen


def load_sentiment_scores(session: Session, today: datetime.date) -> dict[str, dict]:
    """
    Fetch today's sentiment_scores rows as a mapping
    {ticker: {sentiment_res, abn_attention, model_used}}.

    S5 guarantees one row per universe ticker per day.  If no rows
    exist for today (S5 hasn't run yet or failed), returns an empty
    dict — callers must treat absent tickers as sentiment_adj=1.0
    (neutral) rather than skipping them.
    """
    stmt = select(SentimentScore).where(SentimentScore.date == today)
    rows = session.scalars(stmt).all()

    return {
        row.ticker: {
            "sentiment_res": row.sentiment_res,
            "abn_attention": row.abn_attention,
            "model_used": row.model_used,
        }
        for row in rows
    }
