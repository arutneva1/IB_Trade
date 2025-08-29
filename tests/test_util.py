"""Tests for generic utility helpers."""

import pytest

from ibkr_etf_rebalancer.util import (
    from_bps,
    from_percent,
    to_bps,
    to_percent,
    clamp,
)


def test_to_bps_and_back() -> None:
    value = 0.0125  # 1.25%
    bps = to_bps(value)
    assert bps == 125.0
    assert from_bps(bps) == value


def test_to_percent_and_back() -> None:
    value = 0.0125  # 1.25%
    percent = to_percent(value)
    assert percent == 1.25
    assert from_percent(percent) == value


def test_from_bps_negative() -> None:
    assert from_bps(-50) == -0.005


def test_from_percent_negative() -> None:
    assert from_percent(-1.5) == -0.015


def test_clamp_basic() -> None:
    assert clamp(5, 0, 10) == 5
    assert clamp(-1, 0, 10) == 0
    assert clamp(11, 0, 10) == 10


def test_clamp_errors() -> None:
    with pytest.raises(ValueError):
        clamp(1, 5, 3)
