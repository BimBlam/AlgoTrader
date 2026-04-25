# AlgoTrader – Global Project Brief
> **For use as the permanent system prompt / context header in Claude Code sessions.**
> Paste this entire file at the start of any new Claude Code conversation before issuing module prompts.

---

## 1. What This System Is

AlgoTrader is a **modular, multi-process algorithmic trading platform** for US equities, connected to Interactive Brokers Canada via the TWS API (non-registered margin account). It runs on a single Arch Linux workstation (Ryzen 5 5600G / 32 GB DDR4 / RTX 4060).

The system supports **paper trading, live trading, and parallel paper+live** ("BOTH") operation through a single code path. The only differences between modes are configuration values and which IBKR port is used. All mode logic lives in S1 (Orchestrator) and S6 (Execution Engine).

---

## 2. Authoritative References

| Reference | Status | Purpose |
|-----------|--------|---------|
| `./Frozen-Project-Specification-v1.0.md` | **FROZEN – source of record** | Architecture, DB schema, contracts, configs, coding standards |
| `./docs/implementation-log.md` (or inline in spec Part 12) | Living | Deviations, design decisions, resolved gaps |
| Per-session module prompts | Additive | Narrow scope for a specific task |

**If any conflict exists between sources, the frozen spec wins.** Implementation logs document *resolved deviations*, not overrides.

---

## 3. Subsystem Map

| ID | Name | Primary Responsibility |
|----|------|----------------------|
| `shared/` | Shared Utilities | Config, DB session, ORM models, logging, enums, exceptions |
| S1 | Orchestrator | State machine, job scheduler, process lifecycle, halt policy |
| S2 | Data Ingestion | OHLCV download, returns computation, news/social scrape |
| S3 | Signal Engine | OU fitting, s-scores, reversal, regime classification, signal writing |
| S4 | Backtest Validator | Walk-forward, Monte Carlo, bootstrap, CSCV, PBO |
| S5 | Sentiment Engine | FinBERT scoring, attention z-score, residualisation |
| S6 | Execution Engine | IBKR order submission, fill tracking, position management, risk guards |
| S7 | Dashboard | Local Dash UI: approval, calibration, monitoring, halt/resume |

**No subsystem may import from another subsystem package.** All cross-cutting utilities come from `shared/` only.

---

## 4. Process and Data Flow

```
[Cron: 21:00 ET weekdays]
      │
      ├──► S2 (Data Ingestion)  ──writes──► OHLCV + returns parquet, raw scrape JSON
      └──► S5 (Sentiment)       ──reads──►  raw JSON  ──writes──► sentiment_scores DB table
                │
          [DATA_READY + SENTIMENT_READY events]
                │
               S3 (Signal Engine) ──reads──► returns parquet + sentiment_scores
                                  ──writes──► signals table (status=PENDING), ou_params
                │
          [SIGNALS_READY event → S1 notifies S7]
                │
         [Approval window: 22:00–09:20 ET]
         S7 (Dashboard) writes APPROVED/DENIED to signals table
         or S1 auto-approves (SOFT mode + PAPER only)
                │
          [09:25 ET: SIGNALS_APPROVED]
               S6 (Execution Engine) ──reads──► signals (APPROVED)
                                     ──runs──►  risk guards
                                     ──submits──► IBKR TWS
                                     ──writes──►  orders, positions tables
                │
          [Weekly Sunday 20:00 ET]
               S4 (Backtest Validator) ──reads──► full returns history
                                       ──writes──► backtest_runs table + HDD output
```

All inter-process communication uses:
- **Python `multiprocessing.Queue`** for wakeup tokens only (no business state)
- **PostgreSQL** (`SELECT ... FOR UPDATE SKIP LOCKED`) for durable job state
- **Parquet files on SSD** for market data passed between S2 → S3 / S4

---

## 5. Global Coding Rules

These apply to every file in every subsystem. No exceptions unless the frozen spec explicitly overrides.

### Language and Stack
- Python 3.11+
- SQLAlchemy 2.0 ORM only — no raw SQL strings in application code
- `structlog` for all logging — no `print()`
- `pydantic` v2 for config validation
- `pytest` for all tests under `tests/unit/<subsystem>/`

### Shared Utilities (import only from `shared/`)
```python
from shared.config_loader import get_config       # AppConfig object
from shared.db import get_session, init_db        # SQLAlchemy session
from shared.models import Signal, Order, ...      # ORM models
from shared.constants import SystemMode, EventType, SignalStatus, ...  # enums
from shared.exceptions import RiskBreach, DataError, SignalError, ...  # typed exceptions
from shared.logger import get_logger              # structlog logger
```

### Data Types
- Dates → `datetime.date` (UTC)
- Timestamps → `datetime.datetime` with UTC timezone (`tzinfo=timezone.utc`)
- Tickers → uppercase `str`
- Prices → `float`

### Behaviour Rules
- **No hardcoded business parameters.** All values from `get_config()`.
- **Fail closed.** On invalid input: raise a typed exception, write a `system_events` row (where the module contract permits), exit cleanly.
- **MARKET orders are disabled** unless `system.yaml: allow_market_orders: true` is set explicitly.
- **Paper vs live** mode distinction is handled only by S1 and S6. All other modules are mode-agnostic.
- **`init_db(cfg.system.db_url)`** must be called once at each subsystem entry point before any `get_session()` call.
- **`create_all_tables()`** is for setup scripts and integration tests only — never in production entry points.

---

## 6. Key Design Decisions (Resolved)

These are locked. Do not re-debate them.

| Decision | Resolution |
|----------|-----------|
| Queue model | Hybrid: `multiprocessing.Queue` for wakeups; PostgreSQL `SKIP LOCKED` for durable state |
| Approval default | `HARD` (explicit user approval). `SOFT` requires both `system.yaml` change AND dashboard toggle |
| Strategy activation | 4-layer model (system mode → regime → per-stock eligibility → sentiment adjustment). S3 owns this. |
| Paper vs live separation | Config + account_type tag only. Same code path always. |
| Backtest identity | `universe_hash`, `config_hash`, `code_version` (git SHA), `run_id` — all required |
| `target_size_usd` in signals | Written as `0.0` by S3 (placeholder). S6 computes actual size from Kelly + ATR. |
| `BOTH` mode | Single upstream pipeline (S2/S3/S5 run once). S6 launched twice with different `account_type` env vars. |
| Config reload | S7 writes `CONFIG_CHANGED` event → S1 calls `shared.config_loader.invalidate_cache()` → `get_config()` on next use |
| MARKET guard location | Enforced in S6 only. S1 passes mode and account_type cleanly but does not enforce order type. |
| S3 failure events | S3 does not emit a non-canonical event on failure. S1 emits `JOB_FAILED` via the job wrapper. |

---

## 7. Standard Event Types

Only these values are valid for `system_events.event_type`. Do not invent new ones.

```
STARTUP, SHUTDOWN, JOB_STARTED, JOB_COMPLETED, JOB_FAILED, JOB_RETRYING
DATA_READY, DATA_ERROR, DATA_STALE
SENTIMENT_READY, SENTIMENT_ERROR
SIGNALS_READY, SIGNAL_FILTERED
BACKTEST_RESULT, BACKTEST_FAILED
APPROVAL_GRANTED, APPROVAL_DENIED
ORDER_SUBMITTED, ORDER_FILLED, ORDER_REJECTED
POSITION_OPENED, POSITION_CLOSED
RISK_BREACH, RISK_HALT
USER_HALT, USER_RESUME
CONFIG_CHANGED, MODE_CHANGED
```

---

## 8. Implementation Status (as of spec freeze)

| Module | Status |
|--------|--------|
| `shared/` | ✅ Complete |
| S1 Orchestrator | ✅ Complete |
| S2 Data Ingestion | ✅ Complete |
| S3 Signal Engine | ✅ Complete |
| S4 Backtest Validator | ✅ Complete |
| S5 Sentiment Engine | ✅ Complete |
| S6 Execution Engine | 🔲 Not yet built |
| S7 Dashboard | 🔲 Not yet built |
| Integration / wiring | 🔲 In progress |

---

## 9. How to Work in This Project

### Starting a new session
1. Paste this brief as the opening context.
2. Provide the relevant **Module Prompt** (see `./MODULE_PROMPTS.md`) for the subsystem you want to work on.
3. Claude will: read the spec sections listed, summarise current vs target state, propose a step plan, and wait for confirmation before large cross-cutting changes.

### When multiple module prompts are active
- Global rules (this document) always apply.
- Each module prompt narrows or adds requirements for its subsystem.
- If prompts conflict, ask the project owner to resolve before proceeding.

### Response format for any task
1. Identify which subsystem(s) are affected; restate the scope.
2. List which spec sections and code files will be consulted.
3. Summarise current state vs target state.
4. Propose an ordered list of small steps (each step ≤ a few coherent edits + tests).
5. For small, contained steps: proceed immediately.
6. For large or cross-cutting changes: wait for explicit confirmation.
7. After each step, report: files changed, behaviour added/modified, tests added/updated and their status.

---

## 10. File and Directory Conventions

```
algotrader/
├── config/
│   ├── system.yaml
│   ├── risk.yaml
│   ├── universe.yaml
│   ├── strategy_params.yaml
│   └── sentiment_params.yaml
├── shared/
│   ├── config_loader.py
│   ├── db.py
│   ├── models.py
│   ├── logger.py
│   ├── constants.py
│   └── exceptions.py
├── s1_orchestrator/
├── s2_data_ingestion/
├── s3_signal_engine/
├── s4_backtest_validator/
├── s5_sentiment_engine/
├── s6_execution_engine/        ← to be built
├── s7_dashboard/               ← to be built
├── tests/
│   ├── unit/
│   │   ├── shared/
│   │   ├── s1/ ... s7/
│   └── integration/
├── data/
│   ├── processed/ohlcv/
│   ├── processed/returns/
│   └── (raw/ and backtest/ on HDD)
└── logs/
```

**SSD** holds: `config/`, `shared/`, `s*/`, `tests/`, `data/processed/`, `logs/`, active PostgreSQL DB.
**HDD** holds: `data/raw/`, `data/archive/`, `data/backtest/`.

