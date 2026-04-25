"""
S1 — Orchestrator
=================
Entry package for the AlgoTrader orchestration process.

Exports the top-level ``Orchestrator`` class so callers can do::

    from algotrader.orchestrator import Orchestrator
"""

from algotrader.orchestrator.main import Orchestrator

__all__ = ["Orchestrator"]
