from pathlib import Path
import sys

# Ensure project root is on the module search path so the script can be executed
# directly via ``python tests/e2e/update_golden.py``.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ibkr_etf_rebalancer.scenario import load_scenario
from ibkr_etf_rebalancer.scenario_runner import run_scenario

FIXTURE_DIR = Path(__file__).parent / "fixtures"
GOLDEN_DIR = Path(__file__).parent / "golden"


def main() -> None:
    for fixture_path in sorted(FIXTURE_DIR.glob("*.yml")):
        scenario = load_scenario(fixture_path)
        if scenario.config_overrides.get("rebalance", {}).get("min_order_usd", 1) <= 0:
            scenario.config_overrides.setdefault("rebalance", {})["min_order_usd"] = 1e-9
        scenario.config_overrides.setdefault("io", {})["report_dir"] = str(
            GOLDEN_DIR / fixture_path.stem
        )
        result = run_scenario(scenario)
        out_dir = result.pre_report_csv.parent
        print(f"Generated outputs for {fixture_path.stem} in {out_dir}")


if __name__ == "__main__":
    main()
