"""Blend model portfolios into final targets.

This module combines the portfolios produced by individual models
(SMURF, BADASS, GLTR) according to the weights specified in the
``[models]`` section of the application configuration.

The blending process:
    1. Multiply each model's asset weights by its configured mix weight.
    2. Combine overlapping symbols by summing their contributions.
    3. Carry any ``CASH`` row forward as a borrow indicator.
    4. Compute gross (sum of asset weights) and net (including ``CASH``)
       exposure and normalise the final weights so that net exposure is
       exactly ``100%``.
    5. Return the targets in deterministic alphabetical order for
       stable reporting.
"""

from __future__ import annotations

from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from typing import Mapping, Dict

from .config import ModelsConfig


@dataclass
class BlendResult:
    """Result of blending model portfolios."""

    weights: "OrderedDict[str, float]"
    """Normalised target weights per symbol (including ``CASH``)."""

    gross_exposure: float
    """Total long exposure excluding ``CASH`` (always positive)."""

    net_exposure: float
    """Net exposure after including ``CASH`` (should equal ``1.0``)."""


def blend_targets(
    portfolios: Mapping[str, Mapping[str, float]],
    models: ModelsConfig,
) -> BlendResult:
    """Blend model portfolios according to ``models`` weights.

    Parameters
    ----------
    portfolios:
        Mapping of model name to ``{symbol: weight}`` dictionaries. Each
        weight is a fractional value (e.g. ``0.25`` for ``25%``).  A
        special ``CASH`` symbol may appear with a negative weight to
        represent borrowed cash.
    models:
        ``ModelsConfig`` instance providing the mix weights for SMURF,
        BADASS and GLTR.  The weights are expected to sum to ``1.0``.

    Returns
    -------
    BlendResult
        Normalised weights plus gross and net exposure figures.
    """

    # Accumulate contributions from each model
    contributions: Dict[str, float] = defaultdict(float)
    for model_name, model_weight in [
        ("SMURF", models.SMURF),
        ("BADASS", models.BADASS),
        ("GLTR", models.GLTR),
    ]:
        for symbol, weight in portfolios.get(model_name, {}).items():
            contributions[symbol] += weight * model_weight

    net = sum(contributions.values())
    if net == 0:  # pragma: no cover - defensive; portfolios validated elsewhere
        raise ValueError("Combined portfolio has zero net exposure")

    # Normalise so that net exposure equals 100%
    for symbol in list(contributions.keys()):
        contributions[symbol] /= net

    gross = sum(w for s, w in contributions.items() if s != "CASH")
    net = gross + contributions.get("CASH", 0.0)

    ordered = OrderedDict(sorted(contributions.items()))

    return BlendResult(weights=ordered, gross_exposure=gross, net_exposure=net)


__all__ = ["BlendResult", "blend_targets"]
