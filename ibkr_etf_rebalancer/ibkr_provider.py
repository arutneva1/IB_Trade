"""Interactive Brokers provider abstraction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Mapping, Protocol, Sequence, runtime_checkable

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

    def wait_for_fills(self, order_id: str, timeout: float | None = None) -> Sequence[Fill]:
        """Wait for fills and return them."""


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

    def place_order(self, order: Order) -> str:
        self._next_order_id += 1
        order_id = str(self._next_order_id)
        self._orders[order_id] = order
        return order_id

    def cancel(self, order_id: str) -> None:
        self._orders.pop(order_id, None)

    def wait_for_fills(self, order_id: str, timeout: float | None = None) -> Sequence[Fill]:
        order = self._orders.pop(order_id, None)
        if order is None:
            return []
        quote = self._quotes.get(order.contract.symbol)
        price = 0.0
        if quote is not None:
            price = (quote.bid if order.side is OrderSide.SELL else quote.ask) or quote.last or 0.0
        fill = Fill(
            contract=order.contract,
            side=order.side,
            quantity=order.quantity,
            price=price,
            timestamp=datetime.now(timezone.utc),
        )
        return [fill]


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
    "FakeIB",
]
