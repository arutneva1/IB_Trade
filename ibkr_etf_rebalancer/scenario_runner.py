from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, cast
from types import SimpleNamespace

from .account_state import AccountSnapshot, compute_account_state
from .config import AppConfig
from . import safety
from .errors import SafetyError
from .ibkr_provider import (
    AccountValue,
    Contract,
    FakeIB,
    IBKRProvider,
    IBKRProviderOptions,
    Order,
    OrderSide,
    Position,
)
from .order_builder import build_fx_order, build_orders
from .order_executor import (
    OrderExecutionOptions,
    OrderExecutionResult,
    execute_orders,
)
from .pricing import FakeQuoteProvider, Quote
from .rebalance_engine import FxPlan, OrderPlan, plan_rebalance_with_fx
from .reporting import generate_post_trade_report, generate_pre_trade_report
from .scenario import Scenario
from .target_blender import BlendResult, blend_targets
from .util import from_bps


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

    with scenario.frozen_time():
        cfg: AppConfig = scenario.app_config()
        as_of = scenario.as_of
        stamp = as_of.strftime("%Y%m%dT%H%M%S")
        output_dir = Path(cfg.io.report_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # ------------------------------------------------------------------
        # Quote and contract setup
        quotes: Dict[str, Quote] = {
            sym: Quote(bid=q.bid, ask=q.ask, ts=as_of) for sym, q in scenario.quotes.items()
        }
        quote_provider = FakeQuoteProvider(quotes, snapshots=scenario.prices)

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

        # Discard zero-quantity holdings to appease downstream validation logic
        non_zero_positions = {s: q for s, q in scenario.positions.items() if q != 0}
        positions = [
            Position(
                account=cfg.ibkr.account,
                contract=contracts.setdefault(sym, Contract(symbol=sym)),
                quantity=qty,
                avg_price=scenario.prices[sym],
            )
            for sym, qty in non_zero_positions.items()
        ]
        net_liq = sum(qty * scenario.prices[sym] for sym, qty in non_zero_positions.items()) + sum(
            scenario.cash.values()
        )
        account_values = [AccountValue(tag="NetLiquidation", value=net_liq, currency="USD")]
        fake_ib_cfg = scenario.config_overrides.get("fake_ib", {})
        ib = FakeIB(
            options=IBKRProviderOptions(
                allow_market_orders=True, kill_switch=cfg.safety.kill_switch_file
            ),
            contracts=contracts,
            quotes=ib_quotes,
            account_values=account_values,
            positions=positions,
            concurrency_limit=fake_ib_cfg.get("concurrency_limit"),
            fill_fractions=fake_ib_cfg.get("fill_fractions"),
        )

        # ------------------------------------------------------------------
        # Targets: use provided target weights or portfolios if available
        if scenario.target_weights is not None:
            total = sum(scenario.target_weights.values())
            norm = {k: v / total for k, v in scenario.target_weights.items()} if total > 0 else {}
            ordered = OrderedDict(sorted(norm.items()))
            gross = sum(w for s, w in ordered.items() if s != "CASH")
            net = gross + ordered.get("CASH", 0.0)
            blend = BlendResult(weights=ordered, gross_exposure=gross, net_exposure=net)
        else:
            if scenario.portfolios is not None:
                portfolios = scenario.portfolios
            else:
                total_val = sum(
                    qty * scenario.prices[sym] for sym, qty in non_zero_positions.items()
                )
                weights: Dict[str, float] = {}
                if total_val > 0:
                    weights = {
                        sym: qty * scenario.prices[sym] / total_val
                        for sym, qty in non_zero_positions.items()
                    }
                else:
                    # When the portfolio has no holdings, assume equal weights for any
                    # quoted equities so that downstream blending logic still has
                    # non-zero exposure to work with. FX pairs are ignored here.
                    equity_syms = [s for s in scenario.prices if "." not in s]
                    if equity_syms:
                        w = 1.0 / len(equity_syms)
                        weights = {s: w for s in equity_syms}
                portfolios = {"SMURF": weights, "BADASS": weights, "GLTR": weights}
            blend = blend_targets(portfolios, cfg.models)

        # ------------------------------------------------------------------
        cash_balances = dict(scenario.cash)
        if (
            cash_balances.get("USD", 0) <= 0
            and "CAD" in cash_balances
            and "USD.CAD" in scenario.prices
        ):
            rate = scenario.prices["USD.CAD"]
            if rate > 0:
                cash_balances["USD"] = cash_balances["CAD"] / rate
        snapshot = compute_account_state(
            non_zero_positions,
            scenario.prices,
            cash_balances,
            cash_buffer_pct=cfg.rebalance.cash_buffer_pct,
        )

        pre_df, pre_csv, pre_md = cast(
            tuple[Any, Path, Path],
            generate_pre_trade_report(
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
            ),
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
        fx_orders: list[Order] = []
        if fx_plan.need_fx:
            fx_symbol = fx_plan.pair.split(".", 1)[0]
            fx_orders = [
                build_fx_order(fx_plan, contracts[fx_symbol], prefer_rth=cfg.rebalance.prefer_rth)
            ]

        try:
            safety.check_kill_switch(cfg.safety.kill_switch_file)
        except SafetyError:
            execution = OrderExecutionResult(fills=[], canceled=[])
        else:
            exec_cfg = scenario.config_overrides.get("execution", {})
            execution = cast(
                OrderExecutionResult,
                execute_orders(
                    cast(IBKRProvider, ib),
                    fx_orders=fx_orders,
                    sell_orders=sell_orders,
                    buy_orders=buy_orders,
                    fx_plan=fx_plan,
                    options=OrderExecutionOptions(
                        yes=True,
                        concurrency_cap=exec_cfg.get("concurrency_cap"),
                        timeout=exec_cfg.get("timeout_seconds"),
                        require_confirm=cfg.safety.require_confirm,
                    ),
                    max_leverage=cfg.rebalance.max_leverage,
                    allow_margin=cfg.rebalance.allow_margin,
                ),
            )

        post_df, post_csv, post_md = cast(
            tuple[Any, Path, Path],
            generate_post_trade_report(
                blend.weights,
                snapshot.weights,
                scenario.prices,
                snapshot.total_equity,
                execution.fills,
                execution.limit_prices,
                output_dir=output_dir,
                as_of=as_of,
            ),
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
