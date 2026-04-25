"""
s4_backtest_validator/config_schema.py

Pydantic v2 schema for the [backtest] section of strategy_params.yaml.

get_backtest_config() should be called once at the top of main.run()
before any simulation work begins. It validates eagerly and raises
BacktestError immediately so a bad config value is never silently
swallowed by a getattr(..., default) call deep in the pipeline.
"""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field, field_validator, model_validator
from shared.exceptions import BacktestError


class BacktestConfig(BaseModel):
    # Walk-forward window
    is_window_months:    int   = Field(default=12,     ge=3)
    oos_window_months:   int   = Field(default=1,      ge=1)
    # Monte Carlo
    n_mc_paths:          int   = Field(default=1000,   ge=100)
    random_seed:         int   = Field(default=42)
    # Stationary bootstrap
    n_bootstrap_paths:   int   = Field(default=500,    ge=10)
    bootstrap_block_mean:int   = Field(default=10,     ge=2)
    # Permutation battery
    n_permutations:      int   = Field(default=200,    ge=20)
    # Transaction costs
    slippage_rate:       float = Field(default=0.0015, ge=0.0, le=0.05)
    include_costs:       bool  = Field(default=True)

    model_config = {"frozen": True, "extra": "ignore"}

    @field_validator("bootstrap_block_mean")
    @classmethod
    def block_mean_less_than_window(cls, v: int) -> int:
        if v > 63:
            raise ValueError(f"bootstrap_block_mean={v} exceeds 63 trading days")
        return v

    @model_validator(mode="after")
    def oos_shorter_than_is(self) -> "BacktestConfig":
        if self.oos_window_months >= self.is_window_months:
            raise ValueError(
                f"oos_window_months ({self.oos_window_months}) must be "
                f"shorter than is_window_months ({self.is_window_months})."
            )
        return self


def get_backtest_config(cfg: Any) -> BacktestConfig:
    from pydantic import ValidationError

    raw = getattr(cfg, "backtest", None)
    if raw is None:
        return BacktestConfig()

    if isinstance(raw, dict):
        data = raw
    elif hasattr(raw, "__dict__"):
        data = {k: v for k, v in vars(raw).items() if not k.startswith("_")}
    else:
        data = {}

    try:
        return BacktestConfig(**data)
    except ValidationError as exc:
        raise BacktestError(f"Invalid backtest configuration: {exc}") from exc