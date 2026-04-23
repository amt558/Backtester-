"""`tradelab gate-check` — Pearson correlation between indicator gates.

Quick example:
    tradelab gate-check --symbols NVDA,AVGO,MU \
        --gates adr_pct_20d,relative_volume_20d,sigma_spike,minervini_template

Output: a table showing per-pair correlation, overlap % (for boolean gates),
and a recommendation. Redundant gates (|r|>0.7) are flagged red.
"""
from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from .engines.gate_check import check_gate_independence

console = Console()


def gate_check(
    symbols: str = typer.Option(
        "NVDA,AVGO,MSFT,AAPL,META", "--symbols",
        help="Comma-separated ticker symbols to sample gate data from.",
    ),
    gates: str = typer.Option(
        ..., "--gates",
        help="Comma-separated indicator gate names "
             "(e.g. adr_pct_20d,relative_volume_20d,sigma_spike,minervini_template).",
    ),
    benchmark: str = typer.Option("SPY", "--benchmark", help="Benchmark symbol for RS-based gates."),
):
    """Test whether a strategy's indicator gates are independent or redundant.

    Redundant gates (|r|>0.7) add no information. Strategies combining them are
    effectively double-counting one signal.
    """
    sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
    gate_list = [g.strip() for g in gates.split(",") if g.strip()]

    if len(gate_list) < 2:
        console.print("[red]gate-check requires at least 2 gates[/red]")
        raise typer.Exit(2)

    console.print(f"[dim]symbols: {', '.join(sym_list)}[/dim]")
    console.print(f"[dim]gates:   {', '.join(gate_list)}[/dim]")
    console.print()

    try:
        results = check_gate_independence(sym_list, gate_list, benchmark=benchmark)
    except Exception as e:
        console.print(f"[red]gate-check failed:[/red] {e}")
        raise typer.Exit(1)

    t = Table(show_header=True, header_style="bold", title="Gate pairwise correlations")
    t.add_column("Gate A")
    t.add_column("Gate B")
    t.add_column("Pearson r", justify="right")
    t.add_column("Overlap %", justify="right")
    t.add_column("N", justify="right")
    t.add_column("Verdict")

    for r in results:
        corr_s = "n/a" if str(r.correlation) == "nan" else f"{r.correlation:+.3f}"
        overlap_s = "-" if r.overlap_pct is None else f"{r.overlap_pct:.1f}"
        # Color the verdict
        if "REDUNDANT" in r.recommendation:
            verdict = f"[red]{r.recommendation}[/red]"
        elif "OVERLAPPING" in r.recommendation:
            verdict = f"[yellow]{r.recommendation}[/yellow]"
        elif "INDEPENDENT" in r.recommendation:
            verdict = f"[green]{r.recommendation}[/green]"
        else:
            verdict = r.recommendation
        t.add_row(r.gate_a, r.gate_b, corr_s, overlap_s, str(r.n_samples), verdict)

    console.print(t)
    console.print()

    redundant = [r for r in results if "REDUNDANT" in r.recommendation]
    if redundant:
        console.print(
            f"[red]{len(redundant)} pair(s) redundant[/red] "
            "- drop or merge before optimization."
        )
    else:
        console.print("[green]No redundant pairs detected.[/green]")
