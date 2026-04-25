"""
s6_execution/order_builder.py

Build ib_insync Contract and Order objects from a Signal.

- Default: LIMIT orders only.
- Override: if ``cfg.system.allow_market_orders=True``, submit MARKET orders
  (logged as a warning).
- Side mapping: LONG → BUY action, SHORT → SELL action.
- Limit price: last adjusted close from the OHLCV parquet (pre-market at 09:25 ET).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from ib_insync import LimitOrder, MarketOrder, Stock

from shared.config_loader import AppConfig
from shared.exceptions import DataError
from shared.logger import get_logger
from shared.models import Signal

log = get_logger(__name__)


def get_limit_price(ticker: str, cfg: AppConfig) -> float:
    """Return the last adjusted close from the OHLCV parquet for *ticker*."""
    path = Path(cfg.system.data_dir_ssd) / "processed" / "ohlcv" / f"{ticker}.parquet"
    if not path.exists():
        raise DataError(f"OHLCV parquet not found for {ticker}: {path}")
    df = pd.read_parquet(path, engine="pyarrow")
    if df.empty:
        raise DataError(f"OHLCV parquet is empty for {ticker}.")
    return float(df["adj_close"].iloc[-1])


def build_contract(ticker: str) -> Stock:
    """Return a US equity (SMART routing, USD) contract for *ticker*."""
    return Stock(ticker, "SMART", "USD")


def build_order(
    signal: Signal,
    quantity: int,
    limit_price: float,
    cfg: AppConfig,
) -> LimitOrder | MarketOrder:
    """
    Build an ib_insync order for *signal*.

    Returns a LimitOrder (DAY, no extended hours) unless
    ``cfg.system.allow_market_orders`` is True, in which case a MarketOrder
    is returned and a WARNING is emitted.
    """
    action = "BUY" if signal.side == "LONG" else "SELL"

    if cfg.system.allow_market_orders:
        log.warning(
            "market_order_enabled",
            ticker=signal.ticker,
            action=action,
            quantity=quantity,
            note="allow_market_orders=true in system.yaml",
        )
        return MarketOrder(action, quantity)

    order = LimitOrder(action, quantity, round(limit_price, 2))
    order.tif = "DAY"
    order.outsideRth = False  # do not fill in pre/post-market sessions
    return order
