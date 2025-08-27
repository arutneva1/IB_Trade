"""Application configuration using Pydantic models."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator


class IBKRConfig(BaseModel):
    """Interactive Brokers connection settings."""

    account: str = Field(..., description="IBKR account identifier")
    host: str = Field("localhost", description="TWS/IB Gateway host")
    port: int = Field(7497, description="TWS/IB Gateway port")
    client_id: int = Field(1, description="Client id for the API connection")


class ModelsConfig(BaseModel):
    """Weights for allocation models."""

    SMURF: float = Field(..., ge=0, le=1)
    BADASS: float = Field(..., ge=0, le=1)
    GLTR: float = Field(..., ge=0, le=1)

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> "ModelsConfig":
        total = self.SMURF + self.BADASS + self.GLTR
        if abs(total - 1.0) > 0.001:
            raise ValueError("Model weights must sum to 1.0 ±0.001")
        return self


class RebalanceConfig(BaseModel):
    """Rebalancing behaviour flags."""

    allow_fractional: bool = Field(True, description="Allow fractional share orders")
    allow_margin: bool = Field(False, description="Permit use of margin for trades")


class FXConfig(BaseModel):
    """Foreign exchange settings."""

    base_currency: str = Field("USD", description="Base currency for the account")
    max_spread: float = Field(0.005, ge=0, description="Maximum acceptable FX spread")


class LimitsConfig(BaseModel):
    """Trading limits."""

    allow_margin: bool = Field(False, description="Permit margin trading")
    allow_fractional: bool = Field(True, description="Allow fractional shares")
    max_leverage: float = Field(1.0, description="Maximum portfolio leverage")

    @field_validator("max_leverage")
    def positive_leverage(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("max_leverage must be positive")
        return v


class SafetyConfig(BaseModel):
    """Safety related thresholds."""

    max_drawdown: float = Field(0.25, gt=0, le=1, description="Max allowable drawdown")


class IOConfig(BaseModel):
    """Input/output paths and options."""

    output_dir: str = Field("./out", description="Directory for generated reports")
    log_level: str = Field("INFO", description="Logging verbosity")


class AppConfig(BaseModel):
    """Top level application configuration."""

    ibkr: IBKRConfig
    models: ModelsConfig
    rebalance: RebalanceConfig
    fx: FXConfig
    limits: LimitsConfig
    safety: SafetyConfig
    io: IOConfig


__all__ = [
    "IBKRConfig",
    "ModelsConfig",
    "RebalanceConfig",
    "FXConfig",
    "LimitsConfig",
    "SafetyConfig",
    "IOConfig",
    "AppConfig",
]
