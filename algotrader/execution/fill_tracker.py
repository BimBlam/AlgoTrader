"""
algotrader.execution/fill_tracker.py

Registers ib_insync fill-event handlers on submitted Trades and waits for
fills to arrive within a fixed timeout window.

After ``wait()`` returns, all fills received within the timeout have been
written to the database and committed.  Any order still pending remains in
SUBMITTED status and can be monitored/cancelled by a later reconcile pass.
"""
from __future__ import annotations

from datetime import UTC, datetime

from ib_insync import Fill, Trade

from algotrader.shared.constants import EventType, Severity
from algotrader.shared.logger import get_logger
from algotrader.shared.models import Order

from .writer import update_order_filled, write_event, write_position

log = get_logger(__name__)

FILL_TIMEOUT_SECONDS = 60.0


class FillTracker:
    """
    Collects fills for a batch of submitted trades within the current DB session.

    Usage::

        tracker = FillTracker(session, run_id)
        for trade, order_row in submitted_pairs:
            tracker.attach(trade, order_row)
        tracker.wait(ibkr_client)   # runs the ib_insync event loop

    The tracker commits after each fill so partial batches are durable even
    if a later fill triggers an exception.
    """

    def __init__(self, session, run_id: str) -> None:
        self._session = session
        self._run_id = run_id
        # ibkr_order_id (int) → (Trade, Order row)
        self._pending: dict[int, tuple[Trade, Order]] = {}

    def attach(self, trade: Trade, order_row: Order) -> None:
        """Register fill callbacks for *trade*."""
        ibkr_id = trade.order.orderId
        self._pending[ibkr_id] = (trade, order_row)
        trade.fillEvent += self._on_fill

    def _on_fill(self, trade: Trade, fill: Fill) -> None:
        ibkr_id = trade.order.orderId
        if ibkr_id not in self._pending:
            return

        _, order_row = self._pending.pop(ibkr_id)

        fill_price = float(fill.execution.avgPrice)
        filled_at = datetime.now(tz=UTC)

        update_order_filled(self._session, order_row, fill_price, filled_at)
        position = write_position(self._session, order_row, fill_price, filled_at)

        write_event(
            self._session,
            event_type=EventType.ORDER_FILLED,
            severity=Severity.INFO,
            message=(
                f"Order filled: {order_row.ticker} x{order_row.quantity} "
                f"@ {fill_price:.2f}"
            ),
            run_id=self._run_id,
            payload={"order_id": order_row.id, "fill_price": fill_price},
        )
        write_event(
            self._session,
            event_type=EventType.POSITION_OPENED,
            severity=Severity.INFO,
            message=(
                f"Position opened: {order_row.ticker} x{order_row.quantity} "
                f"@ {fill_price:.2f}"
            ),
            run_id=self._run_id,
            payload={
                "ticker": order_row.ticker,
                "quantity": order_row.quantity,
                "fill_price": fill_price,
                "position_id": position.id,
            },
        )

        self._session.commit()
        log.info(
            "fill_captured",
            ticker=order_row.ticker,
            quantity=order_row.quantity,
            fill_price=fill_price,
            position_id=position.id,
        )

    def wait(self, ibkr_client) -> int:
        """
        Run the ib_insync event loop for ``FILL_TIMEOUT_SECONDS`` seconds,
        collecting fills as they arrive via callbacks.

        Returns the number of fills captured.
        """
        pending_before = len(self._pending)
        ibkr_client.sleep(FILL_TIMEOUT_SECONDS)
        fills_captured = pending_before - len(self._pending)
        log.info(
            "fill_wait_complete",
            fills_captured=fills_captured,
            still_pending=len(self._pending),
        )
        return fills_captured
