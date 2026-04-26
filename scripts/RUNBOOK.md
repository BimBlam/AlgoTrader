# AlgoTrader Production Runbook

## Installation

```bash
# 1. Clone and bootstrap
git clone git@github.com:BimBlam/AlgoTrader.git /opt/algotrader
cd /opt/algotrader
sudo useradd -r -s /bin/false algotrader
sudo chown -R algotrader:algotrader /opt/algotrader

# 2. Run bootstrap (creates venv, DB, directories)
make bootstrap

# 3. Install systemd units
sudo cp scripts/systemd/*.service /etc/systemd/system/
sudo cp scripts/systemd/algotrader.logrotate /etc/logrotate.d/algotrader
sudo systemctl daemon-reload

# 4. Optional: set Reddit credentials
sudo systemctl edit algotrader.service
# Add:
# [Service]
# Environment=REDDIT_CLIENT_ID=your_id
# Environment=REDDIT_CLIENT_SECRET=your_secret
```

## Starting

```bash
# Start PostgreSQL first
sudo systemctl start postgresql

# Start orchestrator (runs the scheduler, spawns workers)
sudo systemctl start algotrader

# Start dashboard (optional, for web UI)
sudo systemctl start algotrader-dashboard

# Verify
sudo systemctl status algotrader
sudo journalctl -u algotrader -f
```

## Stopping

```bash
# Graceful stop — sends SIGTERM, waits for running workers
sudo systemctl stop algotrader

# Emergency halt — also writes USER_HALT event to DB
# (preferred method: use dashboard HALT button instead)
sudo systemctl stop algotrader
```

## HALT / RESUME Procedure

**Preferred method:** Use the dashboard.

1. Open dashboard (default http://localhost:8050)
2. Click **HALT** → confirm in modal
3. S1 event handler detects USER_HALT event within 30 seconds
4. State machine transitions to HALT; running workers receive SIGTERM
5. No new jobs are scheduled until RESUME

**Resume:**
1. Click **RESUME** in dashboard
2. S1 transitions HALT → IDLE
3. Normal scheduling resumes on next cron tick

## Mode Switching (PAPER → LIVE)

1. Dashboard → Calibration page
2. Change Mode to LIVE, Approval to HARD
3. Click **Apply Mode Change**
4. S1 writes MODE_CHANGED event; on next poll it reloads config
5. **Paper trading gate:** System enforces 3+ months profitable paper trading before LIVE orders are accepted

## DB Backup

```bash
# Daily cron job
pg_dump -Fc algotrader > /mnt/hdd/algotrader/backups/algotrader-$(date +%Y%m%d).dump
```

## IBKR Connection Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ConnectionRefused` on port 7497 | TWS not running / API not enabled | Start TWS, enable Edit → Global Configuration → API → "Enable ActiveX and Socket Clients" |
| `Duplicate client ID` | Another client using ID 1 | Change `ibkr_client_id` in system.yaml or close other clients |
| Orders rejected with `203` | Account not funded / not subscribed to market data | Check IBKR Account Management |
| No market data | Outside RTH (09:30–16:00 ET) | Normal — system only submits pre-market orders |

## Upgrading Strategy Parameters

1. Dashboard → Calibration → edit YAML
2. Click **Save & Validate**
3. S1 queues a comparison backtest (RUNBACKTEST job)
4. Review backtest diff on Calibration page
5. If improved: change mode to trigger live use
6. If degraded: click **Reload from File** to revert

## Log Locations

| Path | Content |
|---|---|
| `/opt/algotrader/logs/algotrader.log` | Main structured log (JSON) |
| `journalctl -u algotrader` | systemd journal (stdout/stderr) |
| Dashboard → Logs page | Live tail of system_events table |

## Emergency Contacts / Escalation

- **Halt trading immediately:** Dashboard HALT button or `sudo systemctl stop algotrader`
- **Review open positions:** Dashboard → Signals page, or `psql -d algotrader -c "SELECT * FROM positions WHERE status='OPEN'"`
- **Kill a stuck worker:** `sudo systemctl stop algotrader-worker@ingestion` (or signals, backtest, etc.)
