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
        "rebalance": {"allow_fractional": True, "allow_margin": False},
        "fx": {"base_currency": "USD", "max_spread": 0.01},
        "limits": {"allow_margin": False, "allow_fractional": True, "max_leverage": 1.0},
        "safety": {"max_drawdown": 0.5},
        "io": {"output_dir": "/tmp", "log_level": "INFO"},
    }


def test_valid_config():
    cfg = AppConfig(**valid_config_dict())
    assert cfg.models.SMURF == 0.5
    assert cfg.limits.max_leverage == 1.0


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
    data["limits"]["max_leverage"] = -1
    with pytest.raises(ValidationError):
        AppConfig(**data)


def test_invalid_fx_spread():
    data = valid_config_dict()
    data["fx"]["max_spread"] = -0.01
    with pytest.raises(ValidationError):
        AppConfig(**data)
