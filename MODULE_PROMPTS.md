# AlgoTrader – Module Prompts
> **Usage:** In a Claude Code session, always load the Global Project Brief first, then paste the relevant module prompt(s) below for your current task.
> Module prompts are additive. Global rules always apply. If two prompts conflict, ask the project owner to resolve.

---

## Template

```
# Module Prompt – [SUBSYSTEM NAME]

**Target subsystem(s):** [e.g. S6 Execution Engine]

**Spec sections to consult:**
- [list specific sections from the frozen spec, e.g. §2.3 Daily Timeline, §4.2 DB Schema, §7.1 Risk Guards, §10 S6 Contract]

**Codebase to read:**
- [e.g. s6_execution_engine/, shared/models.py, shared/constants.py]

**Current state:**
[One paragraph: what exists, what works, what is missing or broken.]

**Target state:**
[One paragraph: what this session must deliver. Be specific.]

**Scope of work:**
- ✅ In scope: [explicit list of what may be changed]
- 🚫 Out of scope: [explicit list of what must NOT be changed]

**Additional constraints:**
- [Any constraints beyond the global rules, e.g. "no new DB tables", "do not change existing signal schema", "reuse existing EventType enums only"]

**Required outputs:**
- [New or updated Python files]
- [Test files under tests/unit/<subsystem>/]
- [Config or doc changes, if any]

**Working style:**
1. Read the spec sections and existing code listed above.
2. In your own words: summarise current behaviour and the delta this prompt introduces.
3. Propose a step-by-step implementation plan (each step ≤ a few coherent edits + tests).
4. Execute the plan, keeping changes within the declared scope.
5. After each step, report: files changed, behaviour added/modified, tests added/updated and their pass status.
```

---

## Module Prompt – shared/

**Target subsystem(s):** `shared/`

**Spec sections to consult:**
- §8.1 Shared Utilities table
- §8.2 Universal Rules
- §4.2 Canonical DB Tables (ORM source of truth)
- §4.3 Standard Event Types
- §3.1 Mode Definitions (SystemMode enum)
- §3.2 Approval Mode (ApprovalMode enum)
- §3.3 State Machine (SystemState enum)
- §10 Contract: shared/

**Codebase to read:**
- `shared/` (all files)
- `tests/unit/shared/`

**Current state:**
`shared/` is complete. It provides `config_loader.py` (AppConfig, pydantic v2, invalidate_cache), `db.py` (init_db, get_session, engine management), `models.py` (all ORM table classes), `logger.py` (structlog JSON), `constants.py` (all enums including SignalStatus, added post-spec), `exceptions.py` (typed exception hierarchy). `allow_market_orders` field exists in SystemConfig (default False). `AppConfig` exposes `universe_hash` and `strategy_params_hash` computed at load time.

**Target state:**
Any missing field, enum value, or ORM column revealed during integration work must be added here first, before the consuming subsystem is modified. This prompt is used to patch `shared/` in isolation.

**Scope of work:**
- ✅ In scope: adding fields to config models, adding enum values, adding ORM columns (with Alembic migration), adding exception subclasses
- 🚫 Out of scope: any business logic, any I/O beyond config file read and DB session, imports from any subsystem

**Additional constraints:**
- `create_all_tables()` must not be called in production entry points — setup scripts and integration tests only
- New enum values must be added to `constants.py` only; never defined inline in subsystem code
- Schema changes require an Alembic migration file; do not use `create_all_tables()` to migrate

**Required outputs:**
- Updated files in `shared/`
- Updated tests in `tests/unit/shared/`
- Alembic migration file for any schema change

---

## Module Prompt – S1 Orchestrator

**Target subsystem(s):** S1 (`s1_orchestrator/`)

**Spec sections to consult:**
- §2.1 Process Model
- §2.2 Queue/DB Handoff Pattern
- §2.3 Daily Execution Timeline
- §3.1–3.3 Runtime Modes and State Machine
- §4.2 `jobs` table schema
- §4.3 Standard Event Types (S1 emits: STARTUP, SHUTDOWN, JOB_STARTED, JOB_COMPLETED, JOB_FAILED, JOB_RETRYING, RISK_HALT, MODE_CHANGED)
- §6.2 Parameter Calibration Lifecycle (CONFIG_CHANGED handling)
- §7.2 Halt and Resume
- §7.3 Paper vs Live Distinction
- §10 Contract: S1 Orchestrator
- §12 S1 Implementation Log (deviations)

**Codebase to read:**
- `s1_orchestrator/` (all files)
- `shared/constants.py` (SystemMode, SystemState, ApprovalMode, JobStatus, EventType)
- `shared/models.py` (Job, SystemEvent)
- `tests/unit/s1/`

**Current state:**
S1 is complete. Key resolved deviations: `force_halt()` bypasses the transition table for HALT-from-any-state; stale-job timeouts are per job type (defined in S1 internals); `BOTH` mode runs S6 twice with different `account_type` env vars; `SOFT` auto-approval uses `cfg.sentiment.sentiment_threshold_positive` as the confidence cutoff; `CONFIG_CHANGED` triggers `invalidate_cache()` + re-queue of a backtest run.

**Target state:**
Use this prompt when wiring S1 to a newly completed downstream module (e.g. S6, S7) or when patching the state machine for an integration issue.

**Scope of work:**
- ✅ In scope: changes to job scheduling, state transitions, event emission, worker launch logic, approval flow
- 🚫 Out of scope: signal generation, sentiment scoring, order submission, UI rendering, direct IBKR API calls

**Additional constraints:**
- Do not add mode-checking logic in any module other than S1 (and S6 for order routing)
- Stale-job timeout values are internal to S1 and adjustable without a spec change
- The `force_halt()` method must remain as the mechanism for HALT-from-any-state

**Required outputs:**
- Updated files in `s1_orchestrator/`
- Updated tests in `tests/unit/s1/`

---

## Module Prompt – S2 Data Ingestion

**Target subsystem(s):** S2 (`s2_data_ingestion/`)

**Spec sections to consult:**
- §2.3 Daily Execution Timeline (S2 runs at 21:00 ET)
- §4.1 Storage Allocation
- §4.4 Parquet Schema Contracts (OHLCV and returns)
- §5.3 `universe.yaml` schema
- §5.5 `sentiment_params.yaml` (source list consumed by S2 for scraping)
- §10 Contract: S2 Data Ingestion
- §12 S2 Implementation Log (deviations)

**Codebase to read:**
- `s2_data_ingestion/` (main.py, downloader.py, returns.py, scraper.py, validator.py, utils.py)
- `shared/models.py` (Job, SystemEvent)
- `tests/unit/s2/`

**Current state:**
S2 is complete. Key resolved deviations: package is `s2_data_ingestion` not `s2`; raw file paths use `cfg.system.data_dir_hdd / raw / <source> / <DATE>.json`; ticker metadata is prefetched in a single pass. S5 reads raw files from these exact paths — do not change the output path convention.

**Target state:**
Use this prompt to patch data quality issues, add new data sources, or fix scraper failures.

**Scope of work:**
- ✅ In scope: downloader logic, OHLCV validation rules, returns computation, scraper targets, file output paths
- 🚫 Out of scope: sentiment scoring, signal generation, DB tables other than `system_events` and `jobs`, changes to parquet schema columns (those require a spec revision)

**Additional constraints:**
- Raw files must be written atomically — never overwrite; create new dated files only
- Do not change the canonical output paths that S5 depends on (see S2 deviation §2 in implementation log)
- If >20% of universe tickers fail validation, emit `DATA_ERROR` and halt the job; otherwise emit `DATA_STALE` and continue

**Required outputs:**
- Updated files in `s2_data_ingestion/`
- Updated tests in `tests/unit/s2/`

---

## Module Prompt – S3 Signal Engine

**Target subsystem(s):** S3 (`s3_signal_engine/`)

**Spec sections to consult:**
- §4.4 Returns parquet schema (input)
- §4.2 `signals`, `ou_params` tables (output)
- §4.3 Event Types (S3 emits: SIGNALS_READY, SIGNAL_FILTERED)
- §5.4 `strategy_params.yaml`
- §6.1 Strategy Activation Model (4-layer)
- §10 Contract: S3 Signal Engine
- §12 S3 Implementation Log (deviations)

**Codebase to read:**
- `s3_signal_engine/` (all files)
- `shared/models.py` (Signal, OuParams, SystemEvent)
- `shared/constants.py` (SignalStrategy, SignalSide, SignalStatus, EventType)
- `tests/unit/s3/`

**Current state:**
S3 is complete. Key resolved deviations: `target_size_usd` is written as `0.0` (S6 computes final size); S3 does not emit a non-canonical event on failure — S1 emits `JOB_FAILED` via the job wrapper; logging calls use `log.info("event_name", ...)` pattern without `event=` keyword; `SIGNAL_FILTERED` structlog field was corrected to avoid collision.

**Target state:**
Use this prompt to patch OU fitting logic, adjust strategy selection rules, or fix signal writing issues.

**Scope of work:**
- ✅ In scope: OU fitting, s-score computation, reversal ranking, regime classification, sentiment adjustment logic, signal writing
- 🚫 Out of scope: order submission, sentiment model calls, config file writes, IBKR API, imports from S2/S5

**Additional constraints:**
- `target_size_usd` must remain `0.0` on write — S6 is the sole owner of position sizing
- S3 must not emit any `system_events` row with an event type not in the canonical list
- All strategy logic must use parameters exclusively from `cfg.strategy_params`

**Required outputs:**
- Updated files in `s3_signal_engine/`
- Updated tests in `tests/unit/s3/`

---

## Module Prompt – S4 Backtest Validator

**Target subsystem(s):** S4 (`s4_backtest_validator/`)

**Spec sections to consult:**
- §4.2 `backtest_runs` table
- §4.3 Event Types (S4 emits: BACKTEST_RESULT, BACKTEST_FAILED)
- §9.1 Testing levels
- §9.2 Backtest Identity Requirements
- §10 Contract: S4 Backtest Validator
- §12 S4 Implementation Log (deviations)

**Codebase to read:**
- `s4_backtest_validator/` (main.py, loader.py, strategy_sim.py, walk_forward.py, monte_carlo.py, bootstrap.py, permutation.py, cscv.py, metrics.py, costs.py, writer.py, config_schema.py)
- `shared/models.py` (BacktestRun, Job)
- `tests/unit/s4/`

**Current state:**
S4 is complete. Key resolved deviations: look-ahead bias fixed (signal on T, capture on T+1); MC GARCH uses manual simulation for RNG determinism; MC evaluation parallelised via `ThreadPoolExecutor(max_workers=min(8, cpu_count))`; CSCV IS/OOS mapping fixed; circular-shift permutation re-dates fixed; `derive_strategy_cfg()` computes strategy name from enabled flags; `config_hash` sourced from jobs table row not live config; `get_backtest_config()` called at entry point with pydantic v2 validation.

**Target state:**
Use this prompt to add new permutation tests, patch metric calculations, or fix walk-forward window logic.

**Scope of work:**
- ✅ In scope: simulation logic, metric computation, permutation battery, CSCV, output writing, config validation
- 🚫 Out of scope: config file writes, order submission, automatic parameter approval, imports from other subsystems

**Additional constraints:**
- Walk-forward gate: `pbo < 0.40` AND `sharpe > 0.8` required for live activation (live enforcement is S1's responsibility; S4 only computes and records)
- Every backtest run must record all four identity fields — runs without them are invalid
- `check_for_duplicate_run()` must query before proceeding; a match emits WARNING but does not block

**Required outputs:**
- Updated files in `s4_backtest_validator/`
- Updated tests in `tests/unit/s4/`

---

## Module Prompt – S5 Sentiment Engine

**Target subsystem(s):** S5 (`s5_sentiment_engine/`)

**Spec sections to consult:**
- §4.2 `sentiment_scores` table
- §4.3 Event Types (S5 emits: SENTIMENT_READY, SENTIMENT_ERROR)
- §5.5 `sentiment_params.yaml`
- §10 Contract: S5 Sentiment Engine
- §12 S2 Implementation Log note on `utils.py` (utcnow/utctoday, no tests yet)

**Codebase to read:**
- `s5_sentiment_engine/` (all files)
- `shared/models.py` (SentimentScore, SystemEvent)
- `shared/constants.py` (EventType)
- `tests/unit/s5/`

**Current state:**
S5 is complete as a standalone module. Input paths are `cfg.system.data_dir_hdd / raw / news / <DATE>.json` and `cfg.system.data_dir_hdd / raw / social / <DATE>.json` (must match S2 output exactly). FinBERT runs on `cfg.system.gpu_device`. Model fallback chain: `finbert → none`. Every universe ticker gets a row even if no mentions exist (`sentiment_res=0.0`, `abn_attention=0.0`, `model_used='none'`).

**Target state:**
Use this prompt to add model backends (OpenAI, Llama), fix residualisation logic, or patch ticker aggregation.

**Scope of work:**
- ✅ In scope: text preprocessing, model inference, aggregation, residualisation, DB writing
- 🚫 Out of scope: signal generation, order submission, IBKR API, raw file writing (S2 owns that), config file writes

**Additional constraints:**
- Input paths must exactly match S2's output paths — do not change them without coordinating with S2
- `SENTIMENT_ERROR` is a WARNING-severity event — S5 must not halt the pipeline unless total failure
- GPU inference must be gated on `cfg.system.gpu_device` — must fall back to CPU gracefully

**Required outputs:**
- Updated files in `s5_sentiment_engine/`
- Updated tests in `tests/unit/s5/`

---

## Module Prompt – S6 Execution Engine

**Target subsystem(s):** S6 (`s6_execution_engine/`) — **NOT YET BUILT**

**Spec sections to consult:**
- §2.3 Daily Execution Timeline (S6 runs at 09:25 and 16:30 ET)
- §4.2 `signals`, `orders`, `positions` tables
- §4.3 Event Types (S6 emits: ORDER_SUBMITTED, ORDER_FILLED, ORDER_REJECTED, POSITION_OPENED, POSITION_CLOSED, RISK_BREACH, RISK_HALT)
- §5.1 `system.yaml` (`ibkr_paper_port`, `ibkr_live_port`, `allow_market_orders`)
- §5.2 `risk.yaml` (all fields)
- §7.1 Risk Guards (pre-flight checklist — implement all 7 guards)
- §7.2 Halt and Resume
- §7.3 Paper vs Live Distinction
- §8.2 Universal Rules (MARKET order guard)
- §10 Contract: S6 Execution Engine
- §12 S1 Implementation Log §7 (market-order guard location)
- §12 shared/ Implementation Log §2 (`allow_market_orders` field)

**Codebase to read:**
- `shared/` (all — especially models.py, constants.py, exceptions.py)
- `s1_orchestrator/` (understand how S6 is launched and what env vars it receives)
- `tests/unit/s6/` (create if absent)

**Current state:**
S6 does not exist yet. S1 is wired to launch S6 worker processes with `account_type` environment variable set to `PAPER` or `LIVE`. The `signals`, `orders`, and `positions` ORM models exist in `shared/models.py`. Risk config is available via `get_config().risk`.

**Target state:**
A complete, tested S6 implementation that: polls `signals` for `APPROVED` status; runs all 7 risk guards from §7.1; computes position sizes via quarter-Kelly + ATR; submits limit orders via `ib_insync`; tracks fills via IBKR callbacks; reconciles end-of-day; emits correct events; halts cleanly on `RiskBreach` or IBKR connection loss.

**Scope of work:**
- ✅ In scope: everything in `s6_execution_engine/`, unit tests in `tests/unit/s6/`
- 🚫 Out of scope: signal generation, sentiment scoring, backtesting, config file writes, any changes to `shared/` models without a separate `shared/` prompt

**Additional constraints:**
- Suggested internal structure: `main.py`, `risk_guards.py`, `sizer.py`, `order_builder.py`, `ibkr_client.py`, `fill_tracker.py`, `reconciler.py`, `writer.py`
- `account_type` must be read from the environment variable provided by S1 — never from a hardcoded string
- Reconnect logic: 3 attempts with exponential backoff before emitting CRITICAL and triggering HALT
- All 7 risk guards in §7.1 must be implemented in `risk_guards.py` and called as a single pre-flight function `run_preflight_guards(signal, session, cfg)`
- `target_size_usd` in the `signals` table is always `0.0` from S3 — S6 computes final size and updates `orders.quantity` accordingly
- MARKET orders: check `cfg.system.allow_market_orders` before building any non-LIMIT order

**Required outputs:**
- Complete `s6_execution_engine/` package
- Tests in `tests/unit/s6/` (mock IBKR, mock DB session)
- No changes to other subsystems unless a gap in `shared/` is discovered (raise as a separate `shared/` prompt)

---

## Module Prompt – S7 Dashboard

**Target subsystem(s):** S7 (`s7_dashboard/`) — **NOT YET BUILT**

**Spec sections to consult:**
- §3.1–3.3 Runtime Modes and State Machine (display and control)
- §4.2 All DB tables (S7 reads all; writes only `signals` and `system_events`)
- §4.3 Event Types (S7 emits: APPROVAL_GRANTED, APPROVAL_DENIED, USER_HALT, USER_RESUME, CONFIG_CHANGED, MODE_CHANGED)
- §5.1–5.4 Config schemas (S7 is the only module that writes config files)
- §6.2 Parameter Calibration Lifecycle (steps 1–7 — S7 owns steps 1–3 and 5–6)
- §7.2 Halt and Resume (S7 owns the HALT and RESUME UI controls)
- §10 Contract: S7 Dashboard
- §12 S1 Implementation Log §5 (CONFIG_CHANGED handling and config reload)

**Codebase to read:**
- `shared/` (all — especially models.py, constants.py, config_loader.py)
- `s1_orchestrator/` (understand state machine states — S7 displays and controls them)
- `tests/unit/s7/` (create if absent)

**Current state:**
S7 does not exist yet. The DB tables it reads from are all fully defined in `shared/models.py`. The `CONFIG_CHANGED` / `APPROVAL_GRANTED` event pathway is wired in S1 — S7 just needs to write the correct event to `system_events` and S1 will react.

**Target state:**
A local Dash (Plotly Dash) web application with five pages: Home, Signals, Backtest, Calibration, Logs. Persistent HALT/RESUME controls visible on all pages. Mode switching control with confirmation dialog. All writes atomic with rollback on failure.

**Scope of work:**
- ✅ In scope: everything in `s7_dashboard/`, unit tests in `tests/unit/s7/`
- 🚫 Out of scope: IBKR API calls, signal/sentiment model execution, order submission, changes to other subsystems

**Additional constraints:**
- Suggested internal structure: `app.py` (Dash init), `layout.py` (shared nav/header), `pages/home.py`, `pages/signals.py`, `pages/backtest.py`, `pages/calibration.py`, `pages/logs.py`, `callbacks/`, `writer.py` (DB event writes), `config_editor.py` (YAML read/write/validate with rollback)
- Config writes: always write to a `.tmp` file first, validate, then atomically rename — never write partial config
- `SOFT` auto-approval in `LIVE` mode requires both: `approval_mode=SOFT` in `system.yaml` AND a dashboard toggle — neither alone is sufficient (§3.2)
- Dashboard crash must not affect any other subsystem — run as a completely independent process
- Use `shared.db.get_session()` for all DB access — no direct SQL

**Required outputs:**
- Complete `s7_dashboard/` package
- Tests in `tests/unit/s7/` (mock DB session, mock config writes)
- No changes to other subsystems unless a gap in `shared/` is discovered (raise as a separate `shared/` prompt)

---

## Module Prompt – Integration / Wiring

**Target subsystem(s):** Cross-cutting (S1 ↔ S2/S3/S5, S1 ↔ S6, S1 ↔ S7, end-to-end pipeline)

**Spec sections to consult:**
- §2.1 Process Model (full diagram)
- §2.2 Queue/DB Handoff
- §2.3 Daily Execution Timeline (end-to-end sequence)
- §3.3 System State Machine (all transitions)
- §7.2 Halt and Resume
- §12 All implementation logs (deviations that affect wiring)

**Codebase to read:**
- All subsystem `main.py` entry points
- `s1_orchestrator/` (scheduler, worker launcher, event loop)
- `shared/db.py`, `shared/models.py`
- `tests/integration/`

**Current state:**
S1–S5 are individually complete. S6 and S7 are not yet built. End-to-end integration tests do not exist. The queue/DB handoff pattern is implemented in S1 but has not been tested against real S2/S3/S5 worker processes.

**Target state:**
A working end-to-end paper-mode pipeline: S1 schedules → S2 ingests → S5 scores → S3 signals → S1 approves (SOFT/PAPER) → S6 executes on IBKR paper → S7 displays state. All integration tests pass against a test PostgreSQL instance with mocked IBKR.

**Scope of work:**
- ✅ In scope: entry point wiring, environment variable passing, integration tests, systemd unit file stubs
- 🚫 Out of scope: changes to any subsystem's internal business logic (raise a separate module prompt if logic changes are needed)

**Additional constraints:**
- Integration tests must use a real PostgreSQL instance (local, test DB), not SQLite
- No real IBKR API calls in integration tests — use `ib_insync` mock
- Systemd unit files go in `deploy/systemd/` — one unit per process

**Required outputs:**
- Updated entry points if wiring gaps are found
- Tests in `tests/integration/`
- `deploy/systemd/*.service` stub files
- `README.md` quick-start section

