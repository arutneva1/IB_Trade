"""Interactive Brokers provider abstraction."""

from __future__ import annotations

from dataclasses import dataclass


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
    """

    paper: bool = False
    live: bool = False
    dry_run: bool = False
