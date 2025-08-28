"""Typer based command line interface."""

from __future__ import annotations

import typer


app = typer.Typer()


@app.callback()
def main() -> None:
    """Top level CLI entry point."""


@app.command()
def pre_trade() -> None:
    """Placeholder command for generating a pre-trade report."""


__all__ = ["app", "main", "pre_trade"]
