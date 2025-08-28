"""Pricing helpers and quote data structures.

The spread-aware limit pricing logic defined in the SRS ``[limits]`` section
relies on these simple quote primitives.  They provide the minimal information
required for the algorithms in :mod:`limit_pricer` and its tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol


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
    last: float | None = None

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

    def get_price(
        self,
        symbol: str,
        price_source: Literal["last", "midpoint", "bidask"],
        fallback_to_snapshot: bool = False,
    ) -> float:  # pragma: no cover - interface
        """Return a price for *symbol* using *price_source* with fallbacks."""


def is_stale(quote: Quote, now: datetime, stale_quote_seconds: int) -> bool:
    """Return ``True`` if *quote* is older than ``stale_quote_seconds``."""

    return (now - quote.ts).total_seconds() > stale_quote_seconds


class FakeQuoteProvider:
    """Deterministic provider used for tests."""

    def __init__(self, quotes: dict[str, Quote], snapshots: dict[str, float] | None = None) -> None:
        self._quotes = quotes
        self._snapshots = snapshots or {}

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

    def get_price(
        self,
        symbol: str,
        price_source: Literal["last", "midpoint", "bidask"],
        fallback_to_snapshot: bool = False,
    ) -> float:
        if symbol not in self._quotes:
            msg = f"No quote available for {symbol}"
            raise KeyError(msg)
        quote = self._quotes[symbol]

        chain = ["last", "midpoint", "bidask"]
        if price_source not in chain:
            raise ValueError("price_source must be 'last', 'midpoint', or 'bidask'")
        idx = chain.index(price_source)
        ordered = chain[idx:] + chain[:idx]

        for src in ordered:
            if src == "last" and quote.last is not None:
                return quote.last
            if src == "midpoint":
                try:
                    return quote.mid()
                except ValueError:
                    pass
            if src == "bidask":
                if quote.bid is not None:
                    return quote.bid
                if quote.ask is not None:
                    return quote.ask

        if fallback_to_snapshot and symbol in self._snapshots:
            return self._snapshots[symbol]

        raise ValueError(f"No price available for {symbol}")
