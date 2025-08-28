"""Application configuration using Pydantic models."""

from __future__ import annotations

from pathlib import Path
from configparser import ConfigParser
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator, model_validator


SymbolOverrides = dict[str, str | int]


class IBKRConfig(BaseModel):
    """Interactive Brokers connection settings."""

    account: str = Field(..., description="IBKR account identifier")
    host: str = Field("localhost", description="TWS/IB Gateway host")
    port: int = Field(7497, description="TWS/IB Gateway port")
    client_id: int = Field(1, description="Client id for the API connection")
    read_only: bool = Field(True, description="Connect in read-only mode without submitting orders")


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
        1.0,
        ge=0,
        le=100,
        description="Hold back this percentage of equity as cash (e.g. 5 for 5%)",
    )
    allow_fractional: bool = Field(
        False, description="Set true only if account supports fractional shares"
    )
    allow_margin: bool = Field(False, description="Permit use of margin when CASH is negative")

    @field_validator("allow_margin", mode="before")
    @classmethod
    def _validate_allow_margin(cls, v: Any) -> bool:
        """Ensure allow_margin receives a boolean value.

        Accept typical string forms ("true"/"false"), integer 0/1 and bools; reject
        anything else so negative numbers like ``-1`` do not silently coerce to
        ``True``.
        """
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)) and v in (0, 1):
            return bool(v)
        if isinstance(v, str):
            val = v.strip().lower()
            if val in {"true", "1", "yes", "on"}:
                return True
            if val in {"false", "0", "no", "off"}:
                return False
        raise ValueError("allow_margin must be a boolean")

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


class PricingConfig(BaseModel):
    """Pricing options controlling preferred price sources."""

    price_source: Literal["last", "midpoint", "bidask"] = Field(
        "last", description="Preferred initial price source"
    )
    fallback_to_snapshot: bool = Field(
        True,
        description="Allow snapshot retrieval when live data is unavailable",
    )


class SafetyConfig(BaseModel):
    """Safety related thresholds and flags from SRS ``[safety]``."""

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
    pricing: PricingConfig = Field(default_factory=PricingConfig)
    safety: SafetyConfig
    io: IOConfig
    symbol_overrides: SymbolOverrides = Field(default_factory=dict)


def load_config(path: Path) -> AppConfig:
    """Load configuration from an INI file.

    Parameters
    ----------
    path:
        Path to the configuration file.

    Returns
    -------
    AppConfig
        The parsed application configuration.
    """

    parser = ConfigParser()
    parser.optionxform = lambda opt: opt  # type: ignore[assignment]
    # preserve case of keys
    with path.open() as handle:
        parser.read_file(handle)

    data: dict[str, Any] = {}
    for section in [
        "ibkr",
        "models",
        "rebalance",
        "fx",
        "pricing",
        "limits",
        "safety",
        "io",
        "symbol_overrides",
    ]:
        if parser.has_section(section):
            items: dict[str, Any] = dict(parser.items(section))
            if section == "models":
                items = {k.upper(): v for k, v in items.items()}
            if section == "ibkr" and "read_only" in items:
                items["read_only"] = parser.getboolean(section, "read_only")
            if section == "pricing" and "fallback_to_snapshot" in items:
                items["fallback_to_snapshot"] = parser.getboolean(section, "fallback_to_snapshot")
            if section == "fx" and "funding_currencies" in items:
                items["funding_currencies"] = [
                    s.strip() for s in items["funding_currencies"].split(",") if s.strip()
                ]
            if section == "symbol_overrides":
                converted: dict[str, Any] = {}
                for k, v in items.items():
                    v_str = v.strip()
                    try:
                        converted[k] = int(v_str)
                    except ValueError:
                        converted[k] = v_str
                items = converted
            data[section] = items

    return AppConfig(**data)


__all__ = [
    "IBKRConfig",
    "ModelsConfig",
    "RebalanceConfig",
    "FXConfig",
    "LimitsConfig",
    "PricingConfig",
    "SafetyConfig",
    "IOConfig",
    "SymbolOverrides",
    "AppConfig",
    "load_config",
]
