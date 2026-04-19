"""`tradelab leak-check` — three-layer look-ahead bias detector."""
from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .engines.leak_check import run_leak_check
from .registry import StrategyNotRegistered, instantiate_strategy


console = Console()


def leak_check(
    strategy: str = typer.Argument(..., help="Strategy name (from registry)"),
    symbols: str = typer.Option("", help="Comma list, @file.txt, or empty (static-only)"),
    universe: str = typer.Option("", help="Named universe from tradelab.yaml"),
    start: str = typer.Option("2022-01-01"),
    end: str = typer.Option(""),
    static_only: bool = typer.Option(False, "--static-only/--with-dynamic",
                                       help="Skip the dynamic shift backtest"),
    allow_yfinance_fallback: bool = typer.Option(False, "--allow-yfinance-fallback"),
) -> None:
    """
    Static + dynamic look-ahead bias detection.

    Static layer: scan strategy source for .shift(-N) and other suspicious
    patterns. Dynamic layer: re-run with buy_signal shifted +1 bar; flag
    fragile if PF drops > 50%, suspect if > 25%.
    """
    try:
        strat = instantiate_strategy(strategy)
    except StrategyNotRegistered as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(2)

    ticker_data = None
    if not static_only:
        # Resolve universe
        from pathlib import Path
        from datetime import datetime
        from .config import get_config
        from .marketdata import (
            MissingTwelveDataKey, assert_pit_valid,
            download_symbols, enrich_universe,
        )

        if universe:
            try:
                cfg = get_config()
                if universe not in cfg.universes:
                    console.print(f"[red]Universe {universe!r} not in tradelab.yaml.[/red]")
                    raise typer.Exit(2)
                symbol_list = list(cfg.universes[universe])
            except Exception as e:
                console.print(f"[red]Cannot resolve --universe: {e}[/red]")
                raise typer.Exit(2)
        elif symbols.startswith("@"):
            p = Path(symbols[1:])
            symbol_list = [s.strip() for s in p.read_text().splitlines() if s.strip()]
        elif symbols:
            symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
        else:
            console.print("[yellow]No symbols provided — running static check only.[/yellow]")
            symbol_list = []

        if symbol_list:
            if not end:
                end = datetime.now().strftime("%Y-%m-%d")
            console.print(f"[dim]Downloading {len(symbol_list)} symbols ...[/dim]")
            try:
                data = download_symbols(symbol_list, start=start, end=end,
                                         allow_yfinance_fallback=allow_yfinance_fallback)
            except MissingTwelveDataKey as e:
                console.print(f"[red]{e}[/red]")
                raise typer.Exit(4)
            try:
                assert_pit_valid(data, start=start)
            except Exception as e:
                console.print(f"[yellow]PIT warning: {e}[/yellow]")
            ticker_data = enrich_universe(data, benchmark="SPY")

    spy_close = None
    if ticker_data and "SPY" in ticker_data:
        spy_close = ticker_data["SPY"].set_index("Date")["Close"]

    console.print(f"\n[bold]Leak check — {strategy}[/bold]\n")
    res = run_leak_check(strat, ticker_data,
                          spy_close=spy_close, start=start, end=end)

    # Static section
    console.print(f"[bold]Static scan[/bold] ({res.static.file_path})")
    if res.static.n_findings == 0:
        console.print("  [green]OK[/green] — no suspicious patterns found")
    else:
        console.print(f"  [yellow]{res.static.n_findings} suspicious line(s):[/yellow]")
        for f in res.static.findings:
            console.print(f"    L{f.line_no}: [dim]{f.note}[/dim]")
            console.print(f"      [cyan]{f.line.strip()}[/cyan]")

    # Dynamic section
    if res.dynamic:
        d = res.dynamic
        flag_color = {"ok": "green", "suspect": "yellow", "fragile": "red"}[d.flag]
        console.print(f"\n[bold]Dynamic shift test[/bold]")
        t = Table(show_header=False, box=None)
        t.add_column("", style="dim")
        t.add_column("", justify="right")
        t.add_row("Baseline PF (no shift)", f"{d.baseline_pf:.3f}")
        t.add_row("Shifted PF (+1 bar)", f"{d.shifted_pf:.3f}")
        t.add_row("PF drop", f"{d.pf_drop_pct:.1f}%")
        t.add_row("Baseline net P&L", f"${d.baseline_pnl:,.0f}")
        t.add_row("Shifted net P&L", f"${d.shifted_pnl:,.0f}")
        t.add_row("Suspected leakage P&L", f"${d.leakage_pnl_estimate:,.0f}")
        t.add_row("Flag", f"[{flag_color}]{d.flag}[/{flag_color}]")
        console.print(t)
    elif not static_only:
        console.print("\n[dim]Dynamic test skipped (no symbols).[/dim]")

    # Overall verdict
    overall_color = {"ok": "green", "suspect": "yellow", "fragile": "red"}[res.overall_flag]
    console.print(f"\n[bold]Overall: [{overall_color}]{res.overall_flag.upper()}[/{overall_color}][/bold]\n")

    if res.overall_flag == "fragile":
        raise typer.Exit(1)
