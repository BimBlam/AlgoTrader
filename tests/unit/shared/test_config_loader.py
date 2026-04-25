"""Unit tests for shared/config_loader.py."""

import pytest
import yaml

from shared.config_loader import get_config, invalidate_cache, load_config
from shared.exceptions import ConfigError


def test_load_valid_config(config_dir):
    cfg = load_config(config_dir)
    assert cfg.system.mode == "PAPER"
    assert cfg.system.approval_mode == "HARD"
    assert cfg.risk.kelly_fraction == 0.25
    assert cfg.universe.sector_etf_map["Technology"] == "XLK"
    assert cfg.strategy_params.stat_arb.min_kappa == 8.4
    assert cfg.sentiment_params.model == "finbert"


def test_hashes_are_populated(config_dir):
    cfg = load_config(config_dir)
    assert len(cfg.universe_hash) == 64
    assert len(cfg.strategy_params_hash) == 64


def test_missing_file_raises_config_error(config_dir):
    (config_dir / "risk.yaml").unlink()
    with pytest.raises(ConfigError, match="risk.yaml"):
        load_config(config_dir)


def test_invalid_mode_raises_config_error(config_dir):
    data = yaml.safe_load((config_dir / "system.yaml").read_text())
    data["mode"] = "INVALID"
    (config_dir / "system.yaml").write_text(yaml.dump(data))
    with pytest.raises(ConfigError):
        load_config(config_dir)


def test_invalid_approval_mode_raises_config_error(config_dir):
    data = yaml.safe_load((config_dir / "system.yaml").read_text())
    data["approval_mode"] = "MAYBE"
    (config_dir / "system.yaml").write_text(yaml.dump(data))
    with pytest.raises(ConfigError):
        load_config(config_dir)


def test_invalid_kelly_raises_config_error(config_dir):
    data = yaml.safe_load((config_dir / "risk.yaml").read_text())
    data["kelly_fraction"] = 1.5
    (config_dir / "risk.yaml").write_text(yaml.dump(data))
    with pytest.raises(ConfigError):
        load_config(config_dir)


def test_get_config_is_cached(config_dir):
    cfg1 = get_config(config_dir)
    cfg2 = get_config(config_dir)
    assert cfg1 is cfg2


def test_invalidate_cache_forces_reload(config_dir):
    cfg1 = get_config(config_dir)
    invalidate_cache()
    cfg2 = get_config(config_dir)
    assert cfg1 is not cfg2


def test_db_url_env_var_substitution(config_dir, monkeypatch):
    monkeypatch.setenv("PGPASSWORD", "secret")
    data = yaml.safe_load((config_dir / "system.yaml").read_text())
    data["db_url"] = "postgresql://user:${PGPASSWORD}@localhost/test"
    (config_dir / "system.yaml").write_text(yaml.dump(data))
    cfg = load_config(config_dir)
    assert "secret" in cfg.system.db_url
    assert "${PGPASSWORD}" not in cfg.system.db_url


def test_missing_env_var_raises_config_error(config_dir, monkeypatch):
    monkeypatch.delenv("PGPASSWORD", raising=False)
    data = yaml.safe_load((config_dir / "system.yaml").read_text())
    data["db_url"] = "postgresql://user:${PGPASSWORD}@localhost/test"
    (config_dir / "system.yaml").write_text(yaml.dump(data))
    with pytest.raises(ConfigError, match="PGPASSWORD"):
        load_config(config_dir)


def test_allow_market_orders_defaults_false(config_dir):
    cfg = load_config(config_dir)
    assert cfg.system.allow_market_orders is False
