import pytest
from datetime import datetime, timedelta, timezone
from typing import cast

from ibkr_etf_rebalancer.pricing import IBKRQuoteProvider, Quote
from ibkr_etf_rebalancer.ibkr_provider import Contract, FakeIB, IBKRProvider


@pytest.fixture
def ibkr_quote_provider() -> IBKRQuoteProvider:
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


def test_price_fallback_chain() -> None:
    now = datetime.now(timezone.utc)
    contracts = {"SYM": Contract(symbol="SYM")}
    quotes = {"SYM": Quote(bid=100.0, ask=None, ts=now, last=None)}
    ib = FakeIB(contracts=contracts, quotes=quotes)
    provider = IBKRQuoteProvider(cast(IBKRProvider, ib))
    price = provider.get_price("SYM", "last")
    assert price == pytest.approx(100.0)


def test_stale_quote_uses_snapshot() -> None:
    now = datetime.now(timezone.utc) - timedelta(seconds=20)
    contracts = {"SYM": Contract(symbol="SYM")}
    quotes = {"SYM": Quote(bid=None, ask=None, ts=now, last=99.5)}
    ib = FakeIB(contracts=contracts, quotes=quotes)
    provider = IBKRQuoteProvider(
        cast(IBKRProvider, ib), stale_quote_seconds=10, snapshots={"SYM": 98.7}
    )
    price = provider.get_price("SYM", "last", fallback_to_snapshot=True)
    assert price == pytest.approx(98.7)
    with pytest.raises(ValueError):
        provider.get_price("SYM", "last")
