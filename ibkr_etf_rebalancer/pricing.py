"""Pricing helpers and quote data structures.

The spread-aware limit pricing logic defined in the SRS ``[limits]`` section
relies on these simple quote primitives.  They provide the minimal information
required for the algorithms in :mod:`limit_pricer` and its tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal, Mapping, Protocol


__all__ = [
    "Quote",
    "is_stale",
    "QuoteProvider",
    "FakeQuoteProvider",
    "IBKRQuoteProvider",
    "Pricing",
]

if TYPE_CHECKING:  # pragma: no cover - used for type hints only
    from .ibkr_provider import Contract, IBKRProvider


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
        if quote.bid is None and quote.ask is None:
            raise ValueError(f"Quote for {symbol} missing bid and ask")
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


class IBKRQuoteProvider:
    """Quote provider backed by an :class:`IBKRProvider` instance.

    The provider fetches quotes through an ``IBKRProvider`` implementation,
    handling contract resolution for both equity symbols and foreign exchange
    pairs (e.g. ``"USD.CAD"``).  It mirrors the behaviour of
    :class:`FakeQuoteProvider` but sources its data from the Interactive Brokers
    adapter.
    """

    def __init__(
        self,
        ibkr: "IBKRProvider",
        *,
        stale_quote_seconds: int = 10,
        snapshots: Mapping[str, float] | None = None,
    ) -> None:
        self._ib = ibkr
        self._stale = stale_quote_seconds
        self._snapshots = dict(snapshots or {})

    # ------------------------------------------------------------------
    def _resolve(self, symbol: str) -> "Contract":
        """Return a resolved contract for *symbol*.

        Equity symbols resolve as ``STK`` contracts.  Symbols containing a dot
        are treated as FX pairs in ``BASE.QUOTE`` form and resolved as ``CASH``
        contracts routed through ``IDEALPRO``.
        """

        from .ibkr_provider import Contract, ResolutionError

        if "." in symbol:
            base, quote = symbol.split(".", 1)
            contract = Contract(
                symbol=base,
                sec_type="CASH",
                currency=quote,
                exchange="IDEALPRO",
            )
            try:
                return self._ib.resolve_contract(contract)
            except ResolutionError:
                contract = Contract(
                    symbol=symbol,
                    sec_type="CASH",
                    currency=quote,
                    exchange="IDEALPRO",
                )
                return self._ib.resolve_contract(contract)

        contract = Contract(symbol=symbol, sec_type="STK")
        return self._ib.resolve_contract(contract)

    # ------------------------------------------------------------------
    def get_quote(self, symbol: str) -> Quote:
        """Return a :class:`Quote` for *symbol*.

        The symbol is resolved to a contract via the underlying ``IBKRProvider``
        before retrieving the latest quote.
        """

        from .ibkr_provider import Quote as IBQuote

        contract = self._resolve(symbol)
        ib_quote: IBQuote | Quote = self._ib.get_quote(contract)
        if isinstance(ib_quote, Quote):
            return ib_quote
        ts = ib_quote.timestamp or datetime.now(timezone.utc)
        return Quote(ib_quote.bid, ib_quote.ask, ts, last=ib_quote.last)

    # ------------------------------------------------------------------
    def get_price(
        self,
        symbol: str,
        price_source: Literal["last", "midpoint", "bidask"],
        fallback_to_snapshot: bool = False,
    ) -> float:
        """Return a price for *symbol* using *price_source* with fallbacks.

        Prices are rejected if the underlying quote is older than
        ``stale_quote_seconds``.  In such cases, or when the desired price source
        is unavailable, the method falls back through ``last``, ``midpoint`` and
        ``bidask`` before optionally returning a snapshot price.
        """

        quote = self.get_quote(symbol)
        now = datetime.now(timezone.utc)

        chain = ["last", "midpoint", "bidask"]
        if price_source not in chain:
            raise ValueError("price_source must be 'last', 'midpoint', or 'bidask'")
        idx = chain.index(price_source)
        ordered = chain[idx:] + chain[:idx]

        if not is_stale(quote, now, self._stale):
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


class Pricing:
    """Facade that selects an appropriate quote provider.

    When an :class:`IBKRProvider` instance is supplied, quotes are sourced
    through :class:`IBKRQuoteProvider`.  Otherwise a
    :class:`FakeQuoteProvider` backed by the supplied *quotes* mapping is
    used.  The chosen provider is exposed via the :attr:`quote_provider`
    attribute.
    """

    def __init__(
        self,
        ibkr: "IBKRProvider" | None,
        quotes: Mapping[str, Quote] | None = None,
        *,
        stale_quote_seconds: int = 10,
        snapshots: Mapping[str, float] | None = None,
    ) -> None:
        if ibkr is not None:
            self.quote_provider: QuoteProvider = IBKRQuoteProvider(
                ibkr,
                stale_quote_seconds=stale_quote_seconds,
                snapshots=snapshots,
            )
        else:
            self.quote_provider = FakeQuoteProvider(dict(quotes or {}), dict(snapshots or {}))
