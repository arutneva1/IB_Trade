from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

from ibkr_etf_rebalancer.account_state import AccountSnapshot, compute_account_state
from ibkr_etf_rebalancer.config import AppConfig
from ibkr_etf_rebalancer.ibkr_provider import (
    AccountValue,
    Contract,
    FakeIB,
    Order,
    OrderSide,
    Position,
)
from ibkr_etf_rebalancer.order_builder import build_fx_order, build_orders
from ibkr_etf_rebalancer.order_executor import OrderExecutionOptions, OrderExecutionResult, execute_orders
from ibkr_etf_rebalancer.pricing import FakeQuoteProvider, Quote
from ibkr_etf_rebalancer.rebalance_engine import FxPlan, OrderPlan, plan_rebalance_with_fx
from ibkr_etf_rebalancer.reporting import generate_post_trade_report, generate_pre_trade_report
from ibkr_etf_rebalancer.target_blender import BlendResult, blend_targets
from ibkr_etf_rebalancer.util import from_bps

from .scenario import Scenario


@dataclass
class ScenarioRunResult:
    """Return information produced by :func:`run_scenario`."""

    blend: BlendResult
    snapshot: AccountSnapshot
    plan: OrderPlan
    fx_plan: FxPlan
    execution: OrderExecutionResult
    pre_report_csv: Path
    pre_report_md: Path
    post_report_csv: Path
    post_report_md: Path
    event_log: Path


# ---------------------------------------------------------------------------

def run_scenario(scenario: Scenario) -> ScenarioRunResult:
    """Execute *scenario* end-to-end using fakes only.

    The function performs the following high level steps:

    * Instantiate :class:`FakeQuoteProvider` and :class:`FakeIB` using scenario
      data.
    * Blend model portfolios into final targets.
    * Compute the current account snapshot.
    * Plan the rebalance including any FX conversion.
    * Build and execute the resulting orders.
    * Generate pre and post trade reports.
    * Persist the broker event log.
    """

    def _run(cfg: AppConfig) -> ScenarioRunResult:
        as_of = scenario.as_of
        stamp = as_of.strftime("%Y%m%dT%H%M%S")
        output_dir = Path(cfg.io.report_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # ------------------------------------------------------------------
        # Quote and contract setup
        quotes: Dict[str, Quote] = {
            sym: Quote(bid=q.bid, ask=q.ask, ts=as_of, last=scenario.prices.get(sym))
            for sym, q in scenario.quotes.items()
        }
        quote_provider = FakeQuoteProvider(quotes)

        contracts: Dict[str, Contract] = {}
        ib_quotes: Dict[str, Quote] = {}
        for sym, q in quotes.items():
            if "." in sym:
                base, ccy = sym.split(".", 1)
                contract = Contract(symbol=base, sec_type="CASH", currency=ccy, exchange="IDEALPRO")
                ib_symbol = base
            else:
                contract = Contract(symbol=sym)
                ib_symbol = sym
            contracts[ib_symbol] = contract
            ib_quotes[ib_symbol] = q

        positions = [
            Position(
                account=cfg.ibkr.account,
                contract=contracts.setdefault(sym, Contract(symbol=sym)),
                quantity=qty,
                avg_price=scenario.prices[sym],
            )
            for sym, qty in scenario.positions.items()
        ]
        net_liq = sum(
            qty * scenario.prices[sym] for sym, qty in scenario.positions.items()
        ) + sum(scenario.cash.values())
        account_values = [AccountValue(tag="NetLiquidation", value=net_liq, currency="USD")]
        ib = FakeIB(contracts=contracts, quotes=ib_quotes, account_values=account_values, positions=positions)

        # ------------------------------------------------------------------
        # Targets: derive trivial portfolios from current holdings for now
        total_val = sum(qty * scenario.prices[sym] for sym, qty in scenario.positions.items())
        weights: Dict[str, float] = {}
        if total_val > 0:
            weights = {
                sym: qty * scenario.prices[sym] / total_val
                for sym, qty in scenario.positions.items()
            }
        portfolios = {"SMURF": weights, "BADASS": weights, "GLTR": weights}
        blend = blend_targets(portfolios, cfg.models)

        # ------------------------------------------------------------------
        snapshot = compute_account_state(
            scenario.positions,
            scenario.prices,
            scenario.cash,
            cash_buffer_pct=cfg.rebalance.cash_buffer_pct,
        )

        pre_df, pre_csv, pre_md = generate_pre_trade_report(
            blend.weights,
            snapshot.weights,
            scenario.prices,
            snapshot.total_equity,
            output_dir=output_dir,
            as_of=as_of,
            net_liq=snapshot.total_equity,
            cash_balances=snapshot.cash_by_currency,
            cash_buffer=(
                snapshot.usd_cash * cfg.rebalance.cash_buffer_pct / 100.0
                if cfg.rebalance.cash_buffer_pct
                else None
            ),
            min_order=cfg.rebalance.min_order_usd,
        )

        # ------------------------------------------------------------------
        plan, fx_plan = plan_rebalance_with_fx(
            blend.weights,
            snapshot.weights,
            scenario.prices,
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

        order_quotes = {sym: quote_provider.get_quote(sym) for sym in plan.orders}
        orders = build_orders(
            plan.orders,
            order_quotes,
            cfg.rebalance,
            contracts,
            allow_fractional=cfg.rebalance.allow_fractional,
            allow_margin=cfg.rebalance.allow_margin,
            prefer_rth=cfg.rebalance.prefer_rth,
        )
        sell_orders = [o for o in orders if o.side is OrderSide.SELL]
        buy_orders = [o for o in orders if o.side is OrderSide.BUY]
        fx_orders: list[Order] = []
        if fx_plan.need_fx:
            fx_symbol = fx_plan.pair.split(".", 1)[0]
            fx_orders = [
                build_fx_order(fx_plan, contracts[fx_symbol], prefer_rth=cfg.rebalance.prefer_rth)
            ]

        execution = execute_orders(
            ib,
            fx_orders=fx_orders,
            sell_orders=sell_orders,
            buy_orders=buy_orders,
            fx_plan=fx_plan,
            options=OrderExecutionOptions(yes=True),
            max_leverage=cfg.rebalance.max_leverage,
            allow_margin=cfg.rebalance.allow_margin,
        )

        post_df, post_csv, post_md = generate_post_trade_report(
            blend.weights,
            snapshot.weights,
            scenario.prices,
            snapshot.total_equity,
            execution.fills,
            output_dir=output_dir,
            as_of=as_of,
        )

        event_log_path = output_dir / f"event_log_{stamp}.json"
        event_log_path.write_text(json.dumps(list(ib.event_log), default=str, indent=2))

        return ScenarioRunResult(
            blend=blend,
            snapshot=snapshot,
            plan=plan,
            fx_plan=fx_plan,
            execution=execution,
            pre_report_csv=pre_csv,
            pre_report_md=pre_md,
            post_report_csv=post_csv,
            post_report_md=post_md,
            event_log=event_log_path,
        )

    return scenario.execute(_run)
