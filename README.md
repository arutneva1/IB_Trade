# IBKR ETF Rebalancer

This project automates rebalancing of ETF portfolios via Interactive Brokers. It loads model portfolios, blends them according to configured weights, compares current holdings, and generates orders to bring the account back to target allocations.

## Project Status

Development is being tracked in phased checklists. Phases 0–7 are implemented: Phase 4 introduces FX planning for CAD→USD conversions, Phase 5 adds provider abstractions (`IBKRProvider`, `FakeIB`, `LiveIB`) and the `IBKRQuoteProvider` for market data, enabling account snapshot retrieval and pacing safeguards, Phase 6 delivers the order builder and executor with spread-aware limit pricing, FX→SELL→BUY sequencing, and safety rails, and Phase 7 adds an end-to-end scenario runner for offline workflow verification. Subsequent phases are planned but not yet executed.

## Commands

Run static analysis and formatting checks:

```bash
make lint
```

Run tests:

```bash
make test
```

Examples:

```bash
python -m ibkr_etf_rebalancer.app pre-trade \
    --config config.ini \
    --portfolios portfolios.csv \
    --positions positions.csv \
    --cash USD=10000 \
    --output-dir reports
```

To execute a full rebalance against the broker:

```bash
python -m ibkr_etf_rebalancer.app rebalance \
    --config config.ini \
    --portfolios portfolios.csv \
    --output-dir reports
```

The package also installs an `ib-rebalance` console script providing the same
commands. Display the installed version with `ib-rebalance --version`.

Global flags control behaviour: `--report-only`, `--dry-run`,
`--paper/--no-paper` (paper is the default), `--live`, `--yes`,
`--log-level`, `--log-json/--log-text`, `--kill-switch PATH` to override the
default kill switch file, and `--scenario PATH` to execute a YAML-defined
end-to-end scenario instead of loading CSV/INI inputs. Use `--version` to print the
installed package version and exit.

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

