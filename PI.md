# AlgoTrader — Agent Development Guide

> For **Pi** (pi.dev) and compatible coding agents.

## Tracking

This project uses **bd (beads)** for issue tracking. All work is tracked
as beads issues with dependencies, not in markdown TODO lists.

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
bd list               # All open issues
```

**Rules:**
- Use `bd` for ALL task tracking — never TodoWrite, TaskCreate, or markdown TODOs
- Use `bd remember` for persistent project knowledge
- dátummal push after every session: `git pull --rebase && bd dolt push && git push`

## Before You Start

Read these in order before touching any code:

| Document | Purpose |
|----------|---------|
| `.docs/Frozen Project Specification v1.0.md` | **Reference design doc** — Architecture, DB schema, contracts, configs, coding standards. For historical context; active tracking is in beads. |
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

## External Credentials

Some features require environment variables. None are required for basic operation.

| Variable | Required by | How to get |
|---|---|---|
| `DATABASE_URL` | system.yaml | PostgreSQL connection string |
| `REDDIT_CLIENT_ID` | sentiment_params.yaml | Reddit app settings (https://www.reddit.com/prefs/apps) |
| `REDDIT_CLIENT_SECRET` | sentiment_params.yaml | Same as above |
| `REDDIT_USER_AGENT` | sentiment_params.yaml | Optional, defaults to `algotrader-s2/1.0` |

Reddit scraping is **disabled by default** (`sources.reddit.enabled: false`).
Enable it only after setting the env vars above and flipping the flag.

## Rules for Agent Work

1. **Check beads first.** `bd ready` shows active work. The Frozen Spec is reference material, not the living tracker.
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
