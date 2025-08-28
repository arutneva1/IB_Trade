"""Order execution infrastructure."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OrderExecutionOptions:
    """Options controlling how orders are executed.

    Parameters
    ----------
    report_only:
        Generate reports without sending orders.
    dry_run:
        Simulate the execution flow without side effects.
    yes:
        Automatically answer affirmatively to confirmation prompts.
    """

    report_only: bool = False
    dry_run: bool = False
    yes: bool = False
