You are implementing the Execution Engine (S6) for the AlgoTrader system.

This system is a modular, multi-process algorithmic trading platform for US equities, running via Interactive Brokers Canada (non-registered margin account, IBKR TWS API).

## Frozen Specification Reference

All conventions, data models, enums, event types, config schemas, risk rules, and coding standards are defined in the AlgoTrader Frozen Project Specification v1.0 (Frozen Project Specification v1.0.md).
Every decision in that document is final for this module. Do not deviate.

Key reminders:

- All shared utilities must be imported from shared/ only config_loader, db, logger, constants, exceptions, models)
- All dates are datetime.date (UTC). All timestamps are datetime.datetime with UTC timezone.
- All tickers are uppercase str. All prices are float.
- No module may import from another subsystem module.
- No hardcoded values. All parameters from config via get_config().
- No print(). All output via shared.logger.get_logger(**name**).
- Fail closed: on invalid input, raise typed exception and write system_events row.
- MARKET orders are disabled unless allow_market_orders: true in system.yaml.
- Paper vs live distinction is handled by S1 and S6 only. Do not add mode-checking logic here.

## Module Contract — S6 — Execution Engine

**Purpose:** Translate approved signals into IBKR limit orders, manage the full order lifecycle, enforce pre-flight risk guards, and maintain position records. The only module with direct IBKR API access.

**Responsibilities:**

- Poll `signals` table for status=`APPROVED`; process in batches before market open
- Run all risk guards from Section 7.1; raise `RiskBreach` on any failure
- Compute final position sizes using quarter-Kelly and ATR methods from `risk.yaml`
- Build limit orders (never market orders unless override set); submit via `ib_insync`
- Write each order to `orders` table immediately on submission
- Track fills via IBKR callbacks; update `orders` and `positions` tables within 60 seconds
- Reconcile end-of-day: close any positions the strategy has exited; write `POSITION_CLOSED`
- In `PAPER` mode: route to `ibkr_paper_port`; tag `account_type='PAPER'`
- In `LIVE` mode: route to `ibkr_live_port`; tag `account_type='LIVE'`
- In `BOTH` mode: two instances run with separate account tags; signal sets are distinct

**Inputs:** `signals` table (status=`APPROVED`), `positions` table, `config/risk.yaml`, `config/system.yaml`, live IBKR TWS connection

**Outputs:** `orders` rows, `positions` rows, `system_events` rows

**Must not:** Generate signals, score sentiment, run backtests, modify `signals` table (except to set status=`EXECUTED`), run in any state other than `EXECUTING` or `MONITORING`

**Failure mode:** On `RiskBreach`: write `RISK_HALT` CRITICAL event, set system state to `HALT`, cancel all pending orders. On IBKR connection loss: write `CRITICAL` event, attempt reconnect ×3, then `HALT`.

## Deliverable

Produce the full implementation for the Execution Engine.

Rules:

- Use Python 3.11+
- Use SQLAlchemy 2.0 ORM (not raw SQL)
- Use structlog for logging
- Use pydantic v2 for config validation
- Use pytest for tests (place in tests/unit/[module_id]/)
- Write clear docstrings on all public functions and classes
- Do not over-comment: explain why, not what
- No placeholder TODOs: every function must be complete or raise NotImplementedError with a clear message if intentionally deferred
- Include a requirements section at the top listing which packages this module needs (subset of the global requirements.txt)

The build order is fixed at:

shared/ — must exist before any other module can be written
**DONE**

S2 (data ingestion) — the spine of everything; nothing else runs without data **DONE**

S5 (sentiment) — can be built and tested independently while S3 is drafted
**DONE**

S3 (signal engine) — depends on S2 output shape and S5 scores
**DONE**

S4 (backtest validator) — depends on S2 output shape; can be built in parallel with S3
**DONE**

S1 (orchestrator) — depends on all worker module contracts being stable
**DONE**

S6 (execution engine) — depends on S1 and S3 being complete
**WHAT YOU WILL BE WORKING ON**

S7 (dashboard) — can read the DB as soon as S1 + S3 exist; built last
