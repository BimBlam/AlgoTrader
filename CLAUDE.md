# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Authoritative References

| Reference                                    | Purpose                                                                                                                                          |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `.docs/Frozen Project Specification v1.0.md` | **FROZEN — source of record.** Architecture, DB schema, contracts, configs, coding standards. If any conflict exists between sources, this wins. |
| `.docs/implementation-log.md`                | Living log of resolved deviations and design decisions (not overrides)                                                                           |
| `ALGOTRADER_GLOBAL_BRIEF.md`                 | System overview and subsystem map                                                                                                                |
| `MODULE_PROMPTS.md`                          | Task-scoped development prompts per subsystem                                                                                                    |

Always read the relevant spec sections before implementing in a subsystem.

## Commands

```bash
# Activate virtualenv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Run all tests (395 unit tests)
python -m pytest

# Run tests for a single subsystem
python -m pytest tests/unit/s3/
python -m pytest tests/unit/shared/

# Run a single test file or test
python -m pytest tests/unit/s3/test_ou_fitting.py
python -m pytest tests/unit/s3/test_ou_fitting.py::test_kappa_positive

# Linting
ruff check .

# Type checking
mypy shared/ s1_orchestrator/ s2_data_ingestion/ s3_signal_engine/ s4_backtest_validator/ s5_sentiment/
```

Tests live under `tests/unit/<subsystem>/`. Each subsystem has a `conftest.py` providing shared fixtures (`mock_cfg`, `mock_session`, etc.).

## Architecture

AlgoTrader is a **modular, multi-process algorithmic trading platform** for US equities via Interactive Brokers Canada (TWS API). It runs on a single Linux workstation and supports paper, live, and parallel paper+live ("BOTH") modes.

### Subsystem Map

| ID  | Directory                | Status       | Responsibility                                                     |
| --- | ------------------------ | ------------ | ------------------------------------------------------------------ |
| —   | `shared/`                | ✅ Complete  | Config, DB session, ORM models, logging, enums, exceptions         |
| S1  | `s1_orchestrator/`       | ✅ Complete  | State machine, APScheduler jobs, process lifecycle, halt policy    |
| S2  | `s2_data_ingestion/`     | ✅ Complete  | OHLCV download (yfinance), log-returns parquet, news/social scrape |
| S3  | `s3_signal_engine/`      | ✅ Complete  | OU fitting, s-scores, reversal/regime signals, sentiment layer     |
| S4  | `s4_backtest_validator/` | ✅ Complete  | Walk-forward, Monte Carlo (GARCH), bootstrap, CSCV, PBO            |
| S5  | `s5_sentiment/`          | ✅ Complete  | FinBERT scoring, attention z-score, residualisation                |
| S6  | `s6_execution/`          | ✅ Complete  | IBKR order submission, fill tracking, risk guards                  |
| S7  | `s7_dashboard/`          | ✅ Complete  | Dash UI: approval, calibration, monitoring, halt/resume            |

**Critical rule: No subsystem may import from another subsystem package.** All cross-cutting utilities come from `shared/` only.

### Data Flow

```
[Cron 21:00 ET weekdays]
      ├──► S2 (Data Ingestion)  → OHLCV + returns parquet, raw scrape JSON
      └──► S5 (Sentiment)       → sentiment_scores DB table
                │
          [DATA_READY + SENTIMENT_READY]
                │
               S3 (Signal Engine) → signals table (status=PENDING), ou_params
                │
          [Approval window: 22:00–09:20 ET]
          S7 writes APPROVED/DENIED, or S1 auto-approves (SOFT + PAPER)
                │
          [09:25 ET: SIGNALS_APPROVED]
               S6 (Execution Engine) → IBKR TWS → orders, positions tables
                │
          [Weekly Sunday 20:00 ET]
               S4 (Backtest Validator) → backtest_runs table + HDD output
```

Inter-process communication: `multiprocessing.Queue` for wakeup tokens only; PostgreSQL `SELECT ... FOR UPDATE SKIP LOCKED` for durable job state; Parquet files for market data passed between S2 → S3/S4.

### Shared Utilities (`shared/`)

```python
from shared.config_loader import get_config        # AppConfig (pydantic v2, cached)
from shared.db import get_session, init_db         # SQLAlchemy 2.0
from shared.models import Signal, Order, ...       # ORM models (all tables)
from shared.constants import SystemMode, EventType, SignalStatus, ...
from shared.exceptions import RiskBreach, DataError, SignalError, ...
from shared.logger import get_logger               # structlog, JSON format
```

- `init_db(cfg.system.db_url)` must be called once at each subsystem entry point before any `get_session()` call.
- `create_all_tables()` is for the setup script and integration tests only — never in production entry points. Schema changes require an Alembic migration.
- `get_config()` returns a cached `AppConfig`. Call `shared.config_loader.invalidate_cache()` before re-reading after a `CONFIG_CHANGED` event.
- `AppConfig` exposes `universe_hash` and `strategy_params_hash` (SHA-256, computed at load time) — S4 reads these directly rather than hashing files itself.

### Configuration (`config/`)

| File                    | Content                                                                              |
| ----------------------- | ------------------------------------------------------------------------------------ |
| `system.yaml`           | Mode (PAPER/LIVE/BOTH), approval mode, DB URL, `allow_market_orders` (default false) |
| `risk.yaml`             | Position limits, Kelly fraction, halt conditions                                     |
| `universe.yaml`         | Tickers, sector/ETF mapping                                                          |
| `strategy_params.yaml`  | StatArb/Reversal/RegimeCombo settings                                                |
| `sentiment_params.yaml` | FinBERT model path, scraping sources, thresholds                                     |

All business parameters come from `get_config()` — nothing hardcoded.

### File Storage

- **SSD:** `config/`, `shared/`, `s*/`, `tests/`, `data/processed/` (OHLCV + returns parquet), `logs/`, active PostgreSQL DB
- **HDD** (`cfg.system.data_dir_hdd`): `raw/news/YYYY-MM-DD.json`, `raw/social/YYYY-MM-DD.json`, `data/archive/`, `data/backtest/`

S5 constructs raw input paths as `cfg.system.data_dir_hdd / "raw" / "news" / f"{date}.json"`.

## Coding Rules

- **SQLAlchemy 2.0 ORM only** — no raw SQL strings in application code.
- **`structlog` for all logging** — no `print()`. Pass event name as first positional arg: `log.info("event_name", field=value)` — do not use `event=` as a keyword (collides with structlog's reserved parameter).
- **Pydantic v2** for config validation.
- **Fail closed:** on invalid input, raise a typed exception, log via structlog, exit cleanly. S3 and similar modules do not write non-canonical `system_events` rows on failure — S1 emits `JOB_FAILED` via its job wrapper.
- **EventType enum is closed.** Only use values defined in `shared/constants.py`. Do not invent new event types.
- **`target_size_usd = 0.0`** in signals written by S3 is intentional — S6 computes actual size from Kelly + ATR.
- **MARKET orders are disabled** unless `cfg.system.allow_market_orders` is explicitly `true`. Enforcement lives in S6 only.
- **Paper vs live** distinction is handled only by S1 (scheduling) and S6 (order submission). All other modules are mode-agnostic.
- **BOTH mode:** S2/S3/S5 run once. S6 launches twice with different `account_type` env vars (PAPER and LIVE).
- Dates → `datetime.date` (UTC). Timestamps → `datetime.datetime` with `tzinfo=timezone.utc`. Tickers → uppercase `str`. Prices → `float`.

## Key Resolved Design Decisions

These are locked — do not re-debate them.

| Decision            | Resolution                                                                                                                                        |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| Queue model         | Hybrid: `multiprocessing.Queue` for wakeups; PostgreSQL `SKIP LOCKED` for durable state                                                           |
| Approval default    | `HARD` (explicit user approval). `SOFT` requires both `system.yaml` change AND dashboard toggle                                                   |
| Strategy activation | 4-layer model: system mode → regime → per-stock eligibility → sentiment adjustment (S3 owns all layers)                                           |
| Backtest identity   | `universe_hash`, `config_hash` (from jobs table row, not live config), `code_version` (git SHA), `run_id`                                         |
| S4 `config_hash`    | Read from the `jobs` table row at startup, not from `get_config()`, to survive mid-run config changes                                             |
| S3 failure events   | S3 exits with code 1 on failure; does not write non-canonical events. S1 emits `JOB_FAILED`.                                                      |
| Sentiment Layer 4   | Direction-aware multiplier `{1.0, 0.5, 0.0}` using both `sentiment_res` and `abn_attention`                                                       |
| S4 Monte Carlo      | GARCH path generation sequential (arch not thread-safe); strategy evaluation parallelised via `ThreadPoolExecutor(max_workers=min(8, cpu_count))` |

## Working Style for New Sessions

When starting work on a subsystem:

1. Read the relevant spec sections from `.docs/Frozen Project Specification v1.0.md`.
2. Check `.docs/implementation-log.md` for deviations already resolved.
3. Summarise current state vs target state.
4. Propose an ordered step plan (each step ≤ a few coherent edits + tests).
5. For small contained steps: proceed. For large or cross-cutting changes: wait for confirmation.
6. After each step, report: files changed, behaviour added/modified, tests added/updated and their pass status.
