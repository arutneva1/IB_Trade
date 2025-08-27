import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from ibkr_etf_rebalancer.config import AppConfig

# Ensure project root on path for direct test execution
sys.path.append(str(Path(__file__).resolve().parents[1]))


def valid_config_dict():
    return {
        "ibkr": {"account": "DU123"},
        "models": {"SMURF": 0.5, "BADASS": 0.3, "GLTR": 0.2},
        "rebalance": {},
        "fx": {},
        "limits": {},
        "safety": {},
        "io": {},
    }


def test_valid_config():
    cfg = AppConfig(**valid_config_dict())
    assert cfg.models.SMURF == 0.5
    assert cfg.rebalance.trigger_mode == "per_holding"
    assert cfg.limits.style == "spread_aware"


def test_missing_section():
    data = valid_config_dict()
    data.pop("fx")
    with pytest.raises(ValidationError):
        AppConfig(**data)


def test_model_weights_sum():
    data = valid_config_dict()
    data["models"]["GLTR"] = 0.3  # total = 1.1
    with pytest.raises(ValidationError):
        AppConfig(**data)


def test_invalid_max_leverage():
    data = valid_config_dict()
    data["rebalance"]["max_leverage"] = -1
    with pytest.raises(ValidationError):
        AppConfig(**data)


def test_invalid_trigger_mode():
    data = valid_config_dict()
    data["rebalance"]["trigger_mode"] = "bad"
    with pytest.raises(ValidationError):
        AppConfig(**data)


def test_invalid_limits_style():
    data = valid_config_dict()
    data["limits"]["style"] = "bad"
    with pytest.raises(ValidationError):
        AppConfig(**data)


def test_invalid_fx_buffer():
    data = valid_config_dict()
    data["fx"]["fx_buffer_bps"] = -1
    with pytest.raises(ValidationError):
        AppConfig(**data)
