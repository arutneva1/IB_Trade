import pytest
from datetime import datetime, timedelta, timezone
from typing import cast

from ibkr_etf_rebalancer.pricing import (
    FakeQuoteProvider,
    IBKRQuoteProvider,
    Quote,
    QuoteProvider,
    is_stale,
)
from ibkr_etf_rebalancer.ibkr_provider import Contract, FakeIB, IBKRProvider, Quote as IBQuote


@pytest.fixture
def ibkr_quote_provider() -> IBKRQuoteProvider:
    """IBKRQuoteProvider seeded with equity and FX quotes."""

    now = datetime.now(timezone.utc)
    contracts = {
        "AAA": Contract(symbol="AAA"),
        "USD": Contract(symbol="USD", sec_type="CASH", currency="CAD", exchange="IDEALPRO"),
    }
    quotes = {
        "AAA": Quote(bid=100.0, ask=101.0, ts=now, last=100.5),
        "USD": Quote(bid=1.25, ask=1.26, ts=now, last=1.255),
    }
    ib = FakeIB(contracts=contracts, quotes=quotes)
    return IBKRQuoteProvider(cast(IBKRProvider, ib))


def test_get_quote_equity(ibkr_quote_provider: IBKRQuoteProvider) -> None:
    quote = ibkr_quote_provider.get_quote("AAA")
    assert quote.bid == pytest.approx(100.0)
    assert quote.ask == pytest.approx(101.0)


def test_get_quote_fx_pair(ibkr_quote_provider: IBKRQuoteProvider) -> None:
    quote = ibkr_quote_provider.get_quote("USD.CAD")
    assert quote.mid() == pytest.approx((1.25 + 1.26) / 2)


def test_get_price_follows_chain() -> None:
    now = datetime.now(timezone.utc)
    contracts = {"SYM": Contract(symbol="SYM")}
    quotes = {"SYM": Quote(bid=100.0, ask=102.0, ts=now, last=None)}
    ib = FakeIB(contracts=contracts, quotes=quotes)
    provider = IBKRQuoteProvider(cast(IBKRProvider, ib))
    price = provider.get_price("SYM", "last")
    # last -> midpoint -> bidask chain should return midpoint
    assert price == pytest.approx(101.0)


def test_snapshot_fallback_when_price_missing() -> None:
    now = datetime.now(timezone.utc)
    contracts = {"SYM": Contract(symbol="SYM")}
    quotes = {"SYM": Quote(bid=None, ask=None, ts=now, last=None)}
    ib = FakeIB(contracts=contracts, quotes=quotes)
    provider = IBKRQuoteProvider(cast(IBKRProvider, ib), snapshots={"SYM": 98.7})
    price = provider.get_price("SYM", "last", fallback_to_snapshot=True)
    assert price == pytest.approx(98.7)
    with pytest.raises(ValueError):
        provider.get_price("SYM", "last")


def test_stale_quote_uses_snapshot() -> None:
    now = datetime.now(timezone.utc) - timedelta(seconds=20)
    contracts = {"SYM": Contract(symbol="SYM")}
    quotes = {"SYM": Quote(bid=100.0, ask=101.0, ts=now, last=100.5)}
    ib = FakeIB(contracts=contracts, quotes=quotes)
    provider = IBKRQuoteProvider(
        cast(IBKRProvider, ib), stale_quote_seconds=10, snapshots={"SYM": 98.7}
    )
    quote = provider.get_quote("SYM")
    assert is_stale(quote, datetime.now(timezone.utc), 10)
    price = provider.get_price("SYM", "last", fallback_to_snapshot=True)
    assert price == pytest.approx(98.7)
    with pytest.raises(ValueError):
        provider.get_price("SYM", "last")


def test_quote_provider_swap() -> None:
    now = datetime.now(timezone.utc)
    contracts = {
        "AAA": Contract(symbol="AAA"),
        "USD": Contract(symbol="USD", sec_type="CASH", currency="CAD", exchange="IDEALPRO"),
    }
    ib_quotes = {
        "AAA": Quote(bid=100.0, ask=101.0, ts=now, last=100.5),
        "USD": Quote(bid=1.25, ask=1.26, ts=now, last=1.255),
    }
    fake_quotes = {
        "AAA": Quote(bid=100.0, ask=101.0, ts=now, last=100.5),
        "USD.CAD": Quote(bid=1.25, ask=1.26, ts=now, last=1.255),
    }
    ib_provider = IBKRQuoteProvider(
        cast(IBKRProvider, FakeIB(contracts=contracts, quotes=ib_quotes))
    )
    fake_provider = FakeQuoteProvider(fake_quotes)

    def check(provider: QuoteProvider) -> None:
        assert provider.get_price("AAA", "last") == pytest.approx(100.5)
        assert provider.get_price("USD.CAD", "midpoint") == pytest.approx((1.25 + 1.26) / 2)

    check(fake_provider)
    check(ib_provider)


def test_fx_resolve_fallback() -> None:
    now = datetime.now(timezone.utc)
    # Only provide a contract for the full FX pair so the base symbol fails
    contracts = {
        "USD.CAD": Contract(symbol="USD.CAD", sec_type="CASH", currency="CAD", exchange="IDEALPRO")
    }
    quotes = {"USD.CAD": Quote(bid=1.25, ask=1.26, ts=now, last=1.255)}
    ib = FakeIB(contracts=contracts, quotes=quotes)
    provider = IBKRQuoteProvider(cast(IBKRProvider, ib))
    quote = provider.get_quote("USD.CAD")
    assert quote.bid == pytest.approx(1.25)


class IBQuoteFakeIB(FakeIB):
    def get_quote(self, contract: Contract) -> IBQuote:
        resolved = self.resolve_contract(contract)
        q = self._quotes[resolved.symbol]
        return IBQuote(contract=resolved, bid=q.bid, ask=q.ask, last=q.last, timestamp=q.ts)


def test_get_quote_converts_ib_quote() -> None:
    now = datetime.now(timezone.utc)
    contracts = {"AAA": Contract(symbol="AAA")}
    quotes = {"AAA": Quote(bid=100.0, ask=101.0, ts=now, last=100.5)}
    ib = IBQuoteFakeIB(contracts=contracts, quotes=quotes)
    provider = IBKRQuoteProvider(cast(IBKRProvider, ib))
    quote = provider.get_quote("AAA")
    assert isinstance(quote, Quote)
    assert quote.last == pytest.approx(100.5)


def test_ibkr_provider_invalid_price_source(ibkr_quote_provider: IBKRQuoteProvider) -> None:
    with pytest.raises(ValueError, match="price_source must be 'last', 'midpoint', or 'bidask'"):
        ibkr_quote_provider.get_price("AAA", "invalid")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "quote_kwargs, expected",
    [
        ({"bid": 100.0, "ask": None, "last": None}, 100.0),
        ({"bid": None, "ask": 101.0, "last": None}, 101.0),
    ],
)
def test_ibkr_provider_bidask_returns_available_side(
    quote_kwargs: dict[str, float | None], expected: float
) -> None:
    now = datetime.now(timezone.utc)
    contracts = {"SYM": Contract(symbol="SYM")}
    quotes = {"SYM": Quote(ts=now, **quote_kwargs)}
    ib = FakeIB(contracts=contracts, quotes=quotes)
    provider = IBKRQuoteProvider(cast(IBKRProvider, ib))
    price = provider.get_price("SYM", "bidask")
    assert price == pytest.approx(expected)
