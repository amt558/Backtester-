"""`tradelab score-from-trades` — score an externally produced trade list."""
from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from .csv_scoring import score_trades, write_report_folder
from .io.tv_csv import TVCSVParseError, parse_tv_trades_csv


console = Console()


def score_from_trades(
    csv_path: str = typer.Argument(..., help="Path to a TradingView 'List of trades' CSV."),
    symbol: str = typer.Option(..., "--symbol", help="Ticker the CSV represents (e.g., AMZN)."),
    name: str = typer.Option(..., "--name", help="Card base name (e.g., 'viprasol-amzn-v1'). "
                                                  "Used for the report folder + audit row."),
    timeframe: str = typer.Option("1D", "--timeframe",
                                   help="Bar timeframe of the source Pine strategy (cosmetic)."),
    starting_equity: float = typer.Option(100_000.0, "--starting-equity",
                                           help="Equity baseline for percent / DD calculations."),
    pine_path: str = typer.Option("", "--pine-path",
                                    help="Optional path to the Pine source to archive next to the report."),
    audit: bool = typer.Option(True, "--audit/--no-audit",
                                help="Write a row to the audit DB."),
    open_dashboard: bool = typer.Option(True, "--open-dashboard/--no-open-dashboard",
                                         help="Auto-open dashboard.html when finished."),
):
    """Score a TradingView Strategy Tester CSV and emit a report folder."""
    csv_file = Path(csv_path)
    if not csv_file.exists() or not csv_file.is_file():
        console.print(f"[red]CSV not found:[/red] {csv_file}")
        raise typer.Exit(2)

    csv_text = csv_file.read_text(encoding="utf-8-sig")  # tolerate BOM

    try:
        parsed = parse_tv_trades_csv(csv_text, symbol=symbol)
    except TVCSVParseError as e:
        console.print(f"[red]CSV parse error:[/red] {e}")
        raise typer.Exit(1)

    console.print(f"[dim]Parsed {len(parsed.trades)} closed trades "
                  f"({parsed.start_date} → {parsed.end_date}).[/dim]")

    out = score_trades(
        parsed, strategy_name=name, symbol=symbol,
        timeframe=timeframe, starting_equity=starting_equity,
    )

    pine_source = None
    if pine_path:
        p = Path(pine_path)
        if not p.exists():
            console.print(f"[yellow]Pine source not found, continuing without:[/yellow] {p}")
        else:
            try:
                pine_source = p.read_text(encoding="utf-8")
            except (PermissionError, UnicodeDecodeError) as e:
                console.print(f"[yellow]Pine source unreadable ({type(e).__name__}), continuing without:[/yellow] {p}")

    folder = write_report_folder(
        out, base_name=name, pine_source=pine_source,
        csv_text=csv_text, record_audit=audit,
    )

    v = out.verdict
    color = {"ROBUST": "green", "INCONCLUSIVE": "yellow", "FRAGILE": "red"}.get(v.verdict, "white")
    console.print(f"\n[bold]Verdict:[/bold] [{color}]{v.verdict}[/{color}]  "
                  f"({sum(1 for s in v.signals if s.outcome=='robust')} robust / "
                  f"{sum(1 for s in v.signals if s.outcome=='inconclusive')} inconclusive / "
                  f"{sum(1 for s in v.signals if s.outcome=='fragile')} fragile)")
    console.print(f"Report:    [cyan]{folder / 'executive_report.md'}[/cyan]")
    console.print(f"Dashboard: [cyan]{folder / 'dashboard.html'}[/cyan]")

    if open_dashboard:
        try:
            typer.launch(str(folder / "dashboard.html"))
        except Exception:
            pass
