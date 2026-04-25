"""
tests/unit/s4/test_loader.py

Unit tests for load_returns_history().  All file I/O uses tmp_path so
no real filesystem state is required.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest



def _write_returns_parquet(path: Path, n_dates: int = 10,
                           n_tickers: int = 5) -> pd.DataFrame:
    """Write a minimal valid returns parquet to `path`; return the DataFrame."""
    rng = np.random.default_rng(0)
    start = datetime.date(2022, 1, 3)
    dates = pd.bdate_range(start=start, periods=n_dates).date.tolist()
    tickers = [f"T{i:02d}" for i in range(n_tickers)]
    rows = []
    for d in dates:
        for t in tickers:
            rows.append({
                "date": d, "ticker": t,
                "ret1d": float(rng.normal(0, 0.01)),
                "ret5d": float(rng.normal(0, 0.02)),
                "volume": int(rng.integers(1_000_000, 5_000_000)),
                "avg_vol30": float(rng.integers(1_000_000, 5_000_000)),
                "turnover": float(rng.uniform(0.001, 0.05)),
                "sector_etf": "XLK",
            })
    df = pd.DataFrame(rows).set_index(["date", "ticker"])
    df.to_parquet(path)
    return df


@pytest.fixture
def cfg_with_tmp(tmp_path, mock_cfg):
    """Patch cfg.system.data_dir_ssd to a temp directory."""
    returns_dir = tmp_path / "processed" / "returns"
    returns_dir.mkdir(parents=True)
    mock_cfg.system.data_dir_ssd = str(tmp_path)
    return mock_cfg, returns_dir


def test_load_returns_happy_path(cfg_with_tmp):
    """Single valid parquet file → DataFrame with correct MultiIndex."""
    from s4_backtest_validator.loader import load_returns_history
    cfg, returns_dir = cfg_with_tmp
    _write_returns_parquet(returns_dir / "2022-01-03.parquet", n_dates=10)
    df = load_returns_history(cfg)
    assert isinstance(df.index, pd.MultiIndex)
    assert df.index.names == ["date", "ticker"]
    assert "ret1d" in df.columns
    assert len(df) > 0


def test_load_returns_multiple_files(cfg_with_tmp):
    """Multiple parquet files are concatenated correctly."""
    from s4_backtest_validator.loader import load_returns_history
    cfg, returns_dir = cfg_with_tmp
    _write_returns_parquet(returns_dir / "2022-01.parquet", n_dates=10)
    _write_returns_parquet(returns_dir / "2022-02.parquet", n_dates=10)
    df = load_returns_history(cfg)
    # Should have rows from both files (some dates may overlap — dedup not required)
    assert len(df) > 50  # at least 10 dates × 5 tickers per file


def test_load_returns_tickers_uppercase(cfg_with_tmp):
    """Loader enforces uppercase tickers regardless of source case."""
    from s4_backtest_validator.loader import load_returns_history
    cfg, returns_dir = cfg_with_tmp
    fp = returns_dir / "lower.parquet"
    _write_returns_parquet(fp)
    # Manually lower-case the tickers in the parquet
    df = pd.read_parquet(fp).reset_index()
    df["ticker"] = df["ticker"].str.lower()
    df.set_index(["date", "ticker"]).to_parquet(fp)
    result = load_returns_history(cfg)
    tickers = result.index.get_level_values("ticker")
    assert all(t == t.upper() for t in tickers)


def test_load_returns_empty_dir_raises(cfg_with_tmp):
    """Empty returns directory raises DataError."""
    from s4_backtest_validator.loader import load_returns_history
    from shared.exceptions import DataError
    cfg, returns_dir = cfg_with_tmp
    # No files written
    with pytest.raises(DataError, match="No returns parquets"):
        load_returns_history(cfg)


def test_load_returns_corrupt_file_skipped(cfg_with_tmp):
    """A corrupt parquet file is skipped with a warning; valid files load."""
    from s4_backtest_validator.loader import load_returns_history
    cfg, returns_dir = cfg_with_tmp
    _write_returns_parquet(returns_dir / "good.parquet", n_dates=10)
    (returns_dir / "bad.parquet").write_bytes(b"not a parquet file")
    df = load_returns_history(cfg)
    assert len(df) > 0  # good file loaded despite corrupt sibling


def test_load_returns_all_corrupt_raises(cfg_with_tmp):
    """If all files are corrupt, DataError is raised."""
    from s4_backtest_validator.loader import load_returns_history
    from shared.exceptions import DataError
    cfg, returns_dir = cfg_with_tmp
    (returns_dir / "bad1.parquet").write_bytes(b"garbage")
    (returns_dir / "bad2.parquet").write_bytes(b"garbage")
    with pytest.raises(DataError, match="unreadable"):
        load_returns_history(cfg)