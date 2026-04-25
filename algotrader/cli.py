"""
Unified CLI entry point for the Python side of AlgoTrader.

Replaces the scattered ``python -m sN_...`` commands with a single
dispatch interface::

    python -m algotrader.cli orchestrator
    python -m algotrader.cli ingestion <run_id>
    python -m algotrader.cli signals <run_id>
    python -m algotrader.cli sentiment <run_id>
    python -m algotrader.cli backtest <run_id>
    python -m algotrader.cli execution <run_id>
    python -m algotrader.cli reconcile <run_id>
    python -m algotrader.cli dashboard

Each command delegates to the canonical ``run(run_id: str)`` entry point
(except ``orchestrator`` and ``dashboard``, which are long-running).
"""
from __future__ import annotations

import argparse
import sys

_COMMAND_MAP: dict[str, str] = {
    "ingestion": "algotrader.ingestion.main",
    "signals": "algotrader.signals.main",
    "sentiment": "algotrader.sentiment.main",
    "backtest": "algotrader.backtest.main",
    "execution": "algotrader.execution.main",
    "reconcile": "algotrader.execution.reconcile",
}


def _run_module(module_name: str, run_id: str | None) -> None:
    """Import the module and call its ``run()`` function."""
    module = __import__(module_name, fromlist=["run"])
    run_fn = getattr(module, "run")
    if run_id is not None:
        run_fn(run_id)
    else:
        run_fn()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="algotrader",
        description="AlgoTrader subsystem launcher",
    )
    parser.add_argument(
        "command",
        choices=["orchestrator", "ingestion", "signals", "sentiment",
                 "backtest", "execution", "reconcile", "dashboard"],
        help="Subsystem to launch",
    )
    parser.add_argument(
        "run_id",
        nargs="?",
        help="Job run_id (required for all commands except orchestrator and dashboard)",
    )
    args = parser.parse_args(argv)

    if args.command == "orchestrator":
        from algotrader.orchestrator.main import Orchestrator
        Orchestrator().start()
        return 0

    if args.command == "dashboard":
        from algotrader.dashboard.main import main as dashboard_main
        dashboard_main()
        return 0

    module_name = _COMMAND_MAP.get(args.command)
    if module_name is None:
        parser.error(f"Unknown command: {args.command}")

    if args.run_id is None:
        parser.error(f"Command '{args.command}' requires a run_id argument.")

    _run_module(module_name, args.run_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
