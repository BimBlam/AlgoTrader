"""
Pydantic v2 schemas for S3-relevant config sections.

These are used to validate that the strategy_params.yaml and
sentiment_params.yaml sections contain all required fields before
the pipeline starts.  get_config() returns already-validated objects,
but we define the schemas here so S3 tests can build minimal configs
without loading the full AppConfig.
"""
from pydantic import BaseModel, Field, field_validator


class StatArbConfig(BaseModel):
    enabled: bool = True
    lookback_days: int = Field(ge=10, le=252)
    min_kappa: float = Field(ge=0.0)
    entry_s_score: float = Field(ge=0.0)
    exit_s_score_long: float
    exit_s_score_short: float = Field(ge=0.0)
    max_allocation_pct: float = Field(ge=0.0, le=1.0)


class ReversalConfig(BaseModel):
    enabled: bool = True
    lookback_days: int = Field(ge=1)
    long_decile: float = Field(ge=0.0, le=0.5)
    short_decile: float = Field(ge=0.5, le=1.0)
    turnover_split: bool = True
    max_allocation_pct: float = Field(ge=0.0, le=1.0)

    @field_validator("short_decile")
    @classmethod
    def short_above_long(cls, v, info):
        long_decile = info.data.get("long_decile", 0.0)
        if v <= long_decile:
            raise ValueError("short_decile must be > long_decile")
        return v


class RegimeComboConfig(BaseModel):
    enabled: bool = True
    vix_sma_lookback: int = Field(ge=5)
    low_vol_strategy: str
    med_vol_strategy: str
    high_vol_reduce_pct: float = Field(ge=0.0, le=1.0)
    extreme_vol_halt: bool = True
    max_allocation_pct: float = Field(ge=0.0, le=1.0)


class StrategyParamsConfig(BaseModel):
    stat_arb: StatArbConfig
    reversal: ReversalConfig
    regime_combo: RegimeComboConfig


class SentimentParamsConfig(BaseModel):
    model: str
    sentiment_threshold_positive: float = Field(ge=0.0, le=1.0)
    sentiment_threshold_negative: float = Field(le=0.0, ge=-1.0)
    attention_z_threshold: float = Field(ge=0.0)
    attention_lookback_days: int = Field(ge=1)
