"""Reporting helpers for pre and post trade summaries."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, TYPE_CHECKING

import pandas as pd

from .rebalance_engine import generate_orders
from .util import to_bps

if TYPE_CHECKING:  # pragma: no cover - imported for type checking only
    from .ibkr_provider import Fill


def _build_pre_trade_dataframe(
    targets: Mapping[str, float],
    current: Mapping[str, float],
    prices: Mapping[str, float],
    total_equity: float,
    **order_kwargs: Any,
) -> pd.DataFrame:
    """Internal helper to assemble the pre‑trade report dataframe.

    Additional keyword arguments are forwarded to
    :func:`rebalance_engine.generate_orders` allowing callers to tweak
    behaviour such as tolerance bands or minimum order size.
    """

    plan = generate_orders(targets, current, prices, total_equity, **order_kwargs)
    rows: list[dict[str, object]] = []
    symbols = sorted(set(targets) | set(current))
    for symbol in symbols:
        if symbol == "CASH":
            continue
        target = targets.get(symbol, 0.0)
        current_pct = current.get(symbol, 0.0)
        diff = target - current_pct
        price = prices[symbol]
        share_delta = plan.orders.get(symbol, 0.0)
        est_notional = share_delta * price
        dollar_delta = diff * total_equity
        side = "BUY" if share_delta > 0 else "SELL" if share_delta < 0 else ""
        rows.append(
            {
                "symbol": symbol,
                "target_pct": target * 100,
                "current_pct": current_pct * 100,
                "drift_bps": to_bps(diff),
                "price": price,
                "dollar_delta": dollar_delta,
                "share_delta": share_delta,
                "side": side,
                "est_notional": est_notional,
                "reason": plan.dropped.get(symbol, ""),
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df = df.reindex(df["drift_bps"].abs().sort_values(ascending=False).index).reset_index(drop=True)

    for col, digits in {
        "target_pct": 2,
        "current_pct": 2,
        "drift_bps": 2,
        "price": 2,
        "dollar_delta": 2,
        "share_delta": 4,
        "est_notional": 2,
    }.items():
        df[col] = df[col].round(digits)

    total = {
        "symbol": "TOTAL",
        "target_pct": round(df["target_pct"].sum(), 2),
        "current_pct": round(df["current_pct"].sum(), 2),
        "drift_bps": round(df["drift_bps"].sum(), 2),
        "price": pd.NA,
        "dollar_delta": round(df["dollar_delta"].sum(), 2),
        "share_delta": pd.NA,
        "side": "",
        "est_notional": round(df["est_notional"].sum(), 2),
        "reason": "",
    }
    df = pd.concat([df, pd.DataFrame([total])], ignore_index=True)

    return df


def _df_to_markdown(df: pd.DataFrame) -> str:
    """Render ``df`` as a simple GitHub‑flavoured Markdown table."""

    headers = list(df.columns)
    header_line = "| " + " | ".join(headers) + " |\n"
    separator = "| " + " | ".join(["---"] * len(headers)) + " |\n"
    lines = [header_line, separator]

    for _, row in df.iterrows():
        cells = []
        for col, val in row.items():
            if pd.isna(val):
                cells.append("")
            elif col in {
                "target_pct",
                "current_pct",
                "drift_bps",
                "price",
                "dollar_delta",
                "est_notional",
                "avg_price",
                "notional",
                "avg_slippage",
                "residual_drift_bps",
            }:
                cells.append(f"{val:.2f}")
            elif col in {"share_delta", "filled_shares"}:
                cells.append(f"{val:.4f}")
            else:
                cells.append(str(val))
        lines.append("| " + " | ".join(cells) + " |\n")

    return "".join(lines)


def generate_pre_trade_report(
    targets: Mapping[str, float],
    current: Mapping[str, float],
    prices: Mapping[str, float],
    total_equity: float,
    *,
    output_dir: Path | None = None,
    as_of: datetime | None = None,
    net_liq: float | None = None,
    cash_balances: Mapping[str, float] | None = None,
    cash_buffer: float | None = None,
    **order_kwargs: Any,
) -> pd.DataFrame | tuple[pd.DataFrame, Path, Path]:
    """Create the pre‑trade report and optionally persist it to ``output_dir``.

    Parameters
    ----------
    targets, current, prices, total_equity:
        Inputs as expected by :func:`rebalance_engine.generate_orders`.
    output_dir:
        When supplied, CSV and Markdown versions of the report are written to
        this directory using a timestamped filename.
    as_of:
        Timestamp used for naming the output files.  Defaults to ``datetime.now()``.
    net_liq, cash_balances, cash_buffer:
        Optional account summary details to prepend to the generated reports.
    **order_kwargs:
        Additional options passed through to
        :func:`rebalance_engine.generate_orders`.

    Returns
    -------
    pandas.DataFrame
        The report data.  When ``output_dir`` is provided the tuple ``(df,
        csv_path, md_path)`` is returned.
    """

    df = _build_pre_trade_dataframe(targets, current, prices, total_equity, **order_kwargs)

    if output_dir is not None:
        as_of = as_of or datetime.now()
        stamp = as_of.strftime("%Y%m%dT%H%M%S")
        output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = output_dir / f"pre_trade_report_{stamp}.csv"
        md_path = output_dir / f"pre_trade_report_{stamp}.md"

        summary_csv_lines: list[str] = []
        summary_md_lines: list[str] = []
        if net_liq is not None:
            summary_csv_lines.append(f"NetLiq,{net_liq:.2f}")
            summary_md_lines.append(f"NetLiq: {net_liq:.2f}")
        if cash_balances:
            for cur, amt in cash_balances.items():
                summary_csv_lines.append(f"Cash {cur},{amt:.2f}")
                summary_md_lines.append(f"Cash {cur}: {amt:.2f}")
        if cash_buffer is not None:
            summary_csv_lines.append(f"Cash Buffer,{cash_buffer:.2f}")
            summary_md_lines.append(f"Cash Buffer: {cash_buffer:.2f}")

        csv_content = "\n".join(summary_csv_lines)
        if csv_content:
            csv_content += "\n\n"
        csv_content += df.to_csv(index=False)
        csv_path.write_text(csv_content)

        md_content = "\n".join(summary_md_lines)
        if md_content:
            md_content += "\n\n"
        md_content += _df_to_markdown(df)
        md_path.write_text(md_content)
        return df, csv_path, md_path

    return df


def generate_post_trade_report(
    targets: Mapping[str, float],
    current: Mapping[str, float],
    prices: Mapping[str, float],
    total_equity: float,
    fills: Iterable[Fill],
    limit_prices: Mapping[str, float | None] | None = None,
    *,
    output_dir: Path | None = None,
    as_of: datetime | None = None,
) -> pd.DataFrame | tuple[pd.DataFrame, Path, Path]:
    """Summarise executed fills into a post‑trade report.

    Parameters
    ----------
    targets, current, prices, total_equity:
        Portfolio details used to compute residual drift after the fills.
    fills:
        Iterable of :class:`ibkr_provider.Fill` instances.
    limit_prices:
        Mapping of order IDs to limit prices used to compute slippage.
    output_dir:
        When provided, CSV and Markdown versions of the report are written to
        this directory using a timestamped filename.
    as_of:
        Timestamp used for naming the output files.  Defaults to
        ``datetime.now()``.

    Returns
    -------
    pandas.DataFrame
        The report data.  When ``output_dir`` is provided the tuple ``(df,
        csv_path, md_path)`` is returned.
    """

    from .ibkr_provider import OrderSide  # local import to avoid cycle

    limit_prices = limit_prices or {}
    agg: dict[str, dict[str, float]] = {}
    for fill in fills:
        symbol = fill.contract.symbol
        signed_qty = fill.quantity if fill.side == OrderSide.BUY else -fill.quantity
        notional = signed_qty * fill.price
        info = agg.setdefault(
            symbol,
            {"qty": 0.0, "notional": 0.0, "slip": 0.0, "volume": 0.0},
        )
        info["qty"] += signed_qty
        info["notional"] += notional
        limit = None
        if getattr(fill, "order_id", None) is not None:
            limit = limit_prices.get(fill.order_id)
        if limit is not None:
            side_mult = 1.0 if fill.side == OrderSide.BUY else -1.0
            per_share_slip = side_mult * (fill.price - limit)
            info["slip"] += per_share_slip * fill.quantity
            info["volume"] += fill.quantity

    rows: list[dict[str, object]] = []
    for symbol, info in agg.items():
        qty = info["qty"]
        notional = info["notional"]
        avg_price = notional / qty if qty else 0.0
        side = "BUY" if qty > 0 else "SELL" if qty < 0 else ""
        volume = info["volume"]
        avg_slip = info["slip"] / volume if volume else 0.0

        current_shares = current.get(symbol, 0.0) * total_equity / prices[symbol]
        residual_shares = current_shares + qty
        residual_pct = residual_shares * prices[symbol] / total_equity
        residual_drift = to_bps(targets.get(symbol, 0.0) - residual_pct)

        rows.append(
            {
                "symbol": symbol,
                "side": side,
                "filled_shares": qty,
                "avg_price": avg_price,
                "notional": notional,
                "avg_slippage": avg_slip,
                "residual_drift_bps": residual_drift,
            }
        )

    df = pd.DataFrame(rows)
    if not df.empty:
        for col, digits in {
            "filled_shares": 4,
            "avg_price": 2,
            "notional": 2,
            "avg_slippage": 2,
            "residual_drift_bps": 2,
        }.items():
            df[col] = df[col].round(digits)

    if output_dir is not None:
        as_of = as_of or datetime.now()
        stamp = as_of.strftime("%Y%m%dT%H%M%S")
        output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = output_dir / f"post_trade_report_{stamp}.csv"
        md_path = output_dir / f"post_trade_report_{stamp}.md"
        csv_path.write_text(df.to_csv(index=False))
        md_path.write_text(_df_to_markdown(df))
        return df, csv_path, md_path

    return df


__all__ = ["generate_pre_trade_report", "generate_post_trade_report"]
