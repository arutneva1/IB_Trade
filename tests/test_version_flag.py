import importlib.metadata
import subprocess


def test_version_flag_prints_current_version() -> None:
    expected = importlib.metadata.version("ib-trade")
    result = subprocess.run(
        ["ib-rebalance", "--version"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == expected
