"""
algotrader.execution/ibkr_client.py

Thin wrapper around ``ib_insync.IB`` providing the interface S6 needs.

Responsibilities
----------------
- ``connect()``         — connect with 3 retries and exponential back-off.
- ``disconnect()``      — graceful disconnect.
- ``get_account_equity()`` — net liquidation value (USD) from account summary.
- ``check_margin_ok()`` — whatIfOrder margin pre-check.
- ``qualify_contract()`` — resolve contract details with TWS.
- ``submit_order()``    — placeOrder; returns the Trade for fill tracking.
- ``cancel_all_pending()`` — cancel every open order (used on HALT).
- ``sleep()``           — run the ib_insync event loop for N seconds.

Connection failure after exhausting retries raises ``ExecutionError`` so the
caller can write a RISK_HALT event and exit cleanly.
"""
from __future__ import annotations

import time

from ib_insync import IB, Contract, LimitOrder, Order, Stock, Trade

from algotrader.shared.config_loader import AppConfig
from algotrader.shared.exceptions import ExecutionError
from algotrader.shared.logger import get_logger

log = get_logger(__name__)

_MAX_RETRIES = 3
_INITIAL_BACKOFF_SECONDS = 5.0


class IBKRClient:
    """Manages a single ib_insync connection to TWS."""

    def __init__(self, cfg: AppConfig, account_type: str) -> None:
        self._cfg = cfg
        self._account_type = account_type
        self._ib = IB()
        self._port = (
            cfg.system.ibkr_paper_port
            if account_type == "PAPER"
            else cfg.system.ibkr_live_port
        )
        self._client_id = cfg.system.ibkr_client_id

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Connect to TWS; retry up to _MAX_RETRIES times with exponential back-off."""
        last_exc: Exception | None = None
        backoff = _INITIAL_BACKOFF_SECONDS

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                self._ib.connect(
                    host="127.0.0.1",
                    port=self._port,
                    clientId=self._client_id,
                    timeout=20,
                    readonly=False,
                )
                log.info(
                    "ibkr_connected",
                    port=self._port,
                    client_id=self._client_id,
                    account_type=self._account_type,
                )
                return
            except Exception as exc:
                last_exc = exc
                log.warning(
                    "ibkr_connect_attempt_failed",
                    attempt=attempt,
                    max_retries=_MAX_RETRIES,
                    error=str(exc),
                )
                if attempt < _MAX_RETRIES:
                    time.sleep(backoff)
                    backoff *= 2

        raise ExecutionError(
            f"Failed to connect to IBKR TWS after {_MAX_RETRIES} attempts "
            f"(port={self._port}): {last_exc}"
        )

    def disconnect(self) -> None:
        if self._ib.isConnected():
            self._ib.disconnect()
            log.info("ibkr_disconnected")

    def is_connected(self) -> bool:
        return self._ib.isConnected()

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    def get_account_equity(self) -> float:
        """Return net liquidation value (USD) from the IBKR account summary."""
        summaries = self._ib.accountSummary()
        for item in summaries:
            if item.tag == "NetLiquidation" and item.currency == "USD":
                return float(item.value)
        raise ExecutionError(
            "Could not retrieve NetLiquidation from IBKR account summary. "
            "Ensure TWS is connected and the account is active."
        )

    # ------------------------------------------------------------------
    # Margin pre-check
    # ------------------------------------------------------------------

    def check_margin_ok(self, ticker: str, quantity: int, price: float) -> bool:
        """
        Use TWS whatIfOrder to check whether the position would be accepted.

        Returns True if IBKR reports a positive initial margin change, False
        if margin is insufficient or the check cannot be performed.
        """
        try:
            contract = Stock(ticker, "SMART", "USD")
            self._ib.qualifyContracts(contract)
            test_order = LimitOrder("BUY", quantity, round(price, 2))
            test_order.whatIf = True
            state = self._ib.whatIfOrder(contract, test_order)
            margin_change = float(state.initMarginChange)
            return margin_change > 0
        except Exception as exc:
            log.warning(
                "margin_check_failed",
                ticker=ticker,
                error=str(exc),
            )
            return False

    # ------------------------------------------------------------------
    # Order management
    # ------------------------------------------------------------------

    def qualify_contract(self, contract: Contract) -> Contract:
        qualified = self._ib.qualifyContracts(contract)
        if not qualified:
            raise ExecutionError(
                f"Could not qualify contract for {contract.symbol}."
            )
        return qualified[0]

    def submit_order(self, contract: Contract, order: Order) -> Trade:
        """Qualify the contract and place the order; return the Trade."""
        contract = self.qualify_contract(contract)
        trade = self._ib.placeOrder(contract, order)
        log.info(
            "order_submitted_to_ibkr",
            ticker=contract.symbol,
            action=order.action,
            quantity=order.totalQuantity,
            ibkr_order_id=str(trade.order.orderId),
        )
        return trade

    def cancel_all_pending(self) -> None:
        """Cancel every open order — called when entering HALT state."""
        open_trades = self._ib.openTrades()
        for trade in open_trades:
            self._ib.cancelOrder(trade.order)
            log.warning(
                "order_cancelled",
                ticker=trade.contract.symbol,
                ibkr_order_id=str(trade.order.orderId),
            )

    # ------------------------------------------------------------------
    # Event loop
    # ------------------------------------------------------------------

    def sleep(self, seconds: float) -> None:
        """
        Run the ib_insync event loop for *seconds*, processing callbacks
        (including fill events) as they arrive.
        """
        self._ib.sleep(seconds)
