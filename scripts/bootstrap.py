#!/usr/bin/env python3
"""AlgoTrader bootstrap — one-command setup for a fresh machine.

Run:  python3 scripts/bootstrap.py [--paper|--live]

What it does:
  1. Verify Python >= 3.11
  2. Create / verify data directories (data/raw, data/processed, data/cache, logs, output)
  3. Create / verify virtualenv at .venv/
  4. Install Python dependencies (requirements.txt + requirements-dev.txt)
  5. Verify / start PostgreSQL, create database, run Alembic migrations
  6. Pre-download FinBERT model weights (~500 MB) to HuggingFace cache
  7. Run a quick import smoke-test for every subsystem
  8. Print a ready-to-run summary

Prerequisites on the host:
  - Python 3.11+ with python3-venv
  - PostgreSQL server (psql, createdb, pg_ctl in PATH)
  - git
  - ~2 GB free disk space (venv + models)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIRS = [
    "data/raw",
    "data/processed",
    "data/cache",
    "logs",
    "output",
]
REQUIREMENTS = ["requirements.txt", "requirements-dev.txt"]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
CONFIG_DIR = REPO_ROOT / "config"
VENV_DIR = REPO_ROOT / ".venv"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str], *, check: bool = True, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run a shell command, streaming stdout/stderr."""
    print(f"  → {' '.join(cmd)}")
    return subprocess.run(
        cmd,
        check=check,
        cwd=cwd or REPO_ROOT,
        env={**os.environ, **(env or {})},
        text=True,
        capture_output=False,
    )


def _run_quiet(cmd: list[str], *, check: bool = True, cwd: Path | None = None) -> str:
    """Run a command and return stdout."""
    result = subprocess.run(
        cmd,
        check=check,
        cwd=cwd or REPO_ROOT,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def _warn(msg: str) -> None:
    print(f"  ⚠️  {msg}")


def _ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def _fail(msg: str) -> None:
    print(f"  ❌ {msg}")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

def step_python() -> None:
    """1. Verify Python version."""
    print("\n[1/8] Python version check")
    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 11):
        _fail(f"Python {major}.{minor} found — need >= 3.11")
    _ok(f"Python {major}.{minor}.{sys.version_info.micro}")


def step_dirs() -> None:
    """2. Create data directories."""
    print("\n[2/8] Data directories")
    for rel in DATA_DIRS:
        path = REPO_ROOT / rel
        path.mkdir(parents=True, exist_ok=True)
        _ok(f"{rel}/")

    # Also ensure the HDD mount point exists (warn if not)
    try:
        from algotrader.shared.config_loader import get_config  # type: ignore
        cfg = get_config()
        hdd = Path(cfg.system.data_dir_hdd)
        hdd.mkdir(parents=True, exist_ok=True)
        _ok(f"HDD data dir: {hdd}")
    except Exception as exc:
        _warn(f"Could not create HDD data dir: {exc}")


def step_venv() -> None:
    """3. Create / verify virtualenv."""
    print("\n[3/8] Virtualenv")
    if VENV_DIR.exists():
        _ok(f"Existing venv at {VENV_DIR}")
        return

    _run([sys.executable, "-m", "venv", str(VENV_DIR)])
    _ok(f"Created venv at {VENV_DIR}")


def _pip(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run pip inside the venv."""
    pip = VENV_DIR / "bin" / "pip"
    return _run([str(pip), *args], check=check)


def step_deps() -> None:
    """4. Install dependencies."""
    print("\n[4/8] Dependencies")
    _pip("install", "--upgrade", "pip")
    for req in REQUIREMENTS:
        req_path = REPO_ROOT / req
        if not req_path.exists():
            _warn(f"{req} not found — skipping")
            continue
        _pip("install", "-r", str(req_path))
    _ok("Dependencies installed")


def step_postgres() -> None:
    """5. PostgreSQL: verify running, create DB, run migrations."""
    print("\n[5/8] PostgreSQL")

    # Check psql exists
    try:
        version = _run_quiet(["psql", "--version"])
        _ok(f"psql: {version}")
    except FileNotFoundError:
        _fail("psql not found — install PostgreSQL (e.g. pacman -S postgresql)")

    # Try to connect as current user; if the server is not running, start it.
    try:
        _run_quiet(["psql", "-d", "postgres", "-c", "SELECT 1"])
        _ok("PostgreSQL server is running")
    except subprocess.CalledProcessError:
        _warn("PostgreSQL not running — attempting to start")
        # Try common init / start paths
        pgdata = Path("/var/lib/postgres/data")
        if not (pgdata / "PG_VERSION").exists():
            _run(["sudo", "-u", "postgres", "initdb", "-D", str(pgdata)], check=False)
        _run(["sudo", "-u", "postgres", "pg_ctl", "-D", str(pgdata), "start"], check=False)
        # Retry connection
        try:
            _run_quiet(["psql", "-d", "postgres", "-c", "SELECT 1"])
            _ok("PostgreSQL started successfully")
        except subprocess.CalledProcessError:
            _fail("Could not start PostgreSQL — start it manually and re-run")

    # Create database if it doesn't exist
    db_name = "algotrader"
    try:
        _run_quiet(["psql", "-d", "postgres", "-c", f"CREATE DATABASE {db_name}"])
        _ok(f"Created database '{db_name}'")
    except subprocess.CalledProcessError:
        _ok(f"Database '{db_name}' already exists")

    # Run Alembic migrations
    if not ALEMBIC_INI.exists():
        _fail(f"alembic.ini not found at {ALEMBIC_INI}")
    alembic = VENV_DIR / "bin" / "alembic"
    _run([str(alembic), "-c", str(ALEMBIC_INI), "upgrade", "head"])
    _ok("Alembic migrations applied")


def step_finbert() -> None:
    """6. Pre-download FinBERT model weights."""
    print("\n[6/8] FinBERT model download")
    python = VENV_DIR / "bin" / "python"
    script = (
        "from transformers import pipeline; "
        "pipe = pipeline('text-classification', model='ProsusAI/finbert', device=-1); "
        "print('FinBERT loaded OK')"
    )
    try:
        _run([str(python), "-c", script])
        _ok("FinBERT model cached")
    except subprocess.CalledProcessError as exc:
        _warn(f"FinBERT download failed: {exc}")
        _warn("Sentiment engine will download on first use (slower)")


def step_smoke_test() -> None:
    """7. Quick import smoke-test for every subsystem."""
    print("\n[7/8] Smoke tests")
    python = VENV_DIR / "bin" / "python"
    modules = [
        "algotrader.orchestrator.main",
        "algotrader.ingestion.main",
        "algotrader.signals.main",
        "algotrader.backtest.main",
        "algotrader.sentiment.main",
        "algotrader.execution.main",
        "algotrader.dashboard.main",
    ]
    for mod in modules:
        try:
            _run_quiet([str(python), "-c", f"import {mod}"])
            _ok(f"import {mod}")
        except subprocess.CalledProcessError as exc:
            _fail(f"import {mod} failed: {exc}")


def step_summary() -> None:
    """8. Print ready summary."""
    print("\n" + "=" * 60)
    print("  AlgoTrader bootstrap complete")
    print("=" * 60)
    print(f"""
  Next steps:

    1. Start the orchestrator (paper mode):
       source .venv/bin/activate
       python -m algotrader.cli orchestrator

    2. Or run individual subsystems:
       python -m algotrader.cli <subsystem> <run_id>

    3. Start the dashboard:
       python -m algotrader.cli dashboard

    4. Verify DB connectivity:
       psql -d algotrader -c "\\dt"

  Optional credentials (set before enabling in config):
    export REDDIT_CLIENT_ID="..."
    export REDDIT_CLIENT_SECRET="..."
    export DATABASE_URL="postgresql://localhost/algotrader"

  Config files:
    {CONFIG_DIR}/system.yaml      — mode, DB URL, IBKR ports
    {CONFIG_DIR}/risk.yaml        — position limits, halt rules
    {CONFIG_DIR}/strategy_params.yaml — strategy toggles
    {CONFIG_DIR}/sentiment_params.yaml — sentiment model, social sources
""")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap AlgoTrader")
    parser.add_argument("--paper", action="store_true", help="Force PAPER mode")
    parser.add_argument("--live", action="store_true", help="Force LIVE mode (not recommended for bootstrap)")
    args = parser.parse_args()

    if args.live:
        print("⚠️  LIVE mode requested — this is dangerous on a fresh install.")
        confirm = input("   Type 'LIVE' to confirm: ")
        if confirm != "LIVE":
            print("Aborting.")
            return 1

    step_python()
    step_dirs()
    step_venv()
    step_deps()
    step_postgres()
    step_finbert()
    step_smoke_test()
    step_summary()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
