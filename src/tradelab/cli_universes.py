"""`tradelab universes` — list/show named universes from tradelab.yaml."""
from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .config import get_config


universes_app = typer.Typer(help="List and inspect named symbol universes.")
console = Console()


@universes_app.command("list")
def list_cmd() -> None:
    """List all named universes and their sizes."""
    cfg = get_config()
    if not cfg.universes:
        console.print("[dim]No universes defined in tradelab.yaml.[/dim]")
        return
    t = Table(show_header=True, header_style="bold")
    t.add_column("Name", style="cyan")
    t.add_column("Size", justify="right")
    t.add_column("Symbols", style="dim")
    for name, syms in sorted(cfg.universes.items()):
        # Truncate symbol display so the table stays readable
        preview = ", ".join(syms[:6])
        if len(syms) > 6:
            preview += f", … (+{len(syms) - 6} more)"
        t.add_row(name, str(len(syms)), preview)
    console.print(t)


@universes_app.command("show")
def show_cmd(name: str = typer.Argument(..., help="Universe name")) -> None:
    """Print all symbols in one universe (one per line)."""
    cfg = get_config()
    if name not in cfg.universes:
        import difflib
        available = sorted(cfg.universes.keys())
        close = difflib.get_close_matches(name, available, n=3, cutoff=0.5)
        if close:
            console.print(f"[red]Not found.[/red] Did you mean: {', '.join(close)}?")
        else:
            console.print(f"[red]Universe {name!r} not in tradelab.yaml.[/red]")
            console.print(f"Available: {', '.join(available) or '(none)'}")
        raise typer.Exit(1)
    for sym in cfg.universes[name]:
        console.print(sym)
