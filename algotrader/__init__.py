"""
AlgoTrader — Modular algorithmic trading platform.

Python package layout (post-reorganization):

    algotrader.orchestrator   Process lifecycle, state machine, scheduling
    algotrader.ingestion      EOD OHLCV download, news/social scraping
    algotrader.signals        OU fitting, stat-arb / reversal / regime signals
    algotrader.backtest       Walk-forward, Monte Carlo, CSCV validation
    algotrader.sentiment      FinBERT scoring, residualization
    algotrader.execution      IBKR order submission, fill tracking
    algotrader.dashboard      Dash UI for approval and monitoring
    algotrader.shared         Config, DB, models, logging, constants

Go migration targets (scaffolding in cmd/ and internal/):

    cmd/algotrade            Future unified entry point (Go)
    internal/state           Future state machine (Go)
    internal/scheduler       Future cron / job scheduler (Go)
    internal/ibkr            Future IBKR TWS client (Go)
"""

__version__ = "1.0.0"
