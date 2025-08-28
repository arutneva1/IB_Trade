import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from ibkr_etf_rebalancer.config import AppConfig, load_config

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
    assert cfg.ibkr.read_only is True
    assert cfg.pricing.price_source == "last"
    assert cfg.pricing.fallback_to_snapshot is True
    assert not hasattr(cfg.safety, "max_drawdown")


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


def test_invalid_allow_margin():
    data = valid_config_dict()
    data["rebalance"]["allow_margin"] = -1
    with pytest.raises(ValidationError):
        AppConfig(**data)


def test_invalid_read_only():
    data = valid_config_dict()
    data["ibkr"]["read_only"] = "maybe"
    with pytest.raises(ValidationError):
        AppConfig(**data)


def test_allow_margin_true():
    data = valid_config_dict()
    data["rebalance"]["allow_margin"] = True
    cfg = AppConfig(**data)
    assert cfg.rebalance.allow_margin is True


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


def test_invalid_price_source():
    data = valid_config_dict()
    data["pricing"] = {"price_source": "bogus"}
    with pytest.raises(ValidationError):
        AppConfig(**data)


def test_fallback_to_snapshot_coercion():
    data = valid_config_dict()
    data["pricing"] = {"fallback_to_snapshot": "false"}
    cfg = AppConfig(**data)
    assert cfg.pricing.fallback_to_snapshot is False

    data["pricing"] = {"fallback_to_snapshot": "1"}
    cfg2 = AppConfig(**data)
    assert cfg2.pricing.fallback_to_snapshot is True


def test_symbol_overrides_parsing(tmp_path: Path):
    ini = tmp_path / "config.ini"
    ini.write_text(
        """
[ibkr]
account = DU123

[models]
SMURF = 0.5
BADASS = 0.3
GLTR = 0.2

[rebalance]

[fx]

[limits]

[safety]

[io]

[symbol_overrides]
GBTC = BTC
FUND = 1234
"""
    )

    cfg = load_config(ini)
    assert cfg.symbol_overrides == {"GBTC": "BTC", "FUND": 1234}


def test_symbol_overrides_validation():
    data = valid_config_dict()
    data["symbol_overrides"] = {"GBTC": 1.23}
    with pytest.raises(ValidationError):
        AppConfig(**data)


def test_symbol_overrides_absent(tmp_path: Path):
    cfg = AppConfig(**valid_config_dict())
    assert cfg.symbol_overrides == {}

    ini = tmp_path / "config.ini"
    ini.write_text(
        """
[ibkr]
account = DU123

[models]
SMURF = 0.5
BADASS = 0.3
GLTR = 0.2

[rebalance]

[fx]

[limits]

[safety]

[io]
"""
    )

    cfg2 = load_config(ini)
    assert cfg2.symbol_overrides == {}


def test_load_config_success(tmp_path: Path):
    ini = tmp_path / "config.ini"
    ini.write_text(
        """
[ibkr]
account = DU123
read_only = false

[models]
SMURF = 0.5
BADASS = 0.3
GLTR = 0.2

[rebalance]

[fx]

[limits]

[safety]

[io]
"""
    )

    cfg = load_config(ini)
    assert cfg.ibkr.account == "DU123"
    assert cfg.ibkr.read_only is False
    assert cfg.models.SMURF == 0.5


def test_load_config_missing_section(tmp_path: Path):
    ini = tmp_path / "config.ini"
    ini.write_text(
        """
[ibkr]
account = DU123

[models]
SMURF = 0.5
BADASS = 0.3
GLTR = 0.2

[rebalance]

[limits]

[safety]

[io]
"""
    )

    with pytest.raises(ValidationError):
        load_config(ini)
