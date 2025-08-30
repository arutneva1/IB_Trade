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
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable, Any, Mapping, cast

import typer

from . import safety
from .account_state import compute_account_state
from .config import load_config
from .ibkr_provider import (
    IBKRProvider,
    IBKRProviderOptions,
    FakeIB,
    Contract,
    OrderSide,
)
from .order_builder import build_fx_order, build_orders
from .order_executor import OrderExecutionOptions, OrderExecutionResult, execute_orders
from .portfolio_loader import load_portfolios
from .pricing import IBKRQuoteProvider
from .rebalance_engine import plan_rebalance_with_fx
from .reporting import generate_post_trade_report, generate_pre_trade_report
from .target_blender import blend_targets
from .util import from_bps


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
        from ibkr_etf_rebalancer.scenario import load_scenario
        from .scenario_runner import run_scenario

        sc = load_scenario(scenario)
        cfg = sc.app_config()
        safety.check_kill_switch(cfg.safety.kill_switch_file)
        # Scenarios always run in paper mode using fake providers and should
        # never attempt a real broker connection. Ignore any user supplied
        # ``--live`` or ``--no-paper`` flags and force paper trading.
        safety.ensure_paper_trading(paper=True, live=False)
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


def _connect_ibkr(options: IBKRProviderOptions) -> IBKRProvider:
    """Return a connected :class:`IBKRProvider` instance.

    The default implementation uses :class:`FakeIB` which is sufficient for
    tests.  This helper is intentionally tiny so tests can monkeypatch it to
    provide a preconfigured provider.
    """

    ib = FakeIB(options=options)
    ib.connect()
    return cast(IBKRProvider, ib)


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

    cfg = load_config(config)

    _exec_opts = OrderExecutionOptions(
        report_only=options.report_only,
        dry_run=options.dry_run,
        yes=options.yes,
        require_confirm=cfg.safety.require_confirm,
    )

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


@app.command("rebalance")
def rebalance(
    ctx: typer.Context,
    config: Path = typer.Option(..., exists=True, readable=True, help="Path to INI config file"),
    portfolios: Path = typer.Option(
        ..., exists=True, readable=True, help="CSV describing model portfolios"
    ),
    output_dir: Path | None = typer.Option(
        None, "--output-dir", "-o", help="Directory for generated reports"
    ),
) -> None:
    """Execute a full rebalance against the configured broker."""

    options: CLIOptions = ctx.obj if isinstance(ctx.obj, CLIOptions) else CLIOptions()
    cfg = load_config(config)

    safety.check_kill_switch(cfg.safety.kill_switch_file)
    safety.ensure_paper_trading(options.paper, options.live)
    if cfg.safety.require_confirm:
        safety.require_confirmation("Proceed with rebalancing?", options.yes)

    ib_options = IBKRProviderOptions(
        paper=options.paper,
        live=options.live,
        dry_run=options.dry_run,
        kill_switch=cfg.safety.kill_switch_file,
    )
    ib = _connect_ibkr(ib_options)
    quote_provider = IBKRQuoteProvider(ib)

    portfolios_data = load_portfolios(
        portfolios,
        allow_margin=cfg.rebalance.allow_margin,
        max_leverage=cfg.rebalance.max_leverage,
    )
    blend = blend_targets(portfolios_data, cfg.models)

    positions: Mapping[str, float] = {
        p.contract.symbol: p.quantity for p in ib.get_positions() if p.quantity != 0
    }
    symbols = set(blend.weights) | set(positions)
    prices = {
        sym: quote_provider.get_price(sym, cfg.pricing.price_source, cfg.pricing.fallback_to_snapshot)
        for sym in symbols
    }
    cash_balances = {
        av.currency: av.value
        for av in ib.get_account_values()
        if av.tag == "CashBalance" and av.currency
    }
    snapshot = compute_account_state(
        positions,
        prices,
        cash_balances,
        cash_buffer_pct=cfg.rebalance.cash_buffer_pct,
    )

    report_dir = output_dir or Path(cfg.io.report_dir)
    as_of = datetime.now(timezone.utc)
    pre_df, pre_csv, pre_md = cast(
        tuple[Any, Path, Path],
        generate_pre_trade_report(
            blend.weights,
            snapshot.weights,
            prices,
            snapshot.total_equity,
            output_dir=report_dir,
            as_of=as_of,
            net_liq=snapshot.total_equity,
            cash_balances=snapshot.cash_by_currency,
            cash_buffer=(
                snapshot.usd_cash * cfg.rebalance.cash_buffer_pct / 100.0
                if cfg.rebalance.cash_buffer_pct
                else None
            ),
            min_order=cfg.rebalance.min_order_usd,
        ),
    )

    plan, fx_plan = plan_rebalance_with_fx(
        blend.weights,
        snapshot.weights,
        prices,
        snapshot.total_equity,
        fx_cfg=cfg.fx,
        quote_provider=quote_provider,
        pricing_cfg=cfg.pricing,
        funding_cash=snapshot.cash_by_currency.get("CAD", 0.0),
        bands=from_bps(cfg.rebalance.per_holding_band_bps),
        min_order=cfg.rebalance.min_order_usd,
        max_leverage=cfg.rebalance.max_leverage,
        cash_buffer_pct=cfg.rebalance.cash_buffer_pct,
        maintenance_buffer_pct=cfg.rebalance.maintenance_buffer_pct,
        allow_fractional=cfg.rebalance.allow_fractional,
        trigger_mode=cfg.rebalance.trigger_mode,
        portfolio_total_band_bps=cfg.rebalance.portfolio_total_band_bps,
        allow_margin=cfg.rebalance.allow_margin,
    )

    if fx_plan.need_fx:
        prices[fx_plan.pair.split(".")[0]] = fx_plan.est_rate

    order_quotes = {sym: quote_provider.get_quote(sym) for sym in plan.orders}
    contracts = {sym: ib.resolve_contract(Contract(symbol=sym)) for sym in plan.orders}
    order_cfg = SimpleNamespace(**cfg.rebalance.model_dump(), limits=cfg.limits)
    orders = build_orders(
        plan.orders,
        order_quotes,
        order_cfg,
        contracts,
        allow_fractional=cfg.rebalance.allow_fractional,
        allow_margin=cfg.rebalance.allow_margin,
        prefer_rth=cfg.rebalance.prefer_rth,
    )
    sell_orders = [o for o in orders if o.side is OrderSide.SELL]
    buy_orders = [o for o in orders if o.side is OrderSide.BUY]
    fx_orders = []
    if fx_plan.need_fx:
        fx_sym, fx_cur = fx_plan.pair.split(".", 1)
        fx_contract = ib.resolve_contract(
            Contract(symbol=fx_sym, sec_type="CASH", currency=fx_cur, exchange=fx_plan.route)
        )
        fx_orders = [build_fx_order(fx_plan, fx_contract, prefer_rth=cfg.rebalance.prefer_rth)]

    execution = execute_orders(
        ib,
        fx_orders=fx_orders,
        sell_orders=sell_orders,
        buy_orders=buy_orders,
        fx_plan=fx_plan,
        options=OrderExecutionOptions(
            report_only=options.report_only,
            dry_run=options.dry_run,
            yes=options.yes,
            require_confirm=cfg.safety.require_confirm,
            prefer_rth=cfg.rebalance.prefer_rth,
        ),
        max_leverage=cfg.rebalance.max_leverage,
        allow_margin=cfg.rebalance.allow_margin,
    )
    fills: list[Any]
    limit_prices: Mapping[str, float | None]
    if isinstance(execution, OrderExecutionResult):
        fills = execution.fills
        limit_prices = execution.limit_prices
    else:
        fills = []
        limit_prices = {}

    post_df, post_csv, post_md = cast(
        tuple[Any, Path, Path],
        generate_post_trade_report(
            blend.weights,
            snapshot.weights,
            prices,
            snapshot.total_equity,
            fills,
            limit_prices,
            output_dir=report_dir,
            as_of=as_of,
        ),
    )

    event_log_path = report_dir / f"event_log_{as_of.strftime('%Y%m%dT%H%M%S')}.json"
    event_log_path.write_text(json.dumps(list(ib.event_log), default=str, indent=2))

    typer.echo(f"Pre-trade CSV report written to {pre_csv}")
    typer.echo(f"Pre-trade Markdown report written to {pre_md}")
    typer.echo(f"Post-trade CSV report written to {post_csv}")
    typer.echo(f"Post-trade Markdown report written to {post_md}")
    typer.echo(f"Event log written to {event_log_path}")


if __name__ == "__main__":  # pragma: no cover
    app()
