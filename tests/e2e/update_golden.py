from pathlib import Path
import sys

FIXTURE_DIR = Path(__file__).parent / "fixtures"
GOLDEN_DIR = Path(__file__).parent / "golden"


def main() -> None:
    """Generate golden files for test scenarios."""
    # Ensure project root is on the module search path so the script can be
    # executed directly via ``python tests/e2e/update_golden.py``.
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from ibkr_etf_rebalancer.scenario import load_scenario
    from ibkr_etf_rebalancer.scenario_runner import run_scenario

    for fixture_path in sorted(FIXTURE_DIR.glob("*.yml")):
        scenario = load_scenario(fixture_path)
        if scenario.config_overrides.get("rebalance", {}).get("min_order_usd", 1) <= 0:
            scenario.config_overrides.setdefault("rebalance", {})["min_order_usd"] = 1e-9
        scenario.config_overrides.setdefault("io", {})["report_dir"] = str(
            GOLDEN_DIR / fixture_path.stem
        )
        kill_switch = scenario.config_overrides.get("safety", {}).get("kill_switch_file")
        kill_path = Path(kill_switch) if kill_switch else None
        if kill_path:
            kill_path.write_text("")
        try:
            result = run_scenario(scenario)
        finally:
            if kill_path and kill_path.exists():
                kill_path.unlink()
        out_dir = result.pre_report_csv.parent
        print(f"Generated outputs for {fixture_path.stem} in {out_dir}")


if __name__ == "__main__":
    main()
