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
    now = datetime.now(timezone.utc)
    assert not is_stale(fresh, now, stale_quote_seconds=10)
    stale = fake_quote_provider.get_quote("STALE")
    assert is_stale(stale, now, stale_quote_seconds=10)


def test_fake_quote_provider_missing_bid(fake_quote_provider: FakeQuoteProvider) -> None:
    with pytest.raises(ValueError, match="missing bid"):
        fake_quote_provider.get_quote("NOBID")


def test_fake_quote_provider_missing_ask(fake_quote_provider: FakeQuoteProvider) -> None:
    with pytest.raises(ValueError, match="missing ask"):
        fake_quote_provider.get_quote("NOASK")


def test_mid_raises_when_no_sides() -> None:
    quote = Quote(bid=None, ask=None, ts=datetime.now(timezone.utc))
    with pytest.raises(ValueError):
        quote.mid()


def test_mid_raises_when_missing_bid_only() -> None:
    quote = Quote(bid=None, ask=100.0, ts=datetime.now(timezone.utc))
    with pytest.raises(ValueError, match="missing bid"):
        quote.mid()


def test_mid_raises_when_missing_ask_only() -> None:
    quote = Quote(bid=100.0, ask=None, ts=datetime.now(timezone.utc))
    with pytest.raises(ValueError, match="missing ask"):
        quote.mid()


def test_fake_quote_provider_missing_symbol(fake_quote_provider: FakeQuoteProvider) -> None:
    with pytest.raises(KeyError):
        fake_quote_provider.get_quote("UNKNOWN")


def test_mid_calculation() -> None:
    quote = Quote(bid=100.0, ask=102.0, ts=datetime.now(timezone.utc))
    assert quote.mid() == pytest.approx(101.0)
