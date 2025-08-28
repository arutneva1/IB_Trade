# IBKR ETF Rebalancer

This project automates rebalancing of ETF portfolios via Interactive Brokers. It loads model portfolios, blends them according to configured weights, compares current holdings, and generates orders to bring the account back to target allocations.

## Project Status

Development is being tracked in phased checklists. Phases 0–3 are implemented; later phases are planned but not yet executed.

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

The command reads a configuration file, model portfolio definitions and the
current account positions before producing CSV and Markdown pre‑trade reports
under the specified ``reports`` directory.

## Further Documentation

- [System Requirements Specification](srs.md)
- [Implementation Plan](plan.md)

