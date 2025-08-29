"""Scenario loading and execution helpers for end-to-end tests."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterator

import yaml
from freezegun import freeze_time
from pydantic import BaseModel, Field

from ibkr_etf_rebalancer.config import AppConfig


@dataclass
class Quote:
    """Simple bid/ask quote container."""

    bid: float
    ask: float


@dataclass
class Scenario:
    """Represents a test scenario used for E2E tests.

    Attributes
    ----------
    name:
        Descriptive scenario name.
    as_of:
        Timestamp for the scenario. Time is frozen to this value when executed.
    prices:
        Mapping of symbol to last traded price.
    quotes:
        Mapping of symbol to :class:`Quote` objects.
    positions:
        Current holdings expressed as quantity per symbol.
    cash:
        Cash balances keyed by currency code.
    config_overrides:
        Partial configuration overriding the default test configuration.
    """

    name: str
    as_of: datetime
    prices: Dict[str, float]
    quotes: Dict[str, Quote]
    positions: Dict[str, float]
    cash: Dict[str, float]
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


class _QuoteModel(BaseModel):
    bid: float
    ask: float


class _ScenarioModel(BaseModel):
    name: str
    as_of: datetime
    prices: Dict[str, float]
    quotes: Dict[str, _QuoteModel]
    positions: Dict[str, float]
    cash: Dict[str, float]
    config_overrides: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


def load_scenario(path: Path) -> Scenario:
    """Load and validate a scenario definition from *path*."""

    raw = yaml.safe_load(path.read_text())
    data = _ScenarioModel.model_validate(raw)
    quotes = {k: Quote(**q.model_dump()) for k, q in data.quotes.items()}
    return Scenario(
        name=data.name,
        as_of=data.as_of,
        prices=data.prices,
        quotes=quotes,
        positions=data.positions,
        cash=data.cash,
        config_overrides=data.config_overrides,
    )


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
