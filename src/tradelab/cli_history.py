"""`tradelab history` subcommand — list / show / diff historical runs."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .audit import diff_runs, get_run, list_runs


history_app = typer.Typer(help="Query the append-only tradelab run history.")
console = Console()


@history_app.command("list")
def list_cmd(
    strategy: Optional[str] = typer.Option(None, help="Filter to one strategy"),
    since: Optional[str] = typer.Option(None, help="ISO date, e.g. 2026-04-01"),
    limit: int = typer.Option(25, help="Max rows"),
) -> None:
    """List recent runs (newest first)."""
    runs = list_runs(strategy=strategy, since=since, limit=limit)
    if not runs:
        console.print("[dim]No runs recorded yet.[/dim]")
        return
    t = Table(show_header=True, header_style="bold")
    t.add_column("run_id", style="cyan", no_wrap=True)
    t.add_column("timestamp", no_wrap=True)
    t.add_column("strategy", style="magenta")
    t.add_column("verdict")
    t.add_column("DSR", justify="right")
    for r in runs:
        dsr = f"{r.dsr_probability:.3f}" if r.dsr_probability is not None else "-"
        verdict_color = {
            "ROBUST": "green", "INCONCLUSIVE": "yellow",
            "FRAGILE": "red", "UNDEFINED": "dim",
        }.get((r.verdict or "").upper(), "white")
        verdict_cell = f"[{verdict_color}]{r.verdict or '-'}[/{verdict_color}]"
        t.add_row(r.run_id[:8], r.timestamp_utc[:19], r.strategy_name, verdict_cell, dsr)
    console.print(t)


@history_app.command("show")
def show_cmd(run_id: str = typer.Argument(..., help="Full or short (8-char) run_id")) -> None:
    """Print the full report markdown for one run."""
    # Short-id resolution
    if len(run_id) < 36:
        matches = [r for r in list_runs(limit=10_000) if r.run_id.startswith(run_id)]
        if not matches:
            console.print(f"[red]No run matches {run_id!r}[/red]")
            raise typer.Exit(1)
        if len(matches) > 1:
            console.print(f"[yellow]Ambiguous short id {run_id!r}; {len(matches)} matches[/yellow]")
            raise typer.Exit(1)
        run = matches[0]
    else:
        run = get_run(run_id)
        if run is None:
            console.print(f"[red]No run {run_id!r}[/red]")
            raise typer.Exit(1)

    console.print(f"[dim]run_id:   {run.run_id}[/dim]")
    console.print(f"[dim]time:     {run.timestamp_utc}[/dim]")
    console.print(f"[dim]strategy: {run.strategy_name}[/dim]")
    console.print(f"[dim]verdict:  {run.verdict}[/dim]")
    console.print(f"[dim]DSR:      {run.dsr_probability}[/dim]")
    if run.report_card_html_path:
        console.print(f"[dim]dashboard: {run.report_card_html_path}[/dim]")
    console.print()
    console.print(run.report_card_markdown or "[dim](no markdown)[/dim]")


@history_app.command("diff")
def diff_cmd(
    run_id_a: str = typer.Argument(..., help="Older run"),
    run_id_b: str = typer.Argument(..., help="Newer run"),
) -> None:
    """Unified diff between two runs' report markdown."""

    def _resolve(short_or_full: str) -> str:
        if len(short_or_full) >= 36:
            return short_or_full
        matches = [r for r in list_runs(limit=10_000) if r.run_id.startswith(short_or_full)]
        if not matches:
            console.print(f"[red]No match for {short_or_full!r}[/red]")
            raise typer.Exit(1)
        if len(matches) > 1:
            console.print(f"[yellow]Ambiguous {short_or_full!r}[/yellow]")
            raise typer.Exit(1)
        return matches[0].run_id

    a = _resolve(run_id_a)
    b = _resolve(run_id_b)
    console.print(diff_runs(a, b))
