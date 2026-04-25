"""
algotrader.execution/sizer.py

Quarter-Kelly + ATR position sizing (§7.1, §5.2, §10).

Sizing formula
--------------
1.  Load OHLCV parquet for the ticker.
2.  Compute ATR over ``risk.atr_lookback_days`` (True Range average).
3.  dollar_risk   = account_equity × kelly_fraction
4.  base_quantity = floor(dollar_risk / ATR)        # 1 ATR ≈ 1 stop-loss unit
5.  adj_quantity  = floor(base_quantity × sentiment_adj)
6.  target_usd    = adj_quantity × limit_price

The caller (main.py) passes the result through ``run_per_signal_guards`` which
applies the max_position_usd clip (Guard 3) and recomputes quantity afterward.
"""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from algotrader.shared.config_loader import AppConfig
from algotrader.shared.exceptions import DataError
from algotrader.shared.logger import get_logger
from algotrader.shared.models import Signal

log = get_logger(__name__)


def _load_ohlcv(ticker: str, cfg: AppConfig) -> pd.DataFrame:
    path = Path(cfg.system.data_dir_ssd) / "processed" / "ohlcv" / f"{ticker}.parquet"
    if not path.exists():
        raise DataError(f"OHLCV parquet not found for {ticker}: {path}")
    df = pd.read_parquet(path, engine="pyarrow")
    df.index = pd.to_datetime(df.index)
    return df


def compute_atr(df: pd.DataFrame, lookback_days: int) -> float:
    """
    Return the Average True Range over the last *lookback_days* rows.

    True Range = max(high−low, |high−prev_close|, |low−prev_close|)

    Raises DataError if the DataFrame has fewer than ``lookback_days + 1`` rows
    (need one extra row to compute the first True Range with a prior close).
    """
    if len(df) < lookback_days + 1:
        raise DataError(
            f"Insufficient OHLCV history: need {lookback_days + 1} rows, "
            f"got {len(df)}."
        )
    window = df.iloc[-(lookback_days + 1) :].copy()
    prev_close = window["close"].shift(1)
    tr = pd.concat(
        [
            window["high"] - window["low"],
            (window["high"] - prev_close).abs(),
            (window["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    # Drop the first row which has NaN prev_close
    atr = float(tr.iloc[1:].mean())
    if math.isnan(atr) or atr <= 0:
        raise DataError(
            f"Computed ATR is {atr:.6f} (non-positive or NaN) over "
            f"{lookback_days} days — cannot size position."
        )
    return atr


def compute_position_size(
    signal: Signal,
    cfg: AppConfig,
    account_equity: float,
    limit_price: float,
) -> tuple[float, int]:
    """
    Compute ``(target_size_usd, quantity)`` for *signal*.

    Parameters
    ----------
    signal:
        Signal ORM row (uses ``ticker`` and ``sentiment_adj``).
    cfg:
        Full AppConfig — uses ``risk`` and ``system.data_dir_ssd``.
    account_equity:
        Net liquidation value (USD) from IBKR.
    limit_price:
        The price at which the limit order will be placed (last adj close).

    Returns
    -------
    (target_size_usd, quantity)
        Before Guard-3 clipping.  Pass through ``run_per_signal_guards`` which
        applies ``max_position_usd`` and recomputes quantity.

    Raises
    ------
    DataError
        If OHLCV data is missing/insufficient, ATR is degenerate, or the
        sentiment multiplier reduces quantity to zero.
    """
    df = _load_ohlcv(signal.ticker, cfg)
    atr = compute_atr(df, cfg.risk.atr_lookback_days)

    dollar_risk = account_equity * cfg.risk.kelly_fraction
    base_quantity = math.floor(dollar_risk / atr)

    if base_quantity <= 0:
        raise DataError(
            f"Base quantity=0 for {signal.ticker}: "
            f"dollar_risk={dollar_risk:.2f}, ATR={atr:.4f}. "
            f"Account equity may be too low."
        )

    # Apply sentiment confidence multiplier (1.0 → full size, 0.5 → half, 0.0 → skip)
    adj_quantity = math.floor(base_quantity * signal.sentiment_adj)
    if adj_quantity <= 0:
        raise DataError(
            f"Sentiment-adjusted quantity=0 for {signal.ticker} "
            f"(base={base_quantity}, sentiment_adj={signal.sentiment_adj}). "
            f"Signal will be skipped."
        )

    target_size_usd = adj_quantity * limit_price

    log.info(
        "position_sized",
        ticker=signal.ticker,
        atr=round(atr, 4),
        account_equity=round(account_equity, 2),
        dollar_risk=round(dollar_risk, 2),
        base_quantity=base_quantity,
        sentiment_adj=signal.sentiment_adj,
        adj_quantity=adj_quantity,
        target_usd=round(target_size_usd, 2),
    )

    return target_size_usd, adj_quantity
