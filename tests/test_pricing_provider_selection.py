from typing import cast

from ibkr_etf_rebalancer.ibkr_provider import FakeIB, IBKRProvider
from ibkr_etf_rebalancer.pricing import (
    FakeQuoteProvider,
    IBKRQuoteProvider,
    Pricing,
)


def test_pricing_uses_fake_provider_when_no_broker() -> None:
    pricing = Pricing(None)
    assert isinstance(pricing.quote_provider, FakeQuoteProvider)


def test_pricing_uses_ibkr_provider_when_broker_supplied() -> None:
    ib = cast(IBKRProvider, FakeIB())
    pricing = Pricing(ib)
    assert isinstance(pricing.quote_provider, IBKRQuoteProvider)
