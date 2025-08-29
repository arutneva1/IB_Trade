"""Interactive Brokers provider abstraction."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Callable, Mapping, Protocol, Sequence, runtime_checkable

from ib_async import IB, Contract as IBContract, Order as IBOrder  # type: ignore

from . import pricing


class OrderSide(str, Enum):
    """Side of an order."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Order type."""

    MARKET = "MKT"
    LIMIT = "LMT"


class TimeInForce(str, Enum):
    """Time in force for an order."""

    DAY = "DAY"
    GTC = "GTC"


class OrderRoute(str, Enum):
    """Routing destination for an order."""

    SMART = "SMART"
    ISLAND = "ISLAND"


class RTH(int, Enum):
    """Regular trading hours flag."""

    RTH_ONLY = 1
    ALL_HOURS = 0


@dataclass(frozen=True)
class Contract:
    """Tradable contract specification."""

    symbol: str
    sec_type: str = "STK"
    currency: str = "USD"
    exchange: str = "SMART"


@dataclass(frozen=True)
class Order:
    """Order details."""

    contract: Contract
    side: OrderSide
    quantity: float
    order_type: OrderType
    tif: TimeInForce = TimeInForce.DAY
    route: OrderRoute = OrderRoute.SMART
    limit_price: float | None = None
    rth: RTH = RTH.RTH_ONLY


@dataclass(frozen=True)
class Fill:
    """Execution fill details."""

    contract: Contract
    side: OrderSide
    quantity: float
    price: float
    timestamp: datetime | None = None


@dataclass(frozen=True)
class Quote:
    """Market quote information."""

    contract: Contract
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None
    timestamp: datetime | None = None


@dataclass(frozen=True)
class AccountValue:
    """Single account value entry."""

    tag: str
    value: float
    currency: str | None = None


@dataclass(frozen=True)
class Position:
    """Open position information."""

    account: str
    contract: Contract
    quantity: float
    avg_price: float


@dataclass
class IBKRProviderOptions:
    """Options for configuring the IBKR provider connection.

    Parameters
    ----------
    paper:
        Connect to the paper trading environment.
    live:
        Connect to a live trading environment.
    dry_run:
        Avoid performing any side effects on the provider.
    host:
        Hostname of the TWS or gateway API.
    port:
        Port of the TWS or gateway API.
    client_id:
        Client ID for the API connection.
    """

    paper: bool = False
    live: bool = False
    dry_run: bool = False
    host: str = "127.0.0.1"
    port: int = 7497
    client_id: int = 0


class ProviderError(Exception):
    """Base class for provider errors."""


class ResolutionError(ProviderError):
    """Raised when a contract cannot be resolved."""


class PacingError(ProviderError):
    """Raised when provider pacing limits are exceeded."""


@runtime_checkable
class IBKRProvider(Protocol):
    """Protocol for IBKR provider implementations."""

    options: IBKRProviderOptions

    def connect(self) -> None:
        """Establish connection to the provider."""

    def disconnect(self) -> None:
        """Terminate connection to the provider."""

    def resolve_contract(self, contract: Contract) -> Contract:
        """Resolve a partially specified contract."""

    def get_quote(self, contract: Contract) -> Quote:
        """Return the latest market quote."""

    def get_account_values(self) -> Sequence[AccountValue]:
        """Return current account values."""

    def get_positions(self) -> Sequence[Position]:
        """Return current open positions."""

    def place_order(self, order: Order) -> str:
        """Submit an order and return an order identifier."""

    def cancel(self, order_id: str) -> None:
        """Cancel an open order."""

    def wait_for_fills(
        self, order_ids: Sequence[str], timeout: float | None = None
    ) -> Sequence[Fill]:
        """Wait for fills and return them."""


class LiveIB:
    """Stubbed provider implementation using :mod:`ib_async` types.

    The class defines the same interface as :class:`FakeIB` but leaves all
    methods unimplemented for future development. No network connections are
    established on import or instantiation.
    """

    def __init__(self, options: IBKRProviderOptions | None = None) -> None:
        self.options = options or IBKRProviderOptions()
        self._ib: IB | None = None

    # ------------------------------------------------------------------
    # IBKRProvider interface
    def connect(self) -> None:  # pragma: no cover - stub
        raise NotImplementedError

    def disconnect(self) -> None:  # pragma: no cover - stub
        raise NotImplementedError

    def resolve_contract(self, contract: Contract) -> Contract:  # pragma: no cover - stub
        raise NotImplementedError

    def get_quote(self, contract: Contract) -> Quote:  # pragma: no cover - stub
        raise NotImplementedError

    def get_account_values(self) -> Sequence[AccountValue]:  # pragma: no cover - stub
        raise NotImplementedError

    def get_positions(self) -> Sequence[Position]:  # pragma: no cover - stub
        raise NotImplementedError

    def place_order(self, order: Order) -> str:  # pragma: no cover - stub
        raise NotImplementedError

    def cancel(self, order_id: str) -> None:  # pragma: no cover - stub
        raise NotImplementedError

    def wait_for_fills(
        self, order_ids: Sequence[str], timeout: float | None = None
    ) -> Sequence[Fill]:  # pragma: no cover - stub
        raise NotImplementedError

    # ------------------------------------------------------------------
    # conversion helpers
    def _to_ib_contract(self, contract: Contract) -> IBContract:  # pragma: no cover - stub
        raise NotImplementedError

    def _to_ib_order(self, order: Order) -> IBOrder:  # pragma: no cover - stub
        raise NotImplementedError


class FakeIB:
    """In-memory implementation of :class:`IBKRProvider` for tests.

    The class exposes its internal state so tests can inspect and modify it
    directly. Quotes are stored as :class:`pricing.Quote` objects and returned
    with UTC timestamps, allowing stale quote simulation by seeding old
    timestamps.
    """

    def __init__(
        self,
        options: IBKRProviderOptions | None = None,
        *,
        contracts: Mapping[str, Contract] | None = None,
        quotes: Mapping[str, pricing.Quote] | None = None,
        account_values: Sequence[AccountValue] | None = None,
        positions: Sequence[Position] | None = None,
        symbol_overrides: Mapping[str, str | Contract] | None = None,
        concurrency_limit: int | None = None,
        pacing_hook: Callable[[int], None] | None = None,
    ) -> None:
        self.options = options or IBKRProviderOptions()
        self._contracts: dict[str, Contract] = dict(contracts or {})
        self._quotes: dict[str, pricing.Quote] = dict(quotes or {})
        self._account_values: list[AccountValue] = list(account_values or [])
        self._positions: list[Position] = list(positions or [])
        self._symbol_overrides: dict[str, str | Contract] = dict(symbol_overrides or {})
        self._connected = False
        self._next_order_id = 0
        self._orders: dict[str, Order] = {}
        self._event_log: list[dict[str, object]] = []
        self._last_ts = datetime.now(timezone.utc)
        self._concurrency_limit = concurrency_limit
        self._pacing_hook = pacing_hook

    # ------------------------------------------------------------------
    # state helpers
    @property
    def state(self) -> dict[str, object]:
        """Return a snapshot of internal state for tests."""

        return {
            "connected": self._connected,
            "contracts": self._contracts,
            "quotes": self._quotes,
            "account_values": self._account_values,
            "positions": self._positions,
        }

    # ------------------------------------------------------------------
    # IBKRProvider interface
    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def resolve_contract(self, contract: Contract) -> Contract:
        symbol = contract.symbol
        override = self._symbol_overrides.get(symbol)
        if override is not None:
            if isinstance(override, Contract):
                return override
            if isinstance(override, str):
                symbol = override
            else:  # pragma: no cover - defensive
                raise ResolutionError(f"Unsupported override type for {symbol!r}")
        if symbol not in self._contracts:
            msg = f"Unknown symbol: {symbol}"
            raise ResolutionError(msg)
        return self._contracts[symbol]

    def get_quote(self, contract: Contract) -> pricing.Quote:
        resolved = self.resolve_contract(contract)
        if resolved.symbol not in self._quotes:
            msg = f"No quote for {resolved.symbol}"
            raise KeyError(msg)
        quote = self._quotes[resolved.symbol]
        ts = quote.ts
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)
        return pricing.Quote(quote.bid, quote.ask, ts, last=quote.last)

    def get_account_values(self) -> Sequence[AccountValue]:
        return list(self._account_values)

    def get_positions(self) -> Sequence[Position]:
        return list(self._positions)

    # --- event helpers -------------------------------------------------
    def _timestamp(self) -> datetime:
        """Return a monotonic timestamp."""
        now = datetime.now(timezone.utc)
        if now <= self._last_ts:
            now = self._last_ts + timedelta(microseconds=1)
        self._last_ts = now
        return now

    def _log_event(self, event_type: str, order_id: str, **data: object) -> None:
        event = {"ts": self._timestamp(), "type": event_type, "order_id": order_id}
        event.update(data)
        self._event_log.append(event)

    # ------------------------------------------------------------------
    def place_order(self, order: Order) -> str:
        if order.quantity <= 0:
            raise ValueError("Quantity must be positive")

        resolved = self.resolve_contract(order.contract)
        order = replace(order, contract=resolved)

        if self._concurrency_limit is not None and len(self._orders) >= self._concurrency_limit:
            if self._pacing_hook is not None:
                self._pacing_hook(len(self._orders))
            raise PacingError("pacing limit exceeded")

        self._next_order_id += 1
        order_id = str(self._next_order_id)
        self._orders[order_id] = order
        self._log_event("placed", order_id, order=order)
        return order_id

    def cancel(self, order_id: str) -> None:
        order = self._orders.pop(order_id, None)
        if order is not None:
            self._log_event("canceled", order_id, order=order)

    def wait_for_fills(
        self, order_ids: Sequence[str], timeout: float | None = None
    ) -> Sequence[Fill]:
        fills: list[Fill] = []
        for oid in order_ids:
            order = self._orders.get(oid)
            if order is None:
                continue

            quote = self._quotes.get(order.contract.symbol)
            price: float | None = None

            if order.order_type is OrderType.MARKET:
                if quote is not None:
                    price = quote.ask if order.side is OrderSide.BUY else quote.bid
                if price is None and quote is not None:
                    price = quote.last
            else:  # LIMIT
                limit = order.limit_price
                if quote is not None and limit is not None:
                    if order.side is OrderSide.BUY:
                        market = quote.ask if quote.ask is not None else quote.last
                        if market is not None and market <= limit:
                            price = min(market, limit)
                    else:  # SELL
                        market = quote.bid if quote.bid is not None else quote.last
                        if market is not None and market >= limit:
                            price = max(market, limit)

            if price is None:
                continue

            fill = Fill(
                contract=order.contract,
                side=order.side,
                quantity=order.quantity,
                price=price,
                timestamp=self._timestamp(),
            )
            fills.append(fill)
            self._log_event("filled", oid, fill=fill)
            self._orders.pop(oid, None)

        return fills


__all__ = [
    "Contract",
    "Order",
    "Fill",
    "Quote",
    "AccountValue",
    "Position",
    "OrderSide",
    "OrderType",
    "TimeInForce",
    "OrderRoute",
    "RTH",
    "ProviderError",
    "ResolutionError",
    "PacingError",
    "IBKRProvider",
    "IBKRProviderOptions",
    "LiveIB",
    "FakeIB",
]
