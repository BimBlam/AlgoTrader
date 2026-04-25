"""
s4_backtest_validator/config_schema.py

Pydantic v2 schema for the [backtest] section of strategy_params.yaml.
Validated at process start via get_config(); all defaults match spec contract.
"""

from __future__ import annotations
from pydantic import BaseModel, Field, model_validator


class BacktestConfig(BaseModel):
    """
    Configuration block read from config/strategy_params.yaml under the
    `backtest:` key.  All fields have conservative defaults; no value is
    hardcoded in business logic — callers always read from this object.
    """

    is_window_months: int = Field(
        default=12,
        ge=3,
        description="In-sample window length in calendar months.",
    )
    n_mc_paths: int = Field(
        default=1000,
        ge=100,
        description="Number of GARCH Monte Carlo paths to generate.",
    )
    n_bootstrap_paths: int = Field(
        default=500,
        ge=50,
        description="Number of stationary bootstrap replications.",
    )
    bootstrap_block_mean: int = Field(
        default=10,
        ge=2,
        description="Average block length (days) for stationary bootstrap.",
    )
    n_permutations: int = Field(
        default=200,
        ge=50,
        description="Number of permutations per test in the battery.",
    )
    slippage_rate: float = Field(
        default=0.0015,
        ge=0.0,
        le=0.05,
        description="One-way slippage as a fraction of trade value (0.15% default).",
    )
    include_costs: bool = Field(
        default=True,
        description="Whether to apply transaction costs in simulations.",
    )
    random_seed: int = Field(
        default=42,
        description="Base seed for all RNG operations; ensures reproducibility.",
    )

    @model_validator(mode="after")
    def validate_windows(self) -> "BacktestConfig":
        if self.is_window_months < 3:
            raise ValueError("is_window_months must be at least 3.")
        return self