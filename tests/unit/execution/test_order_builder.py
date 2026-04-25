"""tests/unit/s6/test_order_builder.py"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from ib_insync import LimitOrder, MarketOrder, Stock

from algotrader.shared.exceptions import DataError
from algotrader.execution.order_builder import build_contract, build_order, get_limit_price


def _make_cfg(data_dir: str, allow_market: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        system=SimpleNamespace(
            data_dir_ssd=data_dir,
            allow_market_orders=allow_market,
        )
    )


def _write_parquet(path: Path, adj_close: float) -> None:
    pd.DataFrame(
        {
            "open": [adj_close],
            "high": [adj_close],
            "low":  [adj_close],
            "close": [adj_close],
            "adj_close": [adj_close],
            "volume": [1_000_000],
        }
    ).to_parquet(path, engine="pyarrow")


class TestGetLimitPrice:
    def test_returns_last_adj_close(self, tmp_path):
        ohlcv_dir = tmp_path / "processed" / "ohlcv"
        ohlcv_dir.mkdir(parents=True)
        _write_parquet(ohlcv_dir / "AAPL.parquet", 182.50)

        cfg = _make_cfg(str(tmp_path))
        price = get_limit_price("AAPL", cfg)
        assert price == pytest.approx(182.50)

    def test_raises_when_file_missing(self, tmp_path):
        cfg = _make_cfg(str(tmp_path))
        with pytest.raises(DataError, match="OHLCV parquet not found"):
            get_limit_price("AAPL", cfg)

    def test_raises_when_file_empty(self, tmp_path):
        ohlcv_dir = tmp_path / "processed" / "ohlcv"
        ohlcv_dir.mkdir(parents=True)
        pd.DataFrame(
            columns=["open", "high", "low", "close", "adj_close", "volume"]
        ).to_parquet(ohlcv_dir / "AAPL.parquet", engine="pyarrow")

        cfg = _make_cfg(str(tmp_path))
        with pytest.raises(DataError, match="empty"):
            get_limit_price("AAPL", cfg)


class TestBuildContract:
    def test_returns_stock_with_smart_routing(self):
        contract = build_contract("AAPL")
        assert isinstance(contract, Stock)
        assert contract.symbol == "AAPL"
        assert contract.exchange == "SMART"
        assert contract.currency == "USD"


class TestBuildOrder:
    def test_long_signal_builds_buy_limit(self, sample_signal, mock_cfg):
        sample_signal.side = "LONG"
        order = build_order(sample_signal, 10, 150.0, mock_cfg)
        assert isinstance(order, LimitOrder)
        assert order.action == "BUY"
        assert order.totalQuantity == 10
        assert order.lmtPrice == pytest.approx(150.0)
        assert order.tif == "DAY"
        assert order.outsideRth is False

    def test_short_signal_builds_sell_limit(self, sample_signal, mock_cfg):
        sample_signal.side = "SHORT"
        order = build_order(sample_signal, 5, 200.0, mock_cfg)
        assert isinstance(order, LimitOrder)
        assert order.action == "SELL"

    def test_market_order_when_config_enabled(self, sample_signal, mock_cfg):
        mock_cfg.system.allow_market_orders = True
        order = build_order(sample_signal, 10, 150.0, mock_cfg)
        assert isinstance(order, MarketOrder)
        assert order.action == "BUY"

    def test_limit_price_rounded_to_two_decimals(self, sample_signal, mock_cfg):
        order = build_order(sample_signal, 10, 150.12345, mock_cfg)
        assert isinstance(order, LimitOrder)
        assert order.lmtPrice == pytest.approx(150.12)
