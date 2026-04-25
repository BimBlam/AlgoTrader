"""
algotrader.dashboard/config_editor.py

Atomic YAML config read / write / validate for S7.

Write contract (§10 S7 Contract)
---------------------------------
- Always write to a `.tmp` file first, validate against the Pydantic schema,
  then ``os.replace()`` the tmp → real path (POSIX-atomic on same filesystem).
- On validation failure: delete the tmp file and raise ConfigError.
  The original config is never touched.
- No other subsystem may write config files.

Supported sections
------------------
- strategy_params.yaml   (Calibration page — main editing target)
- system.yaml            (Mode switching + approval_mode)
- risk.yaml              (read-only display; editable via calibration)
- sentiment_params.yaml  (read-only display)
- universe.yaml          (read-only display)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from algotrader.shared.config_loader import (
    RiskConfig,
    StrategyParamsConfig,
    SystemConfig,
)
from algotrader.shared.exceptions import ConfigError
from algotrader.shared.logger import get_logger

log = get_logger(__name__)

_DEFAULT_CONFIG_DIR = Path("config")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Failed to parse {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Config file {path} must contain a top-level mapping.")
    return data


def _write_yaml_atomic(path: Path, data: dict[str, Any]) -> None:
    """
    Write *data* to *path* atomically via a temporary sibling file.

    Steps:
    1. Serialise to YAML in a ``.tmp`` sibling file.
    2. Call ``os.replace()`` (POSIX-atomic) to swap into place.
    3. On any exception: clean up the tmp file; never leave a partial write.
    """
    tmp_path = path.parent / (path.name + ".tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as fh:
            yaml.dump(data, fh, default_flow_style=False, sort_keys=False, allow_unicode=True)
        os.replace(tmp_path, path)
        log.info("config_written_atomically", path=str(path))
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise


def _validate(model_cls, data: dict[str, Any], section: str) -> None:
    """Validate *data* against *model_cls*; raise ConfigError on failure."""
    try:
        model_cls(**data)
    except Exception as exc:
        raise ConfigError(f"Validation failed for {section}: {exc}") from exc


# ── Public read API ───────────────────────────────────────────────────────────

def read_strategy_params(config_dir: Path = _DEFAULT_CONFIG_DIR) -> dict[str, Any]:
    return _load_yaml(config_dir / "strategy_params.yaml")


def read_system_config(config_dir: Path = _DEFAULT_CONFIG_DIR) -> dict[str, Any]:
    return _load_yaml(config_dir / "system.yaml")


def read_risk_config(config_dir: Path = _DEFAULT_CONFIG_DIR) -> dict[str, Any]:
    return _load_yaml(config_dir / "risk.yaml")


def read_sentiment_params(config_dir: Path = _DEFAULT_CONFIG_DIR) -> dict[str, Any]:
    return _load_yaml(config_dir / "sentiment_params.yaml")


def read_universe_config(config_dir: Path = _DEFAULT_CONFIG_DIR) -> dict[str, Any]:
    return _load_yaml(config_dir / "universe.yaml")


# ── Public write API ──────────────────────────────────────────────────────────

def update_strategy_params(
    new_data: dict[str, Any],
    config_dir: Path = _DEFAULT_CONFIG_DIR,
) -> None:
    """
    Validate *new_data* against StrategyParamsConfig and atomically overwrite
    ``strategy_params.yaml``.

    Raises ConfigError on validation failure (original file untouched).
    """
    _validate(StrategyParamsConfig, new_data, "strategy_params")
    _write_yaml_atomic(config_dir / "strategy_params.yaml", new_data)


def update_system_config(
    new_data: dict[str, Any],
    config_dir: Path = _DEFAULT_CONFIG_DIR,
) -> None:
    """
    Validate *new_data* against SystemConfig and atomically overwrite
    ``system.yaml``.

    The ``db_url`` field may contain a ``${VAR}`` placeholder; validation
    accepts any non-empty string.

    Raises ConfigError on validation failure (original file untouched).
    """
    # SystemConfig requires db_url to be a non-empty string; placeholders are ok.
    _validate(SystemConfig, new_data, "system")
    _write_yaml_atomic(config_dir / "system.yaml", new_data)


def update_risk_config(
    new_data: dict[str, Any],
    config_dir: Path = _DEFAULT_CONFIG_DIR,
) -> None:
    """Validate and atomically overwrite ``risk.yaml``."""
    _validate(RiskConfig, new_data, "risk")
    _write_yaml_atomic(config_dir / "risk.yaml", new_data)


# ── Convenience: patch a single nested key ───────────────────────────────────

def patch_system_field(
    field: str,
    value: Any,
    config_dir: Path = _DEFAULT_CONFIG_DIR,
) -> dict[str, Any]:
    """
    Read ``system.yaml``, set ``data[field] = value``, validate, and write.

    Returns the full updated dict.
    Raises ConfigError on validation or write failure.
    """
    data = read_system_config(config_dir)
    data[field] = value
    update_system_config(data, config_dir)
    return data
