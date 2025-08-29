# IBKR ETF Rebalancer

This project automates rebalancing of ETF portfolios via Interactive Brokers. It loads model portfolios, blends them according to configured weights, compares current holdings, and generates orders to bring the account back to target allocations.

## Project Status

Development is being tracked in phased checklists. Phases 0–5 are implemented, with Phase 4 introducing FX planning for CAD→USD conversions and Phase 5 adding provider abstractions (`IBKRProvider`, `FakeIB`, `LiveIB`) and the `IBKRQuoteProvider` for market data, enabling account snapshot retrieval and pacing safeguards. Later phases are planned but not yet executed.

## Commands

Run static analysis and formatting checks:

```bash
make lint
```

Run tests:

```bash
make test
```

Example run of the application:

```bash
python -m ibkr_etf_rebalancer.app pre-trade \
    --config config.ini \
    --portfolios portfolios.csv \
    --positions positions.csv \
    --cash USD=10000 \
    --output-dir reports
```

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

## Further Documentation

- [System Requirements Specification](srs.md)
- [Implementation Plan](plan.md)

