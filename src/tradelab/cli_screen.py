"""`tradelab screen` — find which symbols a strategy works best on."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .engines.screener import render_screen_html, run_screener
from .marketdata import (
    MissingTwelveDataKey,
    assert_pit_valid,
    download_symbols,
    enrich_universe,
)
from .registry import StrategyNotRegistered, instantiate_strategy


console = Console()


def screen(
    strategy: str = typer.Argument(..., help="Strategy name (from registry)"),
    symbols: str = typer.Option("", help="Comma list, @file.txt — required if no --universe"),
    universe: str = typer.Option("", help="Named universe from tradelab.yaml"),
    start: str = typer.Option("2022-01-01", help="Backtest start date"),
    end: str = typer.Option("", help="Backtest end date (default: today)"),
    top: int = typer.Option(20, help="Top-N to print to terminal"),
    min_trades: int = typer.Option(5, help="Drop symbols with < this many trades"),
    min_pf: float = typer.Option(1.0, help="Drop symbols with PF below this"),
    save_universe: str = typer.Option("", help="If set, write top-N to tradelab.yaml as a new universe with this name"),
    out_html: str = typer.Option("", help="Output HTML path; default reports/<strategy>_screen_<ts>.html"),
    open_html: bool = typer.Option(True, "--open/--no-open"),
    allow_yfinance_fallback: bool = typer.Option(False, "--allow-yfinance-fallback"),
) -> None:
    """
    Per-symbol screener: run the strategy on each symbol independently and
    rank by composite score (PF * sqrt(trades) * (1 - |DD|/100)).

    Use to build a focused universe of stocks where a strategy actually has
    edge, then pass that universe back into `tradelab run --universe`.
    """
    try:
        strat = instantiate_strategy(strategy)
    except StrategyNotRegistered as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(2)

    # Resolve symbol list
    if universe:
        from .config import get_config
        cfg = get_config()
        if universe not in cfg.universes:
            console.print(f"[red]Universe {universe!r} not in tradelab.yaml.[/red]")
            raise typer.Exit(2)
        symbol_list = list(cfg.universes[universe])
    elif symbols.startswith("@"):
        p = Path(symbols[1:])
        symbol_list = [s.strip() for s in p.read_text().splitlines() if s.strip()]
    elif symbols:
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    else:
        console.print("[red]Provide --symbols or --universe.[/red]")
        raise typer.Exit(2)

    if not end:
        end = datetime.now().strftime("%Y-%m-%d")

    console.print(f"[dim]Downloading {len(symbol_list)} symbols ...[/dim]")
    try:
        data = download_symbols(symbol_list, start=start, end=end,
                                 allow_yfinance_fallback=allow_yfinance_fallback)
    except MissingTwelveDataKey as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(4)

    if not data:
        console.print("[red]No data retrieved.[/red]")
        raise typer.Exit(1)

    try:
        assert_pit_valid(data, start=start)
    except Exception as e:
        console.print(f"[yellow]PIT warning: {e}[/yellow]")

    console.print("[dim]Enriching with indicators ...[/dim]")
    enriched = enrich_universe(data, benchmark="SPY")

    spy_close = None
    if "SPY" in enriched:
        spy_close = enriched["SPY"].set_index("Date")["Close"]

    console.print(f"[dim]Screening {len(enriched) - (1 if 'SPY' in enriched else 0)} symbols ...[/dim]")
    n_done = [0]
    def _progress(sym, idx, total):
        n_done[0] = idx
        if idx % max(1, total // 10) == 0 or idx == total:
            console.print(f"  [dim]{idx}/{total}: {sym}[/dim]")
    result = run_screener(
        strat, enriched, benchmark="SPY",
        spy_close=spy_close, start=start, end=end,
        progress_cb=_progress,
    )

    # Filter for the terminal printout (raw HTML keeps everything)
    filtered = result.filter(min_trades=min_trades, min_pf=min_pf)
    top_rows = filtered.rows[:top]

    console.print()
    if not top_rows:
        console.print(f"[yellow]No symbols passed the filter "
                      f"(min_trades={min_trades}, min_pf={min_pf}).[/yellow]")
        console.print(f"[dim]Total screened: {len(result.rows)}; show all with --min-trades 0 --min-pf 0.[/dim]")
    else:
        console.print(f"[bold]Top {len(top_rows)} of {len(filtered.rows)} symbols passing filter "
                      f"(min_trades={min_trades}, min_pf={min_pf}):[/bold]")
        t = Table(show_header=True, header_style="bold")
        t.add_column("Symbol", style="cyan")
        t.add_column("Score", justify="right")
        t.add_column("Trades", justify="right")
        t.add_column("PF", justify="right")
        t.add_column("WR%", justify="right")
        t.add_column("Net P&L", justify="right")
        t.add_column("Return%", justify="right")
        t.add_column("Max DD%", justify="right")
        t.add_column("Sharpe", justify="right")
        for r in top_rows:
            m = r.metrics
            pf_color = "green" if m.profit_factor >= 1.0 else "red"
            t.add_row(
                r.symbol,
                f"{r.composite_score:.2f}",
                str(m.total_trades),
                f"[{pf_color}]{m.profit_factor:.2f}[/{pf_color}]",
                f"{m.win_rate:.1f}",
                f"${m.net_pnl:,.0f}",
                f"{m.pct_return:.1f}",
                f"{m.max_drawdown_pct:.1f}",
                f"{m.sharpe_ratio:.2f}",
            )
        console.print(t)

    # Write HTML
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    if not out_html:
        out_html = f"reports/{strategy}_screen_{ts}.html"
    out_path = Path(out_html)
    render_screen_html(result, out_path)
    console.print(f"\n[green]HTML[/green]: {out_path}")

    # Optional: write top-N back to tradelab.yaml as a new named universe
    if save_universe:
        kept_syms = [r.symbol for r in top_rows]
        if not kept_syms:
            console.print(f"[yellow]Nothing to save (filter rejected everything).[/yellow]")
        else:
            yaml_path = Path("tradelab.yaml")
            if yaml_path.exists():
                text = yaml_path.read_text(encoding="utf-8")
                if f"  {save_universe}:" in text:
                    console.print(f"[yellow]Universe {save_universe!r} already exists; not overwriting.[/yellow]")
                else:
                    universe_entry = (
                        f"\n  {save_universe}:\n"
                        f"    [SPY, " + ", ".join(kept_syms) + "]\n"
                    )
                    # Append to the universes: block (heuristic: just append at end)
                    if "\nuniverses:" in text:
                        # Insert after the universes: line
                        text = text.rstrip() + universe_entry + "\n"
                    else:
                        text = text.rstrip() + "\n\nuniverses:" + universe_entry + "\n"
                    yaml_path.write_text(text, encoding="utf-8")
                    console.print(f"[green]Saved[/green] universe {save_universe!r} "
                                  f"({len(kept_syms)} symbols + SPY) to tradelab.yaml")
                    console.print(f"  Run: [cyan]tradelab run {strategy} --universe {save_universe} --robustness[/cyan]")

    if open_html:
        try:
            typer.launch(str(out_path))
        except Exception:
            pass
