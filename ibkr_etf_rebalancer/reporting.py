"""Reporting helpers for pre and post trade summaries."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping

import pandas as pd

from .rebalance_engine import generate_orders


def _build_pre_trade_dataframe(
    targets: Mapping[str, float],
    current: Mapping[str, float],
    prices: Mapping[str, float],
    total_equity: float,
) -> pd.DataFrame:
    """Internal helper to assemble the pre‑trade report dataframe."""

    orders = generate_orders(targets, current, prices, total_equity)
    rows: list[dict[str, object]] = []
    symbols = sorted(set(targets) | set(current))
    for symbol in symbols:
        if symbol == "CASH":
            continue
        target = targets.get(symbol, 0.0)
        current_pct = current.get(symbol, 0.0)
        diff = target - current_pct
        price = prices[symbol]
        share_delta = orders.get(symbol, 0.0)
        est_notional = share_delta * price
        dollar_delta = diff * total_equity
        side = "BUY" if share_delta > 0 else "SELL" if share_delta < 0 else ""
        rows.append(
            {
                "symbol": symbol,
                "target_pct": target * 100,
                "current_pct": current_pct * 100,
                "drift_bps": diff * 10_000,
                "price": price,
                "dollar_delta": dollar_delta,
                "share_delta": share_delta,
                "side": side,
                "est_notional": est_notional,
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
            elif col in {"target_pct", "current_pct", "drift_bps", "price", "dollar_delta", "est_notional"}:
                cells.append(f"{val:.2f}")
            elif col == "share_delta":
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
):
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

    Returns
    -------
    pandas.DataFrame
        The report data.  When ``output_dir`` is provided the tuple ``(df,
        csv_path, md_path)`` is returned.
    """

    df = _build_pre_trade_dataframe(targets, current, prices, total_equity)

    if output_dir is not None:
        as_of = as_of or datetime.now()
        stamp = as_of.strftime("%Y%m%dT%H%M%S")
        output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = output_dir / f"pre_trade_report_{stamp}.csv"
        md_path = output_dir / f"pre_trade_report_{stamp}.md"
        df.to_csv(csv_path, index=False)
        md_path.write_text(_df_to_markdown(df))
        return df, csv_path, md_path

    return df


def generate_post_trade_report(executions: Iterable[Mapping[str, float]]) -> pd.DataFrame:
    """Summarise filled orders into a post‑trade report dataframe.

    Each execution mapping should provide ``symbol``, ``side``,
    ``filled_shares`` and ``avg_price``.  Additional fields may be added in
    the future.
    """

    rows: list[dict[str, object]] = []
    for exe in executions:
        filled = exe.get("filled_shares", 0.0)
        price = exe.get("avg_price", 0.0)
        notional = filled * price
        rows.append(
            {
                "symbol": exe.get("symbol"),
                "side": exe.get("side", ""),
                "filled_shares": filled,
                "avg_price": price,
                "notional": notional,
            }
        )
    return pd.DataFrame(rows)


__all__ = ["generate_pre_trade_report", "generate_post_trade_report"]

