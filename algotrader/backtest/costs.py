"""
algotrader.backtest/costs.py

Transaction cost model: configurable slippage + IBKR Canada tiered
commission schedule.  Used identically in walk-forward, Monte Carlo,
and bootstrap stages so all comparisons are apples-to-apples.
"""

from __future__ import annotations

from dataclasses import dataclass

from algotrader.shared.logger import get_logger

log = get_logger(__name__)

# IBKR Canada tiered equity commission tiers (per share, USD).
# Source: IBKR fee schedule as of spec freeze date.
# Tiers are applied per-order based on monthly volume; we conservatively
# apply tier 1 (< 300k shares / month) which is worst-case for a small account.
_IBKR_TIER1_PER_SHARE = 0.0035  # USD per share
_IBKR_TIER1_MIN = 0.35          # USD per order minimum
_IBKR_TIER1_MAX_PCT = 0.01      # 1 % of trade value cap


@dataclass
class CostEstimate:
    slippage_usd: float
    commission_usd: float

    @property
    def total_usd(self) -> float:
        return self.slippage_usd + self.commission_usd


class TransactionCostModel:
    """
    Estimates round-trip transaction costs for a single trade leg.

    Slippage is applied as a fraction of trade value; commission follows the
    IBKR Canada tiered schedule.  Both parameters are configurable via
    strategy_params.yaml so no values are hardcoded here.

    Parameters
    ----------
    cfg : AppConfig
        Full application config from get_config().
    """

    def __init__(self, cfg) -> None:
        # Default 0.0015 per spec contract ("default 0.15%")
        self._slippage_rate: float = getattr(
            cfg.backtest, "slippage_rate", 0.0015
        )
        self._include_costs: bool = getattr(
            cfg.backtest, "include_costs", True
        )
        log.debug(
            "cost_model_init",
            slippage_rate=self._slippage_rate,
            include_costs=self._include_costs,
        )

    def estimate(self, price: float, quantity: int) -> CostEstimate:
        """
        Compute one-way transaction cost for a trade.

        Parameters
        ----------
        price    : execution price per share (float)
        quantity : number of shares (int, positive)

        Returns
        -------
        CostEstimate
        """
        if not self._include_costs:
            return CostEstimate(slippage_usd=0.0, commission_usd=0.0)

        trade_value = abs(price * quantity)
        slippage = trade_value * self._slippage_rate

        raw_comm = _IBKR_TIER1_PER_SHARE * abs(quantity)
        commission = max(_IBKR_TIER1_MIN, raw_comm)
        commission = min(commission, trade_value * _IBKR_TIER1_MAX_PCT)

        return CostEstimate(slippage_usd=slippage, commission_usd=commission)

    def round_trip_cost_rate(self, price: float, quantity: int) -> float:
        """
        Return total round-trip cost as a fraction of trade value.
        Convenience method for return-series adjustment.
        """
        est = self.estimate(price, quantity)
        trade_value = abs(price * quantity)
        if trade_value == 0:
            return 0.0
        return (est.total_usd * 2) / trade_value  # ×2 for entry + exit
