"""Miscellaneous utility helpers.

This module currently provides small helper functions that are used across the
code base.  Keeping them here avoids sprinkling ``10_000`` constants for basis
point conversions throughout the project which in turn helps maintain
consistency when dealing with sizing and reporting logic.
"""

from __future__ import annotations

__all__ = ["to_bps", "from_bps", "clamp"]


def to_bps(fraction: float) -> float:
    """Convert *fraction* to basis points.

    Examples
    --------
    ``0.0125`` (1.25%) becomes ``125`` basis points.
    """

    return fraction * 10_000


def from_bps(bps: float) -> float:
    """Convert *bps* (basis points) to a fractional value.

    Examples
    --------
    ``125`` basis points becomes ``0.0125`` (1.25%).
    """

    return bps / 10_000


def clamp(value: float, lower: float | None = None, upper: float | None = None) -> float:
    """Return *value* constrained to the inclusive range ``[lower, upper]``.

    Parameters
    ----------
    value:
        The value to clamp.
    lower:
        Optional lower bound.
    upper:
        Optional upper bound.

    Returns
    -------
    float
        ``value`` clamped so it does not fall below ``lower`` or rise above
        ``upper``.

    Raises
    ------
    ValueError
        If both bounds are provided and ``lower`` is greater than ``upper``.
    """

    if lower is not None and upper is not None and lower > upper:
        raise ValueError("lower bound cannot exceed upper bound")
    if lower is not None:
        value = max(lower, value)
    if upper is not None:
        value = min(upper, value)
    return value
