"""Pricing helpers and quote data structures.

The spread-aware limit pricing logic defined in the SRS ``[limits]`` section
relies on these simple quote primitives.  They provide the minimal information
required for the algorithms in :mod:`limit_pricer` and its tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


__all__ = [
    "Quote",
    "is_stale",
    "QuoteProvider",
    "FakeQuoteProvider",
]


@dataclass
class Quote:
    """Simple market quote."""

    bid: float | None
    ask: float | None
    ts: datetime

    def mid(self) -> float:
        """Return the arithmetic mid price."""

        if self.bid is None and self.ask is None:
            raise ValueError("Quote missing bid and ask")
        if self.bid is None:
            raise ValueError("Quote missing bid")
        if self.ask is None:
            raise ValueError("Quote missing ask")
        return (self.bid + self.ask) / 2


class QuoteProvider(Protocol):
    """Abstract quote provider interface."""

    def get_quote(self, symbol: str) -> Quote:  # pragma: no cover - interface
        """Return a :class:`Quote` for *symbol*."""


def is_stale(quote: Quote, now: datetime, stale_quote_seconds: int) -> bool:
    """Return ``True`` if *quote* is older than ``stale_quote_seconds``."""

    return (now - quote.ts).total_seconds() > stale_quote_seconds


class FakeQuoteProvider:
    """Deterministic provider used for tests."""

    def __init__(self, quotes: dict[str, Quote]) -> None:
        self._quotes = quotes

    def get_quote(self, symbol: str) -> Quote:
        if symbol not in self._quotes:
            msg = f"No quote available for {symbol}"
            raise KeyError(msg)
        quote = self._quotes[symbol]
        if quote.bid is None:
            raise ValueError(f"Quote for {symbol} missing bid")
        if quote.ask is None:
            raise ValueError(f"Quote for {symbol} missing ask")
        return quote
