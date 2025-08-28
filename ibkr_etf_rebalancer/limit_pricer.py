"""Limit price calculation helpers.

This module implements the spread aware limit price algorithm described in the
``[limits]`` section of the SRS.  Given the current quote for a symbol it
computes a conservative limit price constrained by the NBBO, a maximum offset
from the mid price and optional escalation rules for wide or stale markets.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
import math

from .config import LimitsConfig
from .pricing import Quote, QuoteProvider, is_stale

__all__ = ["price_limit_buy", "price_limit_sell", "calc_limit_price"]


def _round_to_tick(price: float, tick: float) -> float:
    """Round ``price`` to the nearest multiple of ``tick``.

    IBKR contracts define a minimum tick size; if ``tick`` is non‑positive the
    function falls back to a $0.01 increment.
    """

    if tick <= 0 or not math.isfinite(tick):
        tick = 0.01

    ratio = price / tick
    if not math.isfinite(ratio):
        tick = 0.01
        ratio = price / tick

    return round(ratio) * tick


def price_limit_buy(
    quote: Quote, min_tick: float, cfg: LimitsConfig, now: datetime
) -> tuple[float | None, Literal["LMT", "MKT"]]:
    """Return a conservative BUY price and order type.

    The algorithm follows the spread-aware specification in SRS ``[limits]``:
    apply an offset from the mid price, cap the result by ``max_offset_bps`` and
    optionally the current ask, then round to the contract's minimum tick.  Wide
    or stale markets may escalate according to ``escalate_action``.  When
    ``escalate_action`` is ``"market"`` this function returns ``None`` and the
    ``"MKT"`` order type.
    """

    bid, ask = quote.bid, quote.ask
    if bid is None or ask is None:
        raise ValueError("Quote missing bid/ask")
    spread = ask - bid
    if spread <= 0:
        raise ValueError("Quote ask must be greater than bid")

    mid = (bid + ask) / 2
    spread_bps = (spread / mid) * 10000

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
            return _round_to_tick(ask, min_tick), "LMT"
        if action == "market":
            return None, "MKT"
        # action == "keep" simply keeps the capped price

    return price, "LMT"


def price_limit_sell(
    quote: Quote, min_tick: float, cfg: LimitsConfig, now: datetime
) -> tuple[float | None, Literal["LMT", "MKT"]]:
    """Return a conservative SELL price and order type.

    Behaviour mirrors :func:`price_limit_buy` but for the SELL side as described
    in SRS ``[limits]``.  When ``escalate_action`` is ``"market"`` the function
    returns ``None`` and the ``"MKT"`` order type.
    """

    bid, ask = quote.bid, quote.ask
    if bid is None or ask is None:
        raise ValueError("Quote missing bid/ask")
    spread = ask - bid
    if spread <= 0:
        raise ValueError("Quote ask must be greater than bid")

    mid = (bid + ask) / 2
    spread_bps = (spread / mid) * 10000

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
            return _round_to_tick(bid, min_tick), "LMT"
        if action == "market":
            return None, "MKT"

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

    This thin wrapper exists for backward compatibility and delegates to the
    pure ``price_limit_buy`` or ``price_limit_sell`` functions defined by the
    SRS ``[limits]`` section.  The helper functions already return ``None`` when
    a market order is requested.
    """

    quote = provider.get_quote(symbol)
    side_u = side.upper()
    if side_u not in {"BUY", "SELL"}:
        raise ValueError("Side must be 'BUY' or 'SELL'")

    # Allow disabling the spread-aware algorithm entirely.  When smart_limit is
    # False or an unsupported style is selected, fall back to a naive bid/ask
    # price to avoid surprising behaviour.
    if not cfg.smart_limit or cfg.style != "spread_aware":
        bid, ask = quote.bid, quote.ask
        if bid is None or ask is None:
            raise ValueError("Quote missing bid/ask")
        if not cfg.smart_limit or cfg.style == "off":
            return (ask if side_u == "BUY" else bid), "LMT"
        msg = f"Unsupported limit pricing style: {cfg.style}"
        raise ValueError(msg)

    if side_u == "BUY":
        return price_limit_buy(quote, tick, cfg, now)
    # side_u == "SELL"
    return price_limit_sell(quote, tick, cfg, now)
