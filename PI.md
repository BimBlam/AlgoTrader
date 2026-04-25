# AlgoTrader — Agent Development Guide

> This guide is for **Pi** (pi.dev) and compatible coding agents.  
> It replaces the legacy `CLAUDE.md` — delete any old `CLAUDE.md` you find.

## Before You Start

Read these in order before touching any code:

| Document | Purpose |
|----------|---------|
| `.docs/Frozen Project Specification v1.0.md` | **FROZEN — source of record.** Architecture, DB schema, contracts, configs, coding standards. If any conflict exists between sources, this wins. |
| `.docs/implementation-log.md` | Living log of resolved deviations and design decisions (not overrides) |
| `MIGRATION.md` | Polyglot roadmap (Go migration targets) and reorganization log |
| `ALGOTRADER_GLOBAL_BRIEF.md` | System overview and subsystem map (if present) |

## Quick Commands

```bash
# Install dependencies (when venv is rebuilt)
pip install -r requirements.txt -r requirements-dev.txt

# Run all unit tests
python -m pytest

# Run one subsystem
python -m pytest tests/unit/signals/
python -m pytest tests/unit/execution/

# Run single test
python -m pytest tests/unit/signals/test_ou_model.py::test_kappa_positive

# Lint
ruff check algotrader/ tests/

# Type check
mypy algotrader/

# Build Go scaffold (future)
make build-go
```

## Repository Layout

```
AlgoTrader/
├── algotrader/               ← Python package root
│   ├── orchestrator/         S1 — process lifecycle, state machine (Go candidate)
│   ├── ingestion/            S2 — OHLCV, scrapes
│   ├── signals/              S3 — OU fitting, stat-arb / reversal / regime
│   ├── backtest/             S4 — walk-forward, Monte Carlo, CSCV
│   ├── sentiment/            S5 — FinBERT scoring
│   ├── execution/            S6 — IBKR orders (Go candidate)
│   ├── dashboard/            S7 — Dash UI
│   ├── shared/               Config, DB, models, logging, constants
│   └── cli.py                Unified entry point: python -m algotrader.cli <cmd>
├── cmd/algotrade/            Go entry point scaffold
├── internal/                 Go private libs (state, scheduler, ibkr, db)
├── pkg/models/               Go structs mirroring DB schema
├── contracts/                JSON schemas for cross-process IPC
├── config/                   YAML configs (system, risk, universe, strategy, sentiment)
├── migrations/               Alembic
└── tests/unit/<domain>/      One test dir per subsystem
```

## Rules for Agent Work

1. **Read the spec first.** The Frozen Spec is authoritative. The implementation log records deviations — do not re-deviate without updating both.
2. **No cross-subsystem imports.** Only import from `algotrader.shared` or within the same subsystem directory.
3. **All imports use `algotrader.` prefix.** `from algotrader.shared.config_loader import get_config`, not `from shared...`.
4. **Config only via `get_config()`.** Nothing hardcoded. Call `init_db()` at every entry point.
5. **structlog only.** No `print()`. Event name as first positional arg: `log.info("event_name", field=value)`. Never `event=` as a keyword.
6. **SQLAlchemy 2.0 ORM only.** No raw SQL strings in app code.
7. **Fail closed.** Raise typed exceptions from `algotrader.shared.exceptions`, log, exit cleanly.
8. **EventType enum is closed.** Only values in `algotrader.shared.constants`. No new event types invented.
9. **MARKET orders disabled** unless `cfg.system.allow_market_orders` is explicitly `true`. Enforcement in `execution/` only.
10. **Tests mirror source.** `tests/unit/signals/test_*.py` tests `algotrader/signals/*.py`.

## Entry Points

Use the unified CLI instead of direct module paths:

```bash
python -m algotrader.cli orchestrator      # long-running
python -m algotrader.cli ingestion <run_id>
python -m algotrader.cli signals <run_id>
python -m algotrader.cli sentiment <run_id>
python -m algotrader.cli backtest <run_id>
python -m algotrader.cli execution <run_id>
python -m algotrader.cli reconcile <run_id>
python -m algotrader.cli dashboard         # long-running
```

The legacy `python -m sN_...` paths no longer exist.

## Working Style

When asked to work on a subsystem:

1. Read the relevant Frozen Spec section.
2. Check `.docs/implementation-log.md` for prior deviations.
3. Summarise current vs target state.
4. Propose an ordered step plan (each step = a few coherent edits + tests).
5. For small steps: proceed. For large/cross-cutting changes: wait for confirmation.
6. After each step, report: files changed, behaviour added/modified, test status.

## Go Migration (Background Context)

`cmd/algotrade/`, `internal/`, and `pkg/` are scaffolding for a future Go rewrite of the orchestrator (S1) and execution engine (S6). Do not delete them. Do not implement them unless explicitly asked. The Python modules in `algotrader/orchestrator/` and `algotrader/execution/` remain the active implementations.
