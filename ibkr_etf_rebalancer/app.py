"""Command line interface for the IBKR ETF rebalancer.

This module exposes a small Typer based CLI that stitches together the core
building blocks used throughout the project:

* :func:`config.load_config` – parse an INI style configuration file.
* :func:`portfolio_loader.load_portfolios` – read model portfolio weights.
* :func:`target_blender.blend_targets` – blend the model portfolios according
  to their configured weights.
* :func:`account_state.compute_account_state` – derive the account snapshot
  from current positions and cash balances.
* :func:`reporting.generate_pre_trade_report` – produce a pre‑trade report
  summarising the drift and suggested trades.

The resulting command is intentionally lightweight but demonstrates how the
individual pieces fit together.  It accepts CSV inputs for the model
portfolios and current positions and allows cash balances to be specified on
the command line.  Reports are written to the directory configured in the
configuration file unless an explicit ``--output-dir`` is supplied.

Example
-------

Running a pre‑trade report from the command line::

    python -m ibkr_etf_rebalancer.app pre-trade \
        --config config.ini \
        --portfolios portfolios.csv \
        --positions positions.csv \
        --cash USD=10000 --cash CAD=500 \
        --output-dir reports

This will emit a CSV and Markdown report under ``reports/`` with a
timestamped filename and echo a textual summary to standard output.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import typer

from .account_state import compute_account_state
from .config import load_config
from .ibkr_provider import IBKRProviderOptions
from .order_executor import OrderExecutionOptions
from .portfolio_loader import load_portfolios
from .reporting import generate_pre_trade_report
from .target_blender import blend_targets


app = typer.Typer(help="Utilities for running pre-trade reports and scenarios")


@dataclass
class CLIOptions:
    """Global command line flags routed to downstream components."""

    report_only: bool = False
    dry_run: bool = False
    paper: bool = True
    live: bool = False
    yes: bool = False


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    report_only: bool = typer.Option(
        False, "--report-only", help="Generate reports without placing orders"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Simulate actions without side effects"),
    paper: bool = typer.Option(
        True, "--paper/--no-paper", help="Use the paper trading environment"
    ),
    live: bool = typer.Option(False, "--live", help="Use the live trading environment"),
    yes: bool = typer.Option(False, "--yes", help="Assume yes for all confirmations"),
    scenario: Path | None = typer.Option(
        None,
        "--scenario",
        exists=True,
        readable=True,
        help="Run YAML scenario and exit",
    ),
) -> None:
    """IBKR ETF rebalancer command line utilities."""
    options = CLIOptions(
        report_only=report_only,
        dry_run=dry_run,
        paper=paper,
        live=live,
        yes=yes,
    )
    # Run a pre-canned scenario and exit when requested.
    if scenario is not None:
        from . import safety
        from tests.e2e.scenario import load_scenario
        from tests.e2e.runner import run_scenario

        sc = load_scenario(scenario)
        cfg = sc.app_config()
        safety.check_kill_switch(cfg.safety.kill_switch_file)
        safety.ensure_paper_trading(options.paper, options.live)
        if cfg.safety.require_confirm:
            safety.require_confirmation("Proceed with scenario execution?", options.yes)

        result = run_scenario(sc)

        typer.echo(f"Pre-trade CSV report written to {result.pre_report_csv}")
        typer.echo(f"Pre-trade Markdown report written to {result.pre_report_md}")
        typer.echo(f"Post-trade CSV report written to {result.post_report_csv}")
        typer.echo(f"Post-trade Markdown report written to {result.post_report_md}")
        typer.echo(f"Event log written to {result.event_log}")
        raise typer.Exit()

    # Store the options on the Typer context so subcommands can access them.
    ctx.obj = options


def _parse_cash(values: Iterable[str]) -> dict[str, float]:
    """Parse ``CCY=AMOUNT`` pairs supplied via ``--cash`` options."""

    cash: dict[str, float] = {}
    for item in values:
        if "=" not in item:
            raise typer.BadParameter("Cash must be specified as CUR=AMOUNT")
        cur, amt = item.split("=", 1)
        cash[cur.upper()] = float(amt)
    return cash


@app.command("pre-trade")
def pre_trade(
    ctx: typer.Context,
    config: Path = typer.Option(..., exists=True, readable=True, help="Path to INI config file"),
    portfolios: Path = typer.Option(
        ..., exists=True, readable=True, help="CSV describing model portfolios"
    ),
    positions: Path = typer.Option(
        ..., exists=True, readable=True, help="CSV of current positions"
    ),
    output_dir: Path | None = typer.Option(
        None, "--output-dir", "-o", help="Directory for generated reports"
    ),
    cash: list[str] = typer.Option(
        [],
        "--cash",
        "-c",
        help="Cash balance as CUR=AMOUNT, e.g. --cash USD=1000. Can be repeated.",
    ),
) -> None:
    """Generate a pre‑trade report using the supplied inputs."""

    # Access global CLI options for future routing to downstream components.
    options: CLIOptions = ctx.obj if isinstance(ctx.obj, CLIOptions) else CLIOptions()
    _ibkr_opts = IBKRProviderOptions(
        paper=options.paper, live=options.live, dry_run=options.dry_run
    )
    _exec_opts = OrderExecutionOptions(
        report_only=options.report_only, dry_run=options.dry_run, yes=options.yes
    )

    cfg = load_config(config)

    portfolios_data = load_portfolios(
        portfolios,
        allow_margin=cfg.rebalance.allow_margin,
        max_leverage=cfg.rebalance.max_leverage,
    )
    blend = blend_targets(portfolios_data, cfg.models)

    pos: dict[str, float] = {}
    prices: dict[str, float] = {}
    with positions.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            symbol = row["symbol"].strip().upper()
            pos[symbol] = float(row["quantity"])
            prices[symbol] = float(row["price"])

    cash_balances = _parse_cash(cash)

    snapshot = compute_account_state(
        pos, prices, cash_balances, cash_buffer_pct=cfg.rebalance.cash_buffer_pct
    )

    report_dir = output_dir or Path(cfg.io.report_dir)

    result = generate_pre_trade_report(
        blend.weights,
        snapshot.weights,
        prices,
        snapshot.total_equity,
        output_dir=report_dir,
        net_liq=snapshot.total_equity,
        cash_balances=snapshot.cash_by_currency,
        cash_buffer=(
            (snapshot.usd_cash * cfg.rebalance.cash_buffer_pct / 100.0)
            if cfg.rebalance.cash_buffer_pct
            else None
        ),
        min_order=cfg.rebalance.min_order_usd,
    )

    # ``generate_pre_trade_report`` returns either the DataFrame or a tuple
    # (df, csv_path, md_path) when output_dir is provided.
    if isinstance(result, tuple):
        df, csv_path, md_path = result
        typer.echo(df.to_string(index=False))
        typer.echo(f"CSV report written to {csv_path}")
        typer.echo(f"Markdown report written to {md_path}")
    else:  # pragma: no cover - defensive
        typer.echo(result.to_string(index=False))


if __name__ == "__main__":  # pragma: no cover
    app()
