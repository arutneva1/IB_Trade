"""Limit price calculation helpers.

This module implements the spread aware limit price algorithm described in the
``[limits]`` section of the SRS.  Given the current quote for a symbol it
computes a conservative limit price constrained by the NBBO, a maximum offset
from the mid price and optional escalation rules for wide or stale markets.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from .config import LimitsConfig
from .pricing import Quote, QuoteProvider, is_stale

__all__ = ["price_limit_buy", "price_limit_sell", "calc_limit_price"]


def _round_to_tick(price: float, tick: float) -> float:
    """Round ``price`` to the nearest multiple of ``tick``.

    IBKR contracts define a minimum tick size; if ``tick`` is non‑positive the
    function falls back to a $0.01 increment.
    """

    if tick <= 0:
        tick = 0.01
    return round(price / tick) * tick


def price_limit_buy(
    quote: Quote, min_tick: float, cfg: LimitsConfig, now: datetime
) -> tuple[float, Literal["LMT", "MKT"]]:
    """Return a conservative BUY price and order type.

    The algorithm applies an offset from the mid price, caps the result by
    ``max_offset_bps`` and optionally the current ask, then rounds to the
    contract's minimum tick.  Wide or stale markets may escalate according to
    ``escalate_action``.
    """

    bid, ask = quote.bid, quote.ask
    if bid is None or ask is None:
        raise ValueError("Quote missing bid/ask")
    spread = ask - bid
    if spread <= 0:
        raise ValueError("Quote ask must be greater than bid")

    mid = (bid + ask) / 2
    spread_bps = spread / (bid + ask) * 10000

    price = mid + cfg.buy_offset_frac * spread
    cap = mid * (1 + cfg.max_offset_bps / 10000)
    price = min(price, cap)
    price = _round_to_tick(price, min_tick)
    if cfg.use_ask_bid_cap:
        price = min(price, ask)

    wide_or_stale = spread_bps > cfg.wide_spread_bps or is_stale(
        quote, now, cfg.stale_quote_seconds
    )
    if wide_or_stale:
        action = cfg.escalate_action
        if action == "cross":
            return ask, "LMT"
        if action == "market":
            return 0.0, "MKT"
        # action == "keep" simply keeps the capped price

    return price, "LMT"


def price_limit_sell(
    quote: Quote, min_tick: float, cfg: LimitsConfig, now: datetime
) -> tuple[float, Literal["LMT", "MKT"]]:
    """Return a conservative SELL price and order type.

    Behaviour mirrors :func:`price_limit_buy` but for the SELL side.
    """

    bid, ask = quote.bid, quote.ask
    if bid is None or ask is None:
        raise ValueError("Quote missing bid/ask")
    spread = ask - bid
    if spread <= 0:
        raise ValueError("Quote ask must be greater than bid")

    mid = (bid + ask) / 2
    spread_bps = spread / (bid + ask) * 10000

    price = mid - cfg.sell_offset_frac * spread
    cap = mid * (1 - cfg.max_offset_bps / 10000)
    price = max(price, cap)
    price = _round_to_tick(price, min_tick)
    if cfg.use_ask_bid_cap:
        price = max(price, bid)

    wide_or_stale = spread_bps > cfg.wide_spread_bps or is_stale(
        quote, now, cfg.stale_quote_seconds
    )
    if wide_or_stale:
        action = cfg.escalate_action
        if action == "cross":
            return bid, "LMT"
        if action == "market":
            return 0.0, "MKT"

    return price, "LMT"


def calc_limit_price(
    side: Literal["BUY", "SELL"],
    symbol: str,
    tick: float,
    provider: QuoteProvider,
    now: datetime,
    cfg: LimitsConfig,
) -> tuple[float | None, Literal["LMT", "MKT"]]:
    """Return a limit price and order type for *side* on *symbol*.

    This wrapper exists for backward compatibility and delegates to the pure
    ``price_limit_buy`` or ``price_limit_sell`` functions.  ``price`` is
    ``None`` when a market order is returned.
    """

    quote = provider.get_quote(symbol)
    side_u = side.upper()
    if side_u == "BUY":
        price, order_type = price_limit_buy(quote, tick, cfg, now)
    else:
        price, order_type = price_limit_sell(quote, tick, cfg, now)

    return (price if order_type == "LMT" else None), order_type
