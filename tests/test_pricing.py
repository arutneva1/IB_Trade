import pytest
from datetime import datetime, timedelta, timezone

from ibkr_etf_rebalancer.pricing import Quote, is_stale, FakeQuoteProvider


@pytest.fixture
def fake_quote_provider() -> FakeQuoteProvider:
    now = datetime.now(timezone.utc)
    quotes = {
        "FRESH": Quote(bid=100.0, ask=101.0, ts=now),
        "STALE": Quote(bid=100.0, ask=101.0, ts=now - timedelta(seconds=20)),
        "NOBID": Quote(bid=None, ask=101.0, ts=now),
        "NOASK": Quote(bid=100.0, ask=None, ts=now),
    }
    return FakeQuoteProvider(quotes)


def test_quote_staleness(fake_quote_provider: FakeQuoteProvider) -> None:
    fresh = fake_quote_provider.get_quote("FRESH")
    assert not is_stale(fresh, stale_quote_seconds=10)
    stale = fake_quote_provider.get_quote("STALE")
    assert is_stale(stale, stale_quote_seconds=10)


def test_mid_fallback_for_missing_bid(fake_quote_provider: FakeQuoteProvider) -> None:
    quote = fake_quote_provider.get_quote("NOBID")
    assert quote.mid() == pytest.approx(101.0)


def test_mid_fallback_for_missing_ask(fake_quote_provider: FakeQuoteProvider) -> None:
    quote = fake_quote_provider.get_quote("NOASK")
    assert quote.mid() == pytest.approx(100.0)


def test_mid_raises_when_no_sides() -> None:
    quote = Quote(bid=None, ask=None, ts=datetime.now(timezone.utc))
    with pytest.raises(ValueError):
        quote.mid()
