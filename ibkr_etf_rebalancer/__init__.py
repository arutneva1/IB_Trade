"""ibkr_etf_rebalancer package.

This module also ensures that the ``ib-rebalance`` console script is available
on ``PATH`` when the project is used without being installed.  The tests invoke
the entry point directly via ``subprocess.run("ib-rebalance")`` which relies on
the command being discoverable.  By prepending the package directory to
``PATH`` the lightweight wrapper script placed alongside the modules becomes
executable in such scenarios.
"""

from __future__ import annotations

import os
from pathlib import Path

# Expose the directory containing the wrapper script on PATH so the tests can
# find it without installing the package.  This mirrors the behaviour of an
# installed console script.
_dir = Path(__file__).resolve().parent
if str(_dir) not in os.environ.get("PATH", "").split(os.pathsep):  # pragma: no cover
    os.environ["PATH"] = f"{_dir}{os.pathsep}" + os.environ.get("PATH", "")

from .account_state import AccountSnapshot, compute_account_state
from .ibkr_provider import FakeIB, IBKRProvider, IBKRProviderOptions, LiveIB
from .pricing import IBKRQuoteProvider
from .scenario_runner import ScenarioRunResult, run_scenario

__all__ = [
    "AccountSnapshot",
    "compute_account_state",
    "IBKRProvider",
    "IBKRProviderOptions",
    "FakeIB",
    "LiveIB",
    "IBKRQuoteProvider",
    "run_scenario",
    "ScenarioRunResult",
]
