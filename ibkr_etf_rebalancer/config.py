"""Application configuration using Pydantic models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


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
    """Rebalancing behaviour and limits.

    Values mirror the SRS ``[rebalance]`` section.  Tolerance bands are
    expressed in basis points (1/100th of a percent).
    """

    trigger_mode: Literal["per_holding", "total_drift"] = Field(
        "per_holding",
        description="How to decide when to trade: per holding or total portfolio drift",
    )
    per_holding_band_bps: int = Field(
        50, ge=0, description="Trade a holding when its drift exceeds this many bps"
    )
    portfolio_total_band_bps: int = Field(
        100, ge=0, description="Total drift trigger when trigger_mode='total_drift'"
    )
    min_order_usd: float = Field(
        500, gt=0, description="Ignore trades smaller than this notional value"
    )
    cash_buffer_pct: float = Field(
        1.0, ge=0, le=100, description="Hold back this percent of equity as cash"
    )
    allow_fractional: bool = Field(
        False, description="Set true only if account supports fractional shares"
    )
    allow_margin: bool = Field(False, description="Permit use of margin when CASH is negative")
    max_leverage: float = Field(
        1.5,
        gt=0,
        description="Hard cap on gross exposure as multiple of equity (e.g. 1.5 = 150%)",
    )
    maintenance_buffer_pct: float = Field(
        10, ge=0, le=100, description="Headroom against margin calls in percent"
    )
    prefer_rth: bool = Field(True, description="Place orders only during regular trading hours")
    order_type: Literal["LMT", "MKT"] = Field(
        "LMT", description="Default order type for rebalancing trades"
    )


class FXConfig(BaseModel):
    """Foreign exchange settings following SRS ``[fx]`` rules."""

    enabled: bool = Field(False, description="Enable FX funding of USD trades")
    base_currency: str = Field("USD", description="Portfolio/target currency")
    funding_currencies: list[str] = Field(
        default_factory=lambda: ["CAD"],
        description="Currencies available to convert from",
    )
    convert_mode: Literal["just_in_time", "always_top_up"] = Field(
        "just_in_time", description="When to convert FX to fund buys"
    )
    use_mid_for_planning: bool = Field(True, description="Size FX conversions using the mid price")
    min_fx_order_usd: float = Field(1000, gt=0, description="Skip conversions smaller than this")
    fx_buffer_bps: int = Field(20, ge=0, description="Buy a small extra cushion when converting")
    order_type: Literal["MKT", "LMT"] = Field(
        "MKT", description="Order type used for FX conversions"
    )
    limit_slippage_bps: int = Field(5, ge=0, description="Slippage when order_type='LMT'")
    route: str = Field("IDEALPRO", description="IBKR FX venue")
    wait_for_fill_seconds: int = Field(
        5, ge=0, description="Pause before placing dependent ETF orders"
    )
    prefer_market_hours: bool = Field(False, description="Allow off-hours FX trading by default")


class LimitsConfig(BaseModel):
    """Spread‑aware limit pricing settings from SRS ``[limits]``."""

    smart_limit: bool = Field(True, description="Enable dynamic spread-aware limit prices")
    style: Literal["spread_aware", "static_bps", "off"] = Field(
        "spread_aware", description="Pricing style"
    )
    buy_offset_frac: float = Field(0.25, ge=0, le=1, description="BUY at mid + frac*spread")
    sell_offset_frac: float = Field(0.25, ge=0, le=1, description="SELL at mid - frac*spread")
    max_offset_bps: int = Field(10, ge=0, description="Cap distance from mid in bps")
    wide_spread_bps: int = Field(50, ge=0, description="Treat spreads wider than this as wide")
    escalate_action: Literal["cross", "market", "keep"] = Field(
        "cross", description="Action when spread is wide or quotes stale"
    )
    stale_quote_seconds: int = Field(10, ge=0, description="Quote age before considered stale")
    use_ask_bid_cap: bool = Field(True, description="Never bid above ask or offer below bid")


class SafetyConfig(BaseModel):
    """Safety related thresholds and flags from SRS ``[safety]``."""

    max_drawdown: float = Field(0.25, gt=0, le=1, description="Max allowable drawdown")
    paper_only: bool = Field(
        True, description="Hard gate: only run in paper mode unless overridden"
    )
    require_confirm: bool = Field(
        True, description="Prompt for confirmation before sending live orders"
    )
    kill_switch_file: str = Field(
        "KILL_SWITCH",
        description="If this file exists the program aborts immediately",
    )


class IOConfig(BaseModel):
    """Input/output paths and options."""

    report_dir: str = Field("reports", description="Directory for generated reports")
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
