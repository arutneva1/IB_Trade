import pytest
from datetime import datetime, timedelta, timezone

from ibkr_etf_rebalancer.pricing import Quote, is_stale, FakeQuoteProvider


@pytest.fixture
def fake_quote_provider() -> FakeQuoteProvider:
    now = datetime.now(timezone.utc)
    quotes = {
        "FRESH": Quote(bid=100.0, ask=101.0, ts=now, last=100.5),
        "STALE": Quote(bid=100.0, ask=101.0, ts=now - timedelta(seconds=20), last=100.5),
        "NOBID": Quote(bid=None, ask=101.0, ts=now, last=100.0),
        "NOASK": Quote(bid=100.0, ask=None, ts=now, last=100.0),
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


def test_price_source_last_fallback_midpoint() -> None:
    now = datetime.now(timezone.utc)
    provider = FakeQuoteProvider({"SYM": Quote(100.0, 102.0, now, last=None)})
    price = provider.get_price("SYM", "last")
    assert price == pytest.approx(101.0)


def test_price_source_midpoint_fallback_bidask() -> None:
    now = datetime.now(timezone.utc)
    provider = FakeQuoteProvider({"SYM": Quote(100.0, None, now, last=None)})
    price = provider.get_price("SYM", "midpoint")
    assert price == pytest.approx(100.0)


def test_price_source_bidask_fallback_last() -> None:
    now = datetime.now(timezone.utc)
    provider = FakeQuoteProvider({"SYM": Quote(None, None, now, last=99.5)})
    price = provider.get_price("SYM", "bidask")
    assert price == pytest.approx(99.5)


def test_snapshot_fallback() -> None:
    now = datetime.now(timezone.utc)
    provider = FakeQuoteProvider(
        {"SYM": Quote(None, None, now, last=None)}, snapshots={"SYM": 98.7}
    )
    price = provider.get_price("SYM", "last", fallback_to_snapshot=True)
    assert price == pytest.approx(98.7)


def test_snapshot_disabled_raises() -> None:
    now = datetime.now(timezone.utc)
    provider = FakeQuoteProvider(
        {"SYM": Quote(None, None, now, last=None)}, snapshots={"SYM": 98.7}
    )
    with pytest.raises(ValueError):
        provider.get_price("SYM", "last")
