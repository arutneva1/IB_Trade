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
from .pricing import QuoteProvider, is_stale

__all__ = ["calc_limit_price"]


def _round_to_tick(price: float, tick: float) -> float:
    """Round ``price`` to the nearest multiple of ``tick``.

    IBKR contracts define a minimum tick size; if ``tick`` is non‑positive the
    function falls back to a $0.01 increment.
    """

    if tick <= 0:
        tick = 0.01
    return round(price / tick) * tick


def calc_limit_price(
    side: Literal["BUY", "SELL"],
    symbol: str,
    tick: float,
    provider: QuoteProvider,
    now: datetime,
    cfg: LimitsConfig,
) -> tuple[float | None, Literal["LMT", "MKT"]]:
    """Return a limit price and order type for *side* on *symbol*.

    Parameters
    ----------
    side:
        ``"BUY"`` or ``"SELL"``.
    symbol:
        Ticker to price.
    tick:
        Minimum price increment for the contract.
    provider:
        Quote source used to obtain bid/ask data.
    now:
        Current timestamp used for staleness checks.
    cfg:
        ``LimitsConfig`` with pricing parameters.

    Returns
    -------
    tuple[float | None, str]
        ``(price, order_type)`` where ``price`` is ``None`` for market orders.
    """

    side_u = side.upper()
    quote = provider.get_quote(symbol)
    bid, ask = quote.bid, quote.ask

    if bid is None or ask is None:
        raise ValueError("Quote missing bid/ask")
    if ask <= bid:
        raise ValueError("Quote ask must be greater than bid")

    mid = (bid + ask) / 2
    spread = ask - bid
    spread_bps = spread / (bid + ask) * 10000

    if side_u == "BUY":
        price = mid + cfg.buy_offset_frac * spread
        price = _round_to_tick(price, tick)
        mid_cap = round(mid, 0)
        price = min(price, mid_cap * (1 + cfg.max_offset_bps / 10000))
        if cfg.use_ask_bid_cap:
            price = min(price, ask)
    else:  # SELL
        price = mid - cfg.sell_offset_frac * spread
        price = _round_to_tick(price, tick)
        mid_cap = round(mid, 0)
        price = max(price, mid_cap * (1 - cfg.max_offset_bps / 10000))
        if cfg.use_ask_bid_cap:
            price = max(price, bid)

    wide_or_stale = spread_bps > cfg.wide_spread_bps or is_stale(
        quote, now, cfg.stale_quote_seconds
    )
    if wide_or_stale:
        action = cfg.escalate_action
        if action == "cross":
            price = ask if side_u == "BUY" else bid
            return price, "LMT"
        if action == "market":
            return None, "MKT"
        if action == "keep":
            if side_u == "BUY":
                price = mid * (1 + cfg.max_offset_bps / 10000)
                price = _round_to_tick(price, tick)
                if cfg.use_ask_bid_cap:
                    price = min(price, ask)
            else:
                price = mid * (1 - cfg.max_offset_bps / 10000)
                price = _round_to_tick(price, tick)
                if cfg.use_ask_bid_cap:
                    price = max(price, bid)

    return price, "LMT"
