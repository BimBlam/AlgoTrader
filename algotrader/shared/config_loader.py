"""
shared/config_loader.py

Parses and validates all YAML config files under config/.
Returns a single typed AppConfig object; raises ConfigError on any
missing file, unparseable YAML, or failed Pydantic validation.

Config is cached after the first successful load so all modules in the
same process share one parse.  Use invalidate_cache() in tests or after
a CONFIG_CHANGED event.
"""
import hashlib
import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from algotrader.shared.exceptions import ConfigError

# ── Pydantic models ───────────────────────────────────────────────────────────

class SystemConfig(BaseModel):
    mode: str
    approval_mode: str
    db_url: str
    ibkr_paper_port: int
    ibkr_live_port: int
    ibkr_client_id: int
    log_level: str = "INFO"
    log_dir: str = "logs/"
    data_dir_ssd: str = "data/"
    data_dir_hdd: str = "/mnt/hdd/algotrader/"
    gpu_device: str = "cuda:0"
    allow_market_orders: bool = False

    @field_validator("mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        allowed = {"DISABLED", "PAPER", "LIVE", "BOTH"}
        if v not in allowed:
            raise ValueError(f"mode must be one of {allowed}, got {v!r}")
        return v

    @field_validator("approval_mode")
    @classmethod
    def _approval_mode(cls, v: str) -> str:
        allowed = {"HARD", "SOFT"}
        if v not in allowed:
            raise ValueError(f"approval_mode must be one of {allowed}, got {v!r}")
        return v

    @field_validator("log_level")
    @classmethod
    def _log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in allowed:
            raise ValueError(f"log_level must be one of {allowed}, got {v!r}")
        return v.upper()


class RiskConfig(BaseModel):
    max_position_usd: float
    max_total_exposure_usd: float
    max_daily_loss_usd: float
    max_positions_open: int
    kelly_fraction: float
    atr_lookback_days: int
    extreme_vol_halt: bool = True
    halt_on_daily_loss: bool
    halt_on_data_failure: bool

    @field_validator("kelly_fraction")
    @classmethod
    def _kelly(cls, v: float) -> float:
        if not 0.0 < v <= 1.0:
            raise ValueError(f"kelly_fraction must be in (0, 1], got {v}")
        return v


class UniverseConfig(BaseModel):
    min_market_cap_usd: float
    min_avg_daily_volume: float
    sector_etf_map: dict[str, str]
    tickers: list[str] = Field(default_factory=list)


class StatArbParams(BaseModel):
    enabled: bool
    lookback_days: int
    min_kappa: float
    entry_s_score: float
    exit_s_score_long: float
    exit_s_score_short: float
    max_allocation_pct: float


class ReversalParams(BaseModel):
    enabled: bool
    lookback_days: int
    long_decile: float
    short_decile: float
    turnover_split: bool
    max_allocation_pct: float


class RegimeComboParams(BaseModel):
    enabled: bool
    vix_sma_lookback: int
    low_vol_strategy: str
    med_vol_strategy: str
    high_vol_reduce_pct: float
    max_allocation_pct: float


class StrategyParamsConfig(BaseModel):
    stat_arb: StatArbParams
    reversal: ReversalParams
    regime_combo: RegimeComboParams


class RedditSource(BaseModel):
    enabled: bool
    subreddits: list[str] = Field(default_factory=list)


class TwitterSource(BaseModel):
    enabled: bool


class NewsSource(BaseModel):
    enabled: bool
    provider: str


class SourcesConfig(BaseModel):
    reddit: RedditSource
    twitter: TwitterSource
    news: NewsSource


class SentimentParamsConfig(BaseModel):
    model: str
    finbert_model_id: str
    openai_model: str
    llama_host: str
    sentiment_threshold_positive: float
    sentiment_threshold_negative: float
    attention_z_threshold: float
    attention_lookback_days: int
    sources: SourcesConfig

    @field_validator("model")
    @classmethod
    def _model(cls, v: str) -> str:
        allowed = {"finbert", "openai", "llama3", "none"}
        if v not in allowed:
            raise ValueError(f"sentiment model must be one of {allowed}, got {v!r}")
        return v


class AppConfig(BaseModel):
    """Aggregates all config files into a single typed object."""
    system: SystemConfig
    risk: RiskConfig
    universe: UniverseConfig
    strategy_params: StrategyParamsConfig
    sentiment_params: SentimentParamsConfig
    # Precomputed hashes for backtest identity requirements (§9.2).
    universe_hash: str = ""
    strategy_params_hash: str = ""


# ── Helpers ───────────────────────────────────────────────────────────────────

_DEFAULT_CONFIG_DIR = Path("config")
_cache: AppConfig | None = None


def _load_yaml(path: Path) -> dict[str, Any]:
    """Read and parse a YAML file; raise ConfigError on any failure."""
    if not path.exists():
        raise ConfigError(f"Required config file not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Failed to parse {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(
            f"Config file {path} must contain a YAML mapping at the top level"
        )
    return data


def _sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file's raw bytes."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_env_vars(raw: str) -> str:
    """
    Substitute ${VAR} placeholders with environment variables.
    Keeps secrets out of committed YAML while keeping the schema structured.
    """
    def replacer(match: re.Match[str]) -> str:
        var = match.group(1)
        val = os.environ.get(var)
        if val is None:
            raise ConfigError(
                f"db_url references ${{{var}}} but that environment variable is not set"
            )
        return val

    return re.sub(r"\$\{([^}]+)\}", replacer, raw)


# ── Public API ────────────────────────────────────────────────────────────────

def load_config(config_dir: Path = _DEFAULT_CONFIG_DIR) -> AppConfig:
    """
    Parse and validate all config/*.yaml files.

    Args:
        config_dir: Directory containing the five required YAML files.

    Returns:
        A fully-validated AppConfig instance.

    Raises:
        ConfigError: On missing files, parse errors, or validation failures.
    """
    system_raw    = _load_yaml(config_dir / "system.yaml")
    risk_raw      = _load_yaml(config_dir / "risk.yaml")
    universe_raw  = _load_yaml(config_dir / "universe.yaml")
    strategy_raw  = _load_yaml(config_dir / "strategy_params.yaml")
    sentiment_raw = _load_yaml(config_dir / "sentiment_params.yaml")

    # Resolve DB URL: inline ${VAR} substitution first, then fall back to
    # the DB_URL env var if the key is absent entirely.
    if "db_url" in system_raw:
        system_raw["db_url"] = _resolve_env_vars(str(system_raw["db_url"]))
    else:
        db_url_env = os.environ.get("DB_URL")
        if not db_url_env:
            raise ConfigError(
                "db_url not found in system.yaml and DB_URL env var is not set"
            )
        system_raw["db_url"] = db_url_env

    try:
        system_cfg    = SystemConfig(**system_raw)
        risk_cfg      = RiskConfig(**risk_raw)
        universe_cfg  = UniverseConfig(**universe_raw)
        strategy_cfg  = StrategyParamsConfig(**strategy_raw)
        sentiment_cfg = SentimentParamsConfig(**sentiment_raw)
    except Exception as exc:
        raise ConfigError(f"Config validation error: {exc}") from exc

    return AppConfig(
        system=system_cfg,
        risk=risk_cfg,
        universe=universe_cfg,
        strategy_params=strategy_cfg,
        sentiment_params=sentiment_cfg,
        universe_hash=_sha256_file(config_dir / "universe.yaml"),
        strategy_params_hash=_sha256_file(config_dir / "strategy_params.yaml"),
    )


def get_config(config_dir: Path = _DEFAULT_CONFIG_DIR) -> AppConfig:
    """
    Return the cached AppConfig, loading it on first call.

    The cache is process-local; each worker loads its own copy at startup.

    Args:
        config_dir: Passed through to load_config() on first call only.

    Returns:
        The cached AppConfig.
    """
    global _cache
    if _cache is None:
        _cache = load_config(config_dir)
    return _cache


def invalidate_cache() -> None:
    """
    Clear the in-process config cache.

    Called by S1 after a CONFIG_CHANGED event so the next get_config()
    call re-reads all YAML files from disk.
    """
    global _cache
    _cache = None
