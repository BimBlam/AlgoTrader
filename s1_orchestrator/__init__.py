"""
S1 — Orchestrator
=================
Entry package for the AlgoTrader orchestration process.

Exports the top-level ``Orchestrator`` class so callers can do::

    from s1_orchestrator import Orchestrator
"""

from s1_orchestrator.main import Orchestrator

__all__ = ["Orchestrator"]
