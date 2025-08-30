"""Scenario helpers for end-to-end testing.

This module defines small data classes to describe market scenarios used in
integration tests. The classes are lightweight containers with minimal
behaviour but provide Pydantic-based validation and convenience helpers such as
configuration overrides and time freezing.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterator

import yaml
from freezegun import freeze_time
from pydantic import BaseModel, Field, ValidationError, model_validator

from .config import AppConfig


@dataclass
class Quote:
    """Bid/ask quote.

    Attributes
    ----------
    bid:
        Best bid price in the instrument's quote currency.
    ask:
        Best ask price in the instrument's quote currency.
    """

    bid: float | None = None
    ask: float | None = None


@dataclass
class Scenario:
    """Represents a market scenario used for tests.

    Attributes
    ----------
    name:
        Descriptive scenario name.
    as_of:
        Scenario timestamp in UTC.
    prices:
        Mapping of symbol to last traded price in quote currency.
    quotes:
        Mapping of symbol to :class:`Quote` objects.
    positions:
        Current holdings expressed as quantity per symbol (shares or contracts).
    cash:
        Cash balances keyed by currency code, denominated in that currency.
    target_weights:
        Final desired portfolio weights by symbol. Values are fractional
        (e.g. ``0.25`` for ``25%``) and should normally sum to ``1.0``.
    portfolios:
        Optional mapping of model name to per-symbol weights used for
        blending via :func:`blend_targets`.
    config_overrides:
        Partial configuration overriding the default test configuration.
    """

    name: str
    as_of: datetime
    prices: Dict[str, float]
    quotes: Dict[str, Quote]
    positions: Dict[str, float]
    cash: Dict[str, float]
    target_weights: Dict[str, float] | None = None
    portfolios: Dict[str, Dict[str, float]] | None = None
    config_overrides: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def app_config(self) -> AppConfig:
        """Return an :class:`AppConfig` with overrides applied."""

        cfg = _default_config()
        if self.config_overrides:
            data = _deep_merge(cfg.model_dump(), self.config_overrides)
            cfg = AppConfig(**data)
        return cfg

    @contextmanager
    def frozen_time(self) -> Iterator[None]:
        """Context manager freezing time to :attr:`as_of`."""

        with freeze_time(self.as_of):
            yield

    def execute(self, fn: Callable[[AppConfig], Any]) -> Any:
        """Run *fn* with time frozen and configuration applied."""

        with self.frozen_time():
            return fn(self.app_config())


# ---------------------------------------------------------------------------
# Pydantic validation models


class _QuoteModel(BaseModel):
    bid: float | None = None
    ask: float | None = None


class _ScenarioModel(BaseModel):
    name: str
    as_of: datetime
    prices: Dict[str, float]
    quotes: Dict[str, _QuoteModel]
    positions: Dict[str, float]
    cash: Dict[str, float]
    target_weights: Dict[str, float] | None = None
    portfolios: Dict[str, Dict[str, float]] | None = None
    config_overrides: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_targets(self) -> "_ScenarioModel":
        if self.target_weights and self.portfolios:
            raise ValueError("specify either target_weights or portfolios, not both")
        return self


# ---------------------------------------------------------------------------
# Public helpers


def load_scenario(path: Path) -> Scenario:
    """Load and validate a scenario definition from *path*.

    Parameters
    ----------
    path:
        Filesystem path pointing at the YAML scenario description.

    Raises
    ------
    ValueError
        If the file cannot be parsed or fails validation.  The original
        exception is attached as the cause.
    """

    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:  # pragma: no cover - yaml errors are rare
        raise ValueError(f"failed to parse scenario file {path}: {exc}") from exc

    try:
        data = _ScenarioModel.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"invalid scenario definition in {path}: {exc}") from exc

    quotes = {k: Quote(**q.model_dump()) for k, q in data.quotes.items()}
    return Scenario(
        name=data.name,
        as_of=data.as_of,
        prices=data.prices,
        quotes=quotes,
        positions=data.positions,
        cash=data.cash,
        target_weights=data.target_weights,
        portfolios=data.portfolios,
        config_overrides=data.config_overrides,
    )


# ---------------------------------------------------------------------------
# Configuration helpers


def _default_config() -> AppConfig:
    """Construct a default test-safe :class:`AppConfig`."""

    base = {
        "ibkr": {"account": "DU123"},
        "models": {"SMURF": 0.5, "BADASS": 0.3, "GLTR": 0.2},
        "rebalance": {},
        "fx": {},
        "limits": {},
        "safety": {},
        "io": {},
    }
    return AppConfig.model_validate(base)


def _deep_merge(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge dictionary *b* into *a* without modifying inputs."""

    result: Dict[str, Any] = dict(a)
    for key, value in b.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


__all__ = ["Quote", "Scenario", "load_scenario"]
