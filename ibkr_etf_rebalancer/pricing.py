"""Pricing helpers and quote data structures."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol


@dataclass
class Quote:
    """Simple market quote.

    Attributes
    ----------
    bid:
        Best bid price or ``None`` if unavailable.
    ask:
        Best ask price or ``None`` if unavailable.
    ts:
        Timestamp when the quote was observed.
    """

    bid: float | None
    ask: float | None
    ts: datetime

    def mid(self) -> float:
        """Return the mid price with fallbacks.

        If both bid and ask are available the arithmetic mid is returned.  If
        one side is missing the other side is used as a conservative mid.
        ``ValueError`` is raised when both sides are missing.
        """

        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / 2
        if self.bid is not None:
            return self.bid
        if self.ask is not None:
            return self.ask
        raise ValueError("Quote missing bid and ask")


class QuoteProvider(Protocol):
    """Abstract quote provider interface."""

    def get_quote(self, symbol: str) -> Quote:  # pragma: no cover - interface
        """Return a :class:`Quote` for *symbol*."""


def is_stale(quote: Quote, stale_quote_seconds: int, *, now: datetime | None = None) -> bool:
    """Return ``True`` if *quote* is older than ``stale_quote_seconds``."""

    current = now or datetime.now(timezone.utc)
    return (current - quote.ts).total_seconds() > stale_quote_seconds


class FakeQuoteProvider:
    """Deterministic provider used for tests."""

    def __init__(self, quotes: dict[str, Quote]) -> None:
        self._quotes = quotes

    def get_quote(self, symbol: str) -> Quote:
        if symbol not in self._quotes:
            msg = f"No quote available for {symbol}"
            raise KeyError(msg)
        return self._quotes[symbol]
