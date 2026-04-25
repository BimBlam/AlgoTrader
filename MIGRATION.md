# AlgoTrader Polyglot Reorganization

## Rationale

The existing `s1_...` / `s2_...` flat structure is an artifact of agent-generated incremental development. It is neither idiomatic Python nor compatible with introducing compiled services. This reorganization establishes a clean polyglot repository where:

- **Python** owns the data-science stack (ingestion, signals, backtest, sentiment, dashboard)
- **Go** owns infrastructure, concurrency, and low-latency I/O (orchestrator, execution engine)
- **Contracts** (JSON schemas / proto) define cross-language boundaries

---

## Migration Candidates

| Module | Current Lang | Target Lang | Reason |
|--------|-------------|-------------|--------|
| Orchestrator (S1) | Python | **Go** | Process supervision, state machine, cron scheduling, watchdog — Go’s goroutines + channels are vastly superior for reliable long-running process management. |
| Execution (S6) | Python | **Go** | IBKR TWS API is async/socket-heavy; Go’s concurrency model, memory safety, and static binary deployment eliminate GIL contention and interpreter startup overhead at market open. |
| Ingestion (S2) | Python | **Python** | yfinance, PRAW, pandas are Python-native. Keep. |
| Signals (S3) | Python | **Python** | scipy, statsmodels, numpy, OU fitting. Keep. |
| Backtest (S4) | Python | **Python** | arch, pandas, numpy-heavy Monte Carlo. Keep. |
| Sentiment (S5) | Python | **Python** | transformers / PyTorch / FinBERT. Keep. |
| Dashboard (S7) | Python | **Python** | Dash/Flask/Plotly. Keep. |

## Directory Layout (Target)

```
AlgoTrader/
├── algotrader/                 # Python package root (was s1..s7 + shared)
│   ├── __init__.py
│   ├── cli.py                  # Unified Python CLI entry point
│   ├── orchestrator/           # was s1_orchestrator  (→ Go candidate)
│   ├── ingestion/              # was s2_data_ingestion
│   ├── signals/                # was s3_signal_engine
│   ├── backtest/               # was s4_backtest_validator
│   ├── sentiment/              # was s5_sentiment
│   ├── execution/              # was s6_execution    (→ Go candidate)
│   ├── dashboard/              # was s7_dashboard
│   └── shared/                 # was shared/
├── cmd/                        # Go entry points (standard Go layout)
│   └── algotrade/
│       └── main.go             # Future Go orchestrator + execution launcher
├── internal/                   # Go private libraries
│   ├── state/
│   ├── scheduler/
│   ├── ibkr/
│   └── db/
├── pkg/                        # Go public / shared libraries
│   └── models/
├── proto/                      # Future: protobuf definitions for IPC
├── contracts/                  # JSON schemas for current IPC (DB + queue tokens)
├── config/
├── migrations/
├── tests/
├── Makefile
├── go.mod
└── pyproject.toml
```

## Import Mapping

| Old Import | New Import |
|-----------|-----------|
| `from s1_orchestrator...` | `from algotrader.orchestrator...` |
| `from s2_data_ingestion...` | `from algotrader.ingestion...` |
| `from s3_signal_engine...` | `from algotrader.signals...` |
| `from s4_backtest_validator...` | `from algotrader.backtest...` |
| `from s5_sentiment...` | `from algotrader.sentiment...` |
| `from s6_execution...` | `from algotrader.execution...` |
| `from s7_dashboard...` | `from algotrader.dashboard...` |
| `from shared...` | `from algotrader.shared...` |

## Workflow for Go Migration (Future Steps)

1. **Lock contracts**: Finalize JSON schemas in `contracts/` for jobs, signals, orders, events.
2. **Scaffold Go modules**: `go mod init github.com/addyd/algotrader`; implement `internal/db` (pgx), `internal/scheduler` (cron library), `internal/state` (state machine).
3. **Migrate S1 incrementally**: Implement Go orchestrator that reads/writes the same PostgreSQL schema; run side-by-side with Python S1 in PAPER mode.
4. **Migrate S6 incrementally**: Implement Go IBKR client using `ib_insync`-inspired patterns with TWS API; validate with paper orders.
5. **Unified CLI**: `make build` produces both Python wheel and Go binary; `algotrader` (Go) becomes the primary entry point, shelling out to Python workers for S2/S3/S4/S5.
6. **Retire Python S1/S6**: Once Go versions achieve parity in backtesting + paper trading, remove Python orchestrator and execution modules.

---

## Reorganization Log

| Step | Action | Files Affected |
|------|--------|---------------|
| 1 | Create `algotrader/` package root | New dirs |
| 2 | Move `s1_orchestrator` → `algotrader/orchestrator` | 9 files |
| 3 | Move `s2_data_ingestion` → `algotrader/ingestion` | 7 files |
| 4 | Move `s3_signal_engine` → `algotrader/signals` | 12 files |
| 5 | Move `s4_backtest_validator` → `algotrader/backtest` | 13 files |
| 6 | Move `s5_sentiment` → `algotrader/sentiment` | 7 files |
| 7 | Move `s6_execution` → `algotrader/execution` | 9 files |
| 8 | Move `s7_dashboard` → `algotrader/dashboard` | 10 files |
| 9 | Move `shared` → `algotrader/shared` | 7 files |
| 10 | Rewrite all internal imports | ~144 Python files |
| 11 | Update test imports and paths | ~65 test files |
| 12 | Create `algotrader/cli.py` | New |
| 13 | Create Go scaffolding (`go.mod`, `cmd/`, `internal/`, `pkg/`) | New |
| 14 | Create `Makefile` | New |
| 15 | Update `pyproject.toml` package discovery | 1 file |
