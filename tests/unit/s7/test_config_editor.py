"""tests/unit/s7/test_config_editor.py"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from shared.exceptions import ConfigError
from s7_dashboard.config_editor import (
    _load_yaml,
    _validate,
    _write_yaml_atomic,
    patch_system_field,
    read_strategy_params,
    update_strategy_params,
    update_system_config,
)
from shared.config_loader import RiskConfig


# ── _load_yaml ────────────────────────────────────────────────────────────────

class TestLoadYaml:
    def test_loads_valid_yaml(self, tmp_path):
        p = tmp_path / "test.yaml"
        p.write_text("key: value\nnested:\n  a: 1\n")
        result = _load_yaml(p)
        assert result == {"key": "value", "nested": {"a": 1}}

    def test_raises_when_file_missing(self, tmp_path):
        with pytest.raises(ConfigError, match="not found"):
            _load_yaml(tmp_path / "nonexistent.yaml")

    def test_raises_on_invalid_yaml(self, tmp_path):
        p = tmp_path / "bad.yaml"
        p.write_text("key: [unclosed\n")
        with pytest.raises(ConfigError, match="Failed to parse"):
            _load_yaml(p)

    def test_raises_when_top_level_is_not_mapping(self, tmp_path):
        p = tmp_path / "list.yaml"
        p.write_text("- item1\n- item2\n")
        with pytest.raises(ConfigError, match="top-level mapping"):
            _load_yaml(p)


# ── _write_yaml_atomic ────────────────────────────────────────────────────────

class TestWriteYamlAtomic:
    def test_writes_file(self, tmp_path):
        p = tmp_path / "out.yaml"
        _write_yaml_atomic(p, {"key": "value"})
        assert p.exists()
        content = yaml.safe_load(p.read_text())
        assert content == {"key": "value"}

    def test_tmp_file_is_removed_after_success(self, tmp_path):
        p = tmp_path / "out.yaml"
        _write_yaml_atomic(p, {"a": 1})
        tmp = tmp_path / "out.yaml.tmp"
        assert not tmp.exists()

    def test_replaces_existing_file(self, tmp_path):
        p = tmp_path / "out.yaml"
        p.write_text("old: data\n")
        _write_yaml_atomic(p, {"new": "data"})
        content = yaml.safe_load(p.read_text())
        assert content == {"new": "data"}
        assert "old" not in content

    def test_cleans_up_tmp_on_os_replace_failure(self, tmp_path, monkeypatch):
        p = tmp_path / "out.yaml"

        def bad_replace(src, dst):
            raise OSError("disk full")

        monkeypatch.setattr(os, "replace", bad_replace)
        with pytest.raises(OSError, match="disk full"):
            _write_yaml_atomic(p, {"key": "val"})
        # tmp file should be cleaned up
        tmp = tmp_path / "out.yaml.tmp"
        assert not tmp.exists()

    def test_preserves_unicode(self, tmp_path):
        p = tmp_path / "unicode.yaml"
        _write_yaml_atomic(p, {"label": "résumé"})
        content = yaml.safe_load(p.read_text(encoding="utf-8"))
        assert content["label"] == "résumé"


# ── _validate ─────────────────────────────────────────────────────────────────

class TestValidate:
    def test_passes_valid_risk_config(self):
        data = {
            "max_position_usd": 5000.0,
            "max_total_exposure_usd": 50000.0,
            "max_daily_loss_usd": 1500.0,
            "max_positions_open": 40,
            "kelly_fraction": 0.25,
            "atr_lookback_days": 14,
            "extreme_vol_halt": True,
            "halt_on_daily_loss": True,
            "halt_on_data_failure": True,
        }
        _validate(RiskConfig, data, "risk")  # should not raise

    def test_raises_on_invalid_kelly(self):
        data = {
            "max_position_usd": 5000.0,
            "max_total_exposure_usd": 50000.0,
            "max_daily_loss_usd": 1500.0,
            "max_positions_open": 40,
            "kelly_fraction": 1.5,  # invalid: > 1.0
            "atr_lookback_days": 14,
            "extreme_vol_halt": True,
            "halt_on_daily_loss": True,
            "halt_on_data_failure": True,
        }
        with pytest.raises(ConfigError, match="Validation failed"):
            _validate(RiskConfig, data, "risk")

    def test_raises_on_missing_required_field(self):
        with pytest.raises(ConfigError, match="Validation failed"):
            _validate(RiskConfig, {}, "risk")


# ── read helpers ──────────────────────────────────────────────────────────────

class TestReadHelpers:
    def _write_minimal_strategy(self, tmp_path) -> Path:
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        data = {
            "stat_arb": {"enabled": True, "lookback_days": 252, "min_kappa": 8.4,
                          "entry_s_score": 2.0, "exit_s_score_long": 0.5,
                          "exit_s_score_short": -0.5, "max_allocation_pct": 0.05},
            "reversal": {"enabled": False, "lookback_days": 20, "long_decile": 0.1,
                         "short_decile": 0.9, "turnover_split": False,
                         "max_allocation_pct": 0.05},
            "regime_combo": {"enabled": False, "vix_sma_lookback": 20,
                             "low_vol_strategy": "STAT_ARB",
                             "med_vol_strategy": "REVERSAL",
                             "high_vol_reduce_pct": 0.5,
                             "max_allocation_pct": 0.05},
        }
        (cfg_dir / "strategy_params.yaml").write_text(yaml.dump(data))
        return cfg_dir

    def test_read_strategy_params_returns_dict(self, tmp_path):
        cfg_dir = self._write_minimal_strategy(tmp_path)
        result = read_strategy_params(cfg_dir)
        assert isinstance(result, dict)
        assert "stat_arb" in result

    def test_read_raises_when_file_missing(self, tmp_path):
        cfg_dir = tmp_path / "empty_config"
        cfg_dir.mkdir()
        with pytest.raises(ConfigError):
            read_strategy_params(cfg_dir)


# ── update_strategy_params ────────────────────────────────────────────────────

class TestUpdateStrategyParams:
    def _minimal_valid_data(self):
        return {
            "stat_arb": {"enabled": True, "lookback_days": 252, "min_kappa": 8.4,
                          "entry_s_score": 2.0, "exit_s_score_long": 0.5,
                          "exit_s_score_short": -0.5, "max_allocation_pct": 0.05},
            "reversal": {"enabled": False, "lookback_days": 20, "long_decile": 0.1,
                         "short_decile": 0.9, "turnover_split": False,
                         "max_allocation_pct": 0.05},
            "regime_combo": {"enabled": False, "vix_sma_lookback": 20,
                             "low_vol_strategy": "STAT_ARB",
                             "med_vol_strategy": "REVERSAL",
                             "high_vol_reduce_pct": 0.5,
                             "max_allocation_pct": 0.05},
        }

    def test_writes_valid_data(self, tmp_path):
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        (cfg_dir / "strategy_params.yaml").write_text("")
        data = self._minimal_valid_data()
        update_strategy_params(data, cfg_dir)
        written = yaml.safe_load((cfg_dir / "strategy_params.yaml").read_text())
        assert written["stat_arb"]["enabled"] is True

    def test_raises_on_invalid_data_does_not_overwrite(self, tmp_path):
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        original = "# original\nstat_arb:\n  enabled: true\n"
        (cfg_dir / "strategy_params.yaml").write_text(original)
        with pytest.raises(ConfigError):
            update_strategy_params({"invalid": "data"}, cfg_dir)
        # Original file untouched
        assert (cfg_dir / "strategy_params.yaml").read_text() == original

    def test_no_tmp_file_left_after_success(self, tmp_path):
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        (cfg_dir / "strategy_params.yaml").write_text("")
        update_strategy_params(self._minimal_valid_data(), cfg_dir)
        assert not (cfg_dir / "strategy_params.yaml.tmp").exists()


# ── update_system_config ──────────────────────────────────────────────────────

class TestUpdateSystemConfig:
    def _valid_system(self):
        return {
            "mode": "PAPER",
            "approval_mode": "HARD",
            "db_url": "${DATABASE_URL}",
            "ibkr_paper_port": 7497,
            "ibkr_live_port": 7496,
            "ibkr_client_id": 1,
        }

    def test_writes_valid_system_config(self, tmp_path):
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        (cfg_dir / "system.yaml").write_text("")
        update_system_config(self._valid_system(), cfg_dir)
        written = yaml.safe_load((cfg_dir / "system.yaml").read_text())
        assert written["mode"] == "PAPER"

    def test_raises_on_invalid_mode(self, tmp_path):
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        (cfg_dir / "system.yaml").write_text("")
        data = self._valid_system()
        data["mode"] = "INVALID_MODE"
        with pytest.raises(ConfigError):
            update_system_config(data, cfg_dir)


# ── patch_system_field ────────────────────────────────────────────────────────

class TestPatchSystemField:
    def _write_system_yaml(self, cfg_dir: Path) -> None:
        data = {
            "mode": "PAPER",
            "approval_mode": "HARD",
            "db_url": "${DATABASE_URL}",
            "ibkr_paper_port": 7497,
            "ibkr_live_port": 7496,
            "ibkr_client_id": 1,
        }
        (cfg_dir / "system.yaml").write_text(yaml.dump(data))

    def test_patches_single_field(self, tmp_path):
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        self._write_system_yaml(cfg_dir)
        result = patch_system_field("mode", "LIVE", cfg_dir)
        assert result["mode"] == "LIVE"
        written = yaml.safe_load((cfg_dir / "system.yaml").read_text())
        assert written["mode"] == "LIVE"
        # Other fields preserved
        assert written["approval_mode"] == "HARD"

    def test_returns_full_updated_dict(self, tmp_path):
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        self._write_system_yaml(cfg_dir)
        result = patch_system_field("approval_mode", "SOFT", cfg_dir)
        assert isinstance(result, dict)
        assert "mode" in result
        assert "db_url" in result

    def test_raises_if_patch_makes_config_invalid(self, tmp_path):
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        self._write_system_yaml(cfg_dir)
        with pytest.raises(ConfigError):
            patch_system_field("mode", "NONSENSE", cfg_dir)
