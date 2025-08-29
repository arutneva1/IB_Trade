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
from ibkr_etf_rebalancer.ibkr_provider import Contract, FakeIB, IBKRProvider


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
