# AlgoTrader — User Guide

A practical reference for launching, configuring, and operating the system. This document covers every lever the user has over the platform: config files, the dashboard, runtime controls, and the automated schedule.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [First-Time Setup](#2-first-time-setup)
3. [Launching the System](#3-launching-the-system)
4. [The Automated Schedule](#4-the-automated-schedule)
5. [Config Files — What You Can Change](#5-config-files--what-you-can-change)
   - [system.yaml](#systemyaml)
   - [risk.yaml](#riskyaml)
   - [universe.yaml](#universeyaml)
   - [strategy_params.yaml](#strategy_paramsyaml)
   - [sentiment_params.yaml](#sentiment_paramsyaml)
6. [The Dashboard](#6-the-dashboard)
   - [Home](#home-)
   - [Signals](#signals-)
   - [Backtest](#backtest-)
   - [Calibration](#calibration-)
   - [Logs](#logs-)
7. [Signal Lifecycle — Approval Flow](#7-signal-lifecycle--approval-flow)
8. [Risk Guards — When the System Halts](#8-risk-guards--when-the-system-halts)
9. [Switching Between Paper and Live](#9-switching-between-paper-and-live)
10. [Key Reference Tables](#10-key-reference-tables)

---

## 1. Prerequisites

| Requirement                                            | Notes                                                    |
| ------------------------------------------------------ | -------------------------------------------------------- |
| Python 3.11+ virtualenv                                | `source .venv/bin/activate`                              |
| PostgreSQL (running locally)                           | DB must exist before first run                           |
| Interactive Brokers TWS                                | Running on the same machine; API enabled in TWS settings |
| HDD mount at `/run/media/data1/d.Joel/AlgoTrader/raw/` | Or update `data_dir_hdd` in `system.yaml`                |
| GPU (optional)                                         | `cuda:0` used by FinBERT; falls back gracefully to CPU   |

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## 2. First-Time Setup

**1. Configure environment variable for the DB:**

```bash
export DATABASE_URL="postgresql://user:password@localhost:5432/algotrader"
```

Add this to your shell profile (`~/.bashrc` or `~/.zshrc`) so it persists across sessions.

**2. Create config files** — the three optional files are expected at `config/`:

- `config/universe.yaml` — ticker universe and sector ETF mapping
- `config/strategy_params.yaml` — signal engine parameters
- `config/sentiment_params.yaml` — FinBERT model and source settings

See [Section 5](#5-config-files--what-you-can-change) for the full schema of each file.

**3. Initialise the database schema:**

```bash
# Run once — creates all tables via Alembic
alembic upgrade head
```

**4. Verify TWS is running** and API connections are enabled:

- Paper port: `7497`
- Live port: `7496`
- In TWS: `Edit → Global Configuration → API → Enable ActiveX and Socket Clients`
- Set `Trusted IPs` to `127.0.0.1`

---

## 3. Launching the System

The system has two independent processes. Both must be running for full operation.

### Terminal 1 — Orchestrator (S1)

The orchestrator owns the state machine and drives all scheduled work. It must run continuously during trading hours (and overnight for the 21:00 ET jobs).

```bash
python -m s1_orchestrator.main
```

Press `Ctrl+C` for a clean shutdown. S1 will transition to `HALT` state and exit.

### Terminal 2 — Dashboard (S7)

The dashboard is a separate web server. It does not need to be running for the system to operate, but it is the primary way to approve signals and adjust parameters.

```bash
python -m s7_dashboard.main
```

Open in browser: **`http://127.0.0.1:8050`**

### That's it

S1 manages all other subsystems (S2, S3, S4, S5, S6) automatically — you do not launch them manually. They are spawned as worker processes by S1 on schedule.

---

## 4. The Automated Schedule

All times are **America/New_York (ET)**. The schedule runs on weekdays automatically once S1 is running.

| Time              | Job                                  | What happens                                                                                                                                                                            |
| ----------------- | ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **21:00 Mon–Fri** | Data Ingestion (S2) + Sentiment (S5) | Downloads OHLCV for all tickers; scrapes news/social; scores text with FinBERT. Both run in parallel.                                                                                   |
| **21:30 Mon–Fri** | Signal Engine (S3)                   | Fits OU parameters, classifies VIX regime, computes signals, applies sentiment layer. Writes `PENDING` signals to DB.                                                                   |
| **21:30 → 09:25** | Approval window                      | Dashboard shows pending signals. In `HARD` mode, you must approve/deny before 09:25. In `SOFT` mode, S1 auto-approves signals that pass the sentiment threshold.                        |
| **09:25 Mon–Fri** | Execution (S6)                       | Submits LIMIT orders to IBKR for all `APPROVED` signals. `PENDING` signals still in the queue are marked `EXPIRED`.                                                                     |
| **16:30 Mon–Fri** | Reconciliation (S6)                  | Closes positions absent from IBKR portfolio; expires stale APPROVED signals from prior days.                                                                                            |
| **20:00 Sunday**  | Backtest (S4)                        | Walk-forward + Monte Carlo + bootstrap + CSCV validation run. Results appear on the Backtest page. Also triggered automatically when you save strategy params via the Calibration page. |

---

## 5. Config Files — What You Can Change

Config changes take effect at the **next job run** unless you also click "Apply" in the dashboard (which sends a `CONFIG_CHANGED` or `MODE_CHANGED` event to S1 immediately).

---

### `system.yaml`

Controls the fundamental operating mode and infrastructure connections.

```yaml
mode: PAPER # DISABLED | PAPER | LIVE | BOTH
approval_mode: HARD # HARD | SOFT
db_url: "${DATABASE_URL}" # reads from environment variable
ibkr_paper_port: 7497 # TWS paper trading port
ibkr_live_port: 7496 # TWS live trading port
ibkr_client_id: 1 # unique client ID for this TWS session
log_level: INFO # DEBUG | INFO | WARNING | ERROR
log_dir: "logs/"
data_dir_ssd: "data/" # OHLCV parquet and returns (fast storage)
data_dir_hdd: "/mnt/hdd/algotrader/" # raw news/social JSON and backtest output
gpu_device: "cuda:0" # for FinBERT; use "cpu" if no GPU
allow_market_orders: false # true = allow MARKET orders; false = LIMIT only
```

| Field                        | Effect                                                                                                                                                                 |
| ---------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `mode: DISABLED`             | S1 runs but does not dispatch any jobs or submit orders                                                                                                                |
| `mode: PAPER`                | Uses `ibkr_paper_port`; all orders go to paper account                                                                                                                 |
| `mode: LIVE`                 | Uses `ibkr_live_port`; real money                                                                                                                                      |
| `mode: BOTH`                 | Data/signals run once; S6 is launched twice — once for PAPER, once for LIVE                                                                                            |
| `approval_mode: HARD`        | Every signal requires explicit dashboard approval                                                                                                                      |
| `approval_mode: SOFT`        | S1 auto-approves signals whose `sentiment_adj` exceeds `sentiment_threshold_positive`. Only effective in PAPER mode — LIVE always requires a dashboard toggle as well. |
| `allow_market_orders: false` | **Default and recommended.** All orders are LIMIT. Set to `true` only if you intentionally want market orders.                                                         |

**Editable via dashboard:** Yes — the Calibration page has a mode/approval dropdown.

---

### `risk.yaml`

Controls position sizing, portfolio exposure, and automatic halt conditions.

```yaml
max_position_usd: 5000.0 # max dollar value of any single position
max_total_exposure_usd: 50000.0 # max sum of all open position values
max_daily_loss_usd: 1500.0 # triggers system HALT if breached
max_positions_open: 40 # max concurrent open positions
kelly_fraction: 0.25 # 0.25 = quarter-Kelly (conservative)
atr_lookback_days: 14 # ATR window for volatility-based sizing
max_correlation_threshold: 0.4 # reserved; not yet enforced in S6
halt_on_daily_loss: true # auto-halt when max_daily_loss_usd is hit
halt_on_data_failure: true # auto-halt if S2 fails entirely
```

**How sizing works:** S6 computes position size as:

```
raw_size = kelly_fraction × account_equity × win_probability / volatility
size_usd = min(raw_size, max_position_usd)
```

where `volatility` is the 14-day ATR (configurable via `atr_lookback_days`). This is then capped by `max_position_usd`.

**Levers for risk tolerance:**

| To reduce risk                    | To increase risk                                  |
| --------------------------------- | ------------------------------------------------- |
| Lower `kelly_fraction` (e.g. 0.1) | Raise `kelly_fraction` (max 1.0)                  |
| Lower `max_position_usd`          | Raise `max_position_usd`                          |
| Lower `max_total_exposure_usd`    | Raise `max_total_exposure_usd`                    |
| Lower `max_daily_loss_usd`        | Raise `max_daily_loss_usd`                        |
| Keep `halt_on_daily_loss: true`   | Set `halt_on_daily_loss: false` (not recommended) |

**Editable via dashboard:** No — edit the file directly. S1 picks up the change on next config reload.

---

### `universe.yaml`

Defines which tickers the system trades and how sectors map to ETFs.

```yaml
min_market_cap_usd: 1000000000 # minimum market cap filter (1B)
min_avg_daily_volume: 500000 # minimum average daily volume filter
sector_etf_map:
  Technology: XLK
  Healthcare: XLV
  Financials: XLF
  Energy: XLE
  "Consumer Discretionary": XLY
  Industrials: XLI
  Materials: XLB
  Utilities: XLU
  "Real Estate": XLRE
  "Communication Services": XLC
  "Consumer Staples": XLP
tickers:
  - AAPL
  - MSFT
  - GOOGL
  # ... add any US equity ticker here
```

**Important:** Changing `universe.yaml` changes the `universe_hash`, which affects backtest identity. A new backtest run will be recorded as a distinct experiment. Run a fresh backtest (Calibration page → Sunday auto-run) after any universe change.

**Editable via dashboard:** No — edit the file directly.

---

### `strategy_params.yaml`

Controls signal generation logic. This is the primary calibration knob.

```yaml
stat_arb:
  enabled: true
  lookback_days: 60 # OU estimation window (10–252)
  min_kappa: 8.4 # minimum mean-reversion speed (annualised)
  entry_s_score: 1.25 # enter when |s-score| > this value
  exit_s_score_long: 0.5 # exit long when s-score rises above this
  exit_s_score_short: 0.5 # exit short when s-score falls below this
  max_allocation_pct: 0.20 # max portfolio fraction for this strategy

reversal:
  enabled: true
  lookback_days: 5 # return lookback for ranking
  long_decile: 0.10 # buy bottom 10% by return (most oversold)
  short_decile: 0.90 # short top 90% by return (must be > long_decile)
  turnover_split: true # split tied ranks by turnover
  max_allocation_pct: 0.20

regime_combo:
  enabled: true
  vix_sma_lookback: 20 # VIX SMA window for regime classification
  low_vol_strategy: stat_arb # strategy to use in low-volatility regime
  med_vol_strategy: reversal # strategy to use in medium-volatility regime
  high_vol_reduce_pct: 0.5 # scale positions by this fraction in high vol
  extreme_vol_halt: true # halt all execution if VIX is in EXTREME regime
  max_allocation_pct: 0.20

backtest:
  is_window_months: 12 # in-sample window for walk-forward (min 3)
  n_mc_paths: 1000 # GARCH Monte Carlo paths
  n_bootstrap_paths: 500 # stationary bootstrap replications
  bootstrap_block_mean: 10 # average block length in days (2–63)
  n_permutations: 200 # permutation test iterations
  slippage_rate: 0.0015 # one-way slippage (0.15% default)
  include_costs: true # apply transaction costs in simulations
  random_seed: 42 # base RNG seed for reproducibility
```

**Key signal engine controls:**

| Parameter                      | Effect                                                |
| ------------------------------ | ----------------------------------------------------- |
| `stat_arb.enabled: false`      | Disables statistical arbitrage signals entirely       |
| `reversal.enabled: false`      | Disables reversal signals entirely                    |
| `regime_combo.enabled: false`  | System generates raw signals without regime filtering |
| `entry_s_score`                | Higher = fewer but stronger stat-arb signals          |
| `long_decile` / `short_decile` | Tighter = fewer reversal signals; wider = more        |
| `extreme_vol_halt: true`       | System goes quiet during VIX spikes (EXTREME regime)  |
| `high_vol_reduce_pct: 0.5`     | Half-size positions during elevated volatility        |

**Editable via dashboard:** Yes — the Calibration page has a YAML editor with validation. Saving triggers a comparison backtest automatically.

---

### `sentiment_params.yaml`

Controls the FinBERT sentiment model and scraping sources.

```yaml
model: finbert # finbert | openai | llama3 | none
finbert_model_id: "ProsusAI/finbert"
openai_model: "gpt-4o-mini"
llama_host: "http://localhost:11434"
sentiment_threshold_positive: 0.30 # above this = bullish signal (used by SOFT mode auto-approve)
sentiment_threshold_negative: -0.30 # below this = bearish signal
attention_z_threshold: 2.0 # abnormal attention z-score cutoff
attention_lookback_days: 20 # history window for attention baseline

sources:
  reddit:
    enabled: true
    subreddits:
      - wallstreetbets
      - investing
      - stocks
  twitter:
    enabled: false # requires API credentials
  news:
    enabled: true
    provider: "newsapi" # requires NEWSAPI_KEY env var
```

**Sentiment layer (Layer 4) rules:**

| Condition                                                   | Effect on signal                          |
| ----------------------------------------------------------- | ----------------------------------------- |
| `model_used == 'none'` or no data                           | Signal passes at full size (neutral)      |
| Sentiment within `[neg_threshold, pos_threshold]`           | Signal passes at full size (neutral band) |
| Sentiment confirms signal direction                         | Signal passes at full size                |
| Sentiment counter-directional, `abn_attention < threshold`  | Signal passes at half size                |
| Sentiment counter-directional, `abn_attention >= threshold` | Signal is dropped entirely                |

Setting `model: none` disables sentiment scoring — all signals pass at full size.

**Editable via dashboard:** No — edit the file directly.

---

## 6. The Dashboard

Access at `http://127.0.0.1:8050` while `python -m s7_dashboard.main` is running.

---

### Home (`/`)

The overview page. Auto-refreshes every 5 seconds.

- **System State** — current state machine state (IDLE, INGESTING, PENDING_APPROVAL, HALT, etc.)
- **Today's Realised P&L** — sum of closed positions' P&L for today
- **Open Positions** — count of currently open positions
- **Pending Signals** — count of signals awaiting your approval
- **Recent Events** — last 25 system events with timestamp, subsystem, type, severity, and message

Use this page to confirm the system is alive and to spot errors at a glance.

---

### Signals (`/signals`)

The approval interface. Auto-refreshes every 10 seconds.

**Signal table columns:**

| Column        | Meaning                                                                   |
| ------------- | ------------------------------------------------------------------------- |
| Ticker        | Stock symbol                                                              |
| Strategy      | `STAT_ARB`, `REVERSAL`, or `REGIME_COMBO`                                 |
| Side          | `LONG` (buy) or `SHORT` (sell)                                            |
| Score         | Raw signal score from S3                                                  |
| Sentiment Adj | Multiplier from sentiment layer: `1.0` (full), `0.5` (half), `0.0` (skip) |
| Regime        | VIX regime at signal time: `LOW_VOL`, `MED_VOL`, `HIGH_VOL`, `EXTREME`    |
| Created       | When the signal was written by S3                                         |
| Notes         | Optional free-text note (saved with the approval/denial)                  |

**Actions:**

- Click **Approve** — sets signal status to `APPROVED`. S6 will execute this at 09:25 ET.
- Click **Deny** — sets signal status to `DENIED`. Signal is not executed and is recorded for audit.

**SOFT-mode LIVE toggle:** A toggle at the top of the page enables auto-approval for LIVE signals. This toggle is session-scoped (resets on browser refresh) and only has effect when `approval_mode: SOFT` is set in `system.yaml`.

**Deadline:** Any signal still `PENDING` at 09:25 ET is automatically marked `EXPIRED` by the reconciler.

---

### Backtest (`/backtest`)

A table of the last 20 backtest runs. Auto-refreshes every 30 seconds.

| Column        | Meaning                                                           |
| ------------- | ----------------------------------------------------------------- |
| Run At        | When the backtest completed                                       |
| Strategy      | Which strategy(ies) were validated                                |
| Sharpe (OOS)  | Out-of-sample Sharpe ratio                                        |
| Sortino (OOS) | Out-of-sample Sortino ratio                                       |
| Max Drawdown  | Maximum peak-to-trough drawdown                                   |
| PBO           | Probability of Backtest Overfitting (from CSCV). Lower is better. |
| DSR           | Deflated Sharpe Ratio. Accounts for multiple testing bias.        |
| Date Range    | Historical period covered                                         |
| Code Version  | Git SHA at time of run                                            |

**Interpreting results:**

- **PBO < 0.5** is the target threshold — above 0.5 means the IS winner likely underperforms OOS.
- **DSR > 0** means the Sharpe survives deflation for multiple testing. Negative DSR = no real edge.
- A new row appears here automatically every Sunday night, and also after every "Save & Validate" on the Calibration page.

---

### Calibration (`/calibration`)

Three sections for live tuning without restarting anything.

**Section 1 — System Mode:**

- **Mode dropdown:** `DISABLED`, `PAPER`, `LIVE`, `BOTH`
- **Approval Mode dropdown:** `HARD`, `SOFT`
- **Apply Mode Change** button — writes to `system.yaml` and fires `MODE_CHANGED` event. S1 reacts immediately.

**Section 2 — Strategy Parameters:**

- A YAML editor pre-loaded with the current `strategy_params.yaml`
- **Save & Validate** — parses the YAML, validates against the Pydantic schema, writes to disk, fires `CONFIG_CHANGED`. S1 picks this up and schedules a comparison backtest (S4). If validation fails, the file is not written and an error is shown.
- **Reload from File** — discards any unsaved edits and reloads from disk.

**Section 3 — Backtest Comparison:**

- Side-by-side view of the two most recent backtest runs.
- Metrics with deltas: green = improved, red = worsened.
- Use this to judge whether a parameter change was worth it before switching to LIVE.

---

### Logs (`/logs`)

A filterable tail of the `system_events` table. Auto-refreshes every 5 seconds.

**Filters:**

- **Severity:** ALL / INFO / WARNING / ERROR / CRITICAL
- **Subsystem:** ALL / S1 / S2 / S3 / S4 / S5 / S6 / S7 / SYSTEM
- **Max rows:** 50 / 100 / 200 / 500

**Severity colour coding:**

| Severity | Colour   | Meaning                                        |
| -------- | -------- | ---------------------------------------------- |
| INFO     | Light    | Normal operation                               |
| WARNING  | Yellow   | Non-blocking issue (e.g. data partially stale) |
| ERROR    | Red      | Failed step; may trigger retry                 |
| CRITICAL | Bold red | System-halting event                           |

Use the Logs page to diagnose why a job failed, trace the signal lifecycle, or confirm fills were recorded.

---

## 7. Signal Lifecycle — Approval Flow

```
S3 writes signal
       │
       ▼
   status = PENDING
   (visible on Signals page)
       │
       ├─── User clicks Approve ──► status = APPROVED
       │                               │
       ├─── User clicks Deny ────► status = DENIED (not executed)
       │
       └─── 09:25 ET arrives ────► status = EXPIRED (if still PENDING)

   APPROVED signals:
       │
       ▼
   S6 submits LIMIT order to IBKR
       │
       ▼
   status = EXECUTED
   order written to orders table
       │
       ▼
   Fill received from IBKR
   position written to positions table
```

In `SOFT` approval mode with `approval_mode: SOFT` in config:

```
S1 evaluates each PENDING signal's sentiment_adj score
  ├── score >= sentiment_threshold_positive → auto-APPROVED
  └── score < threshold → remains PENDING (awaits manual action)
```

SOFT auto-approval only applies to PAPER mode unless the dashboard LIVE toggle is also enabled.

---

## 8. Risk Guards — When the System Halts

S6 applies guards in two tiers. A **Guard 1** breach halts the entire batch; **Guards 2–7** deny only the individual signal.

| Guard                     | Type       | Condition                                                  | Action                                               |
| ------------------------- | ---------- | ---------------------------------------------------------- | ---------------------------------------------------- |
| Guard 1: Daily loss       | Global     | Realised P&L loss today ≥ `max_daily_loss_usd`             | Halt entire execution batch; emit `RISK_HALT`        |
| Guard 2: Extreme regime   | Per-signal | VIX regime = EXTREME and `extreme_vol_halt: true`          | Deny signal                                          |
| Guard 3: Position cap     | Per-signal | `max_positions_open` already reached                       | Deny signal                                          |
| Guard 4: Exposure cap     | Per-signal | Adding this position would exceed `max_total_exposure_usd` | Deny signal                                          |
| Guard 5: Position size    | Per-signal | Kelly-sized position exceeds `max_position_usd`            | Clip to `max_position_usd` (not denied, just capped) |
| Guard 6: Margin pre-check | Per-signal | IBKR margin check fails                                    | Deny signal                                          |
| Guard 7: ATR validity     | Per-signal | ATR ≤ 0 or NaN (degenerate price series)                   | Deny signal                                          |

**When S1's watchdog halts the system:**

- Any `CRITICAL` severity event from subsystem S1 or S6 triggers an automatic `HALT`.
- The system transitions to `HALT` state and stops dispatching jobs.

**Manual halt and resume via dashboard:**

- The Home page has **HALT** and **RESUME** buttons.
- HALT writes a `USER_HALT` event; RESUME writes a `USER_RESUME` event.
- S1 reacts to these events and transitions state accordingly.

---

## 9. Switching Between Paper and Live

The recommended procedure for going from paper to live:

1. **Review the Backtest page** — confirm PBO < 0.5 and DSR > 0 for recent runs.
2. **Verify IBKR connection** — TWS must be running with live API enabled on port `7496`.
3. **Open the Calibration page** — change Mode from `PAPER` to `LIVE`, click Apply.
4. **Keep `approval_mode: HARD`** for the first live session — approve every signal manually.
5. **Set conservative risk limits in `risk.yaml`** — lower `max_position_usd` and `max_total_exposure_usd` for the first live run.
6. **Monitor the Logs page** at 09:25 ET to confirm orders are submitted and fills are received.

To run paper and live simultaneously (`BOTH` mode):

- S2 / S3 / S5 run once (one set of signals).
- S6 is launched **twice** by S1: once with `ACCOUNT_TYPE=PAPER` (port 7497) and once with `ACCOUNT_TYPE=LIVE` (port 7496).
- Both accounts receive the same approved signals.

To disable all trading without stopping the orchestrator:

```yaml
# config/system.yaml
mode: DISABLED
```

Apply via the Calibration page or restart S1.

---

## 10. Key Reference Tables

### System States

| State                | Meaning                                                     |
| -------------------- | ----------------------------------------------------------- |
| `DISABLED`           | Mode is DISABLED; no jobs run                               |
| `STARTING`           | S1 is initialising                                          |
| `IDLE`               | Waiting for next scheduled event                            |
| `INGESTING`          | S2 + S5 are running                                         |
| `PROCESSING`         | S3 is computing signals                                     |
| `PENDING_APPROVAL`   | Signals written; waiting for user approval or auto-approval |
| `APPROVED`           | All signals actioned; waiting for 09:25 ET                  |
| `PARTIALLY_APPROVED` | Some approved, some denied                                  |
| `EXECUTING`          | S6 is submitting orders to IBKR                             |
| `MONITORING`         | Orders submitted; waiting for fills and end of day          |
| `RECONCILING`        | S6 is reconciling positions against IBKR portfolio          |
| `HALT`               | System halted (risk breach, critical error, or manual halt) |

### Signal Statuses

| Status     | Meaning                                             |
| ---------- | --------------------------------------------------- |
| `PENDING`  | Awaiting approval                                   |
| `APPROVED` | Approved; will be executed at 09:25 ET              |
| `DENIED`   | Rejected by user; not executed                      |
| `EXECUTED` | Order submitted to IBKR                             |
| `EXPIRED`  | Still PENDING when execution window opened; skipped |

### VIX Regimes (assigned by S3)

| Regime     | Behaviour                                                    |
| ---------- | ------------------------------------------------------------ |
| `LOW_VOL`  | `regime_combo` uses `low_vol_strategy` (default: `stat_arb`) |
| `MED_VOL`  | `regime_combo` uses `med_vol_strategy` (default: `reversal`) |
| `HIGH_VOL` | Positions scaled down by `high_vol_reduce_pct`               |
| `EXTREME`  | All execution halted if `extreme_vol_halt: true`             |

### Subsystem IDs (for log filtering)

| ID  | Name               |
| --- | ------------------ |
| S1  | Orchestrator       |
| S2  | Data Ingestion     |
| S3  | Signal Engine      |
| S4  | Backtest Validator |
| S5  | Sentiment Engine   |
| S6  | Execution Engine   |
| S7  | Dashboard          |

### IBKR Ports

| Mode          | Port | Config field      |
| ------------- | ---- | ----------------- |
| Paper trading | 7497 | `ibkr_paper_port` |
| Live trading  | 7496 | `ibkr_live_port`  |

---

_For architecture, DB schema, and implementation details see `.docs/Frozen Project Specification v1.0.md`._
