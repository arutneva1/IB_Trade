# IBKR ETF Rebalancer

This project automates rebalancing of ETF portfolios via Interactive Brokers. It loads model portfolios, blends them according to configured weights, compares current holdings, and generates orders to bring the account back to target allocations.

> **Warning:** Trading is risky. Use at your own risk. Always test in paper mode and configure a kill switch file before placing live orders.
> Orders are priced with spread-aware limits to avoid crossing the bid/ask spread.

## Project Status

Development is being tracked in phased checklists. Phases 0–8 are implemented: Phase 4 introduces FX planning for CAD→USD conversions, Phase 5 adds provider abstractions (`IBKRProvider`, `FakeIB`, `LiveIB`) and the `IBKRQuoteProvider` for market data, enabling account snapshot retrieval and pacing safeguards, Phase 6 delivers the order builder and executor with spread-aware limit pricing, FX→SELL→BUY sequencing, and safety rails, Phase 7 adds an end-to-end scenario runner for offline workflow verification, and Phase 8 introduces a Typer-based CLI with structured logging and an `ib-rebalance` console script entry point. Subsequent phases are planned but not yet executed.

## Installation

For development install:

```bash
pip install -e .
```

For runtime use:

```bash
pip install ib-trade
```

## Commands

Run static analysis and formatting checks:

```bash
make lint
```

Run tests:

```bash
make test
```

Quick start:

Use the sample files under `examples/`.

```bash
ib-rebalance pre-trade \
    --config examples/settings.ini \
    --portfolios examples/portfolios.csv \
    --positions examples/positions.csv \
    --cash USD=10000 \
    --output-dir reports
```

To execute a full rebalance against the broker:

```bash
ib-rebalance rebalance \
    --config examples/settings.ini \
    --portfolios examples/portfolios.csv \
    --output-dir reports
```

Or run an offline scenario:

```bash
ib-rebalance --scenario examples/scenario.yml --output-dir reports
```

Display a previously generated report:

```bash
ib-rebalance report --file reports/pre_trade_report_20240101T120000.csv
```

Example pre-trade report snippet (`pre_trade_report_<timestamp>.csv`):

```csv
NetLiq,14000.00
Cash USD,5000.00
Cash Buffer,50.00

symbol,target_pct,current_pct,drift_bps,price,dollar_delta,share_delta,side,est_notional,reason
AAA,88.89,57.35,3154.12,100.0,4415.77,44.16,BUY,4415.77,
BBB,11.11,7.17,394.27,50.0,551.97,11.04,BUY,551.97,
```

Example post-trade report snippet (`post_trade_report_<timestamp>.csv`):

```csv
symbol,side,filled_shares,avg_price,notional,avg_slippage,residual_drift_bps
BBB,BUY,11.0,51.0,561.0,0.0,1.41
AAA,BUY,43.0,101.0,4343.0,0.0,82.69
```

Portfolios CSV schema:

- columns: `portfolio`, `symbol`, `target_pct` (percent values like `40` for 40%).
- Include an optional `CASH` row with a negative `target_pct` to model borrowed cash.
- Extra columns such as `note`, `min_lot`, or `exchange` are ignored.

`settings.ini` groups keys under sections like `[ibkr]`, `[rebalance]`, `[fx]`, `[limits]`, `[safety]`, and `[io]`. See `examples/settings.ini` for a minimal configuration.
The package also installs an `ib-rebalance` console script providing the same
commands. Display the installed version with `ib-rebalance --version`.

Global flags control behaviour: `--report-only`, `--dry-run`,
`--paper/--no-paper` (paper is the default), `--live`, `--yes`,
`--log-level`, `--log-json/--log-text`, `--kill-switch PATH` to override the
default kill switch file, and `--scenario PATH` to execute a YAML-defined
end-to-end scenario instead of loading CSV/INI inputs. Use `--version` to print the
installed package version and exit.

### Configuration precedence

Configuration values are loaded from the INI file provided via `--config`. They
may be overridden by environment variables named
`IBKR_ETF_REBALANCER__SECTION__KEY` and finally by CLI options. Precedence is,
from lowest to highest: INI file, environment variables, CLI options.

For example, to override `[ibkr].account` from the environment:

```bash
export IBKR_ETF_REBALANCER__IBKR__ACCOUNT=DU999
```

Each run writes a log file `run_<timestamp>.log` under `io.report_dir`
(`reports/` by default) and tags log lines with a unique run identifier.
Adjust verbosity with `--log-level` and switch to structured JSON output with
`--log-json`.

Safety defaults favour caution: the CLI refuses live orders unless
`--live --yes` is supplied and `[safety].paper_only` is disabled. Presence of a
kill switch file aborts execution (override the path with `--kill-switch`),
and confirmation prompts are enabled by default.

The configuration file can include an `[fx]` section to plan CAD→USD conversions ahead of ETF trades. This feature lets you enable FX planning and set per-order limits and acceptable slippage:

```ini
[fx]
enabled = true
max_fx_order_usd = 5000
limit_slippage_bps = 5
```

Phase 4 implements this FX planning step, performing conversions offline before submitting dependent ETF orders.

The command reads a configuration file, model portfolio definitions and the
current account positions before producing CSV and Markdown pre‑trade reports
under the specified ``reports`` directory.

Phase 5 adds provider abstractions (`IBKRProvider`, `FakeIB`, `LiveIB`) and the
`IBKRQuoteProvider` for market data. These exports support account snapshot
retrieval and pacing safeguards. [SRS AC3][SRS AC9]

## E2E scenarios

End-to-end scenarios exercise the full workflow offline using fake brokers and
quotes. Run one with:

```bash
python -m ibkr_etf_rebalancer.app --scenario tests/e2e/fixtures/no_trade_within_band.yml
```

Reports and an event log are written to the directory configured by
`io.report_dir` (default `reports/`). Scenario fixtures live under
`tests/e2e/fixtures/` and collectively cover acceptance criteria AC1–AC13.

## Further Documentation

- [System Requirements Specification](srs.md)
- [Implementation Plan](plan.md)

