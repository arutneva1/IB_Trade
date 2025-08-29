"""Interactive Brokers provider abstraction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol, Sequence, runtime_checkable


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
]
