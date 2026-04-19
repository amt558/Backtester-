"""
tradelab CLI entry point.

Session 2 wires up: backtest, optimize, wf (real impls).
Session 3 will add: robustness, full-test, compare.
"""
from __future__ import annotations

import time
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .config import get_config
from .registry import (
    list_registered_strategies,
    get_strategy_entry,
    instantiate_strategy,
    StrategyNotRegistered,
)


app = typer.Typer(
    name="tradelab",
    help="Local quant research platform — backtest, optimize, walk-forward, report.",
    add_completion=False,
    no_args_is_help=True,
)

console = Console()


# ─────────────────────────────────────────────────────────────────────
#  VERSION
# ─────────────────────────────────────────────────────────────────────

@app.command("version")
def version():
    """Show the tradelab version."""
    console.print(f"tradelab [bold cyan]{__version__}[/bold cyan]")


# ─────────────────────────────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────────────────────────────

@app.command("config")
def config_cmd(
    test_reports: bool = typer.Option(
        False, "--test-reports",
        help="Generate a synthetic tearsheet to verify reporting works."
    ),
):
    """Show active configuration and verify paths exist."""
    try:
        cfg = get_config()
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)

    console.print()
    console.print(f"[bold]Config file:[/bold]  [cyan]{cfg.config_path}[/cyan]")
    console.print()

    table = Table(show_header=True, header_style="bold", box=None)
    table.add_column("Setting", style="dim")
    table.add_column("Value")
    table.add_column("Status")

    def _check(path_str: str) -> str:
        return "[green]✓ exists[/green]" if Path(path_str).exists() else "[red]✗ missing[/red]"

    table.add_row("Data dir", cfg.paths.data_dir, _check(cfg.paths.data_dir))
    table.add_row("Reports dir", cfg.paths.reports_dir, _check(cfg.paths.reports_dir))
    table.add_row("Cache dir", cfg.paths.cache_dir, _check(cfg.paths.cache_dir))
    table.add_row("", "", "")
    table.add_row("Benchmark", cfg.benchmarks.primary, "")
    table.add_row("Initial capital", f"${cfg.defaults.initial_capital:,.0f}", "")
    table.add_row("Position size", f"{cfg.defaults.position_size_pct}%", "")
    table.add_row("Max positions", str(cfg.defaults.max_concurrent_positions), "")
    table.add_row("Data window", f"{cfg.defaults.data_start} → {cfg.defaults.data_end}", "")
    table.add_row("", "", "")
    table.add_row("Optuna trials (default)", str(cfg.optuna.n_trials_default), "")
    table.add_row("WF: train / test / step", f"{cfg.walkforward.train_months}mo / {cfg.walkforward.test_months}mo / {cfg.walkforward.step_months}mo", "")

    console.print(table)
    console.print()
    console.print(f"[dim]Registered strategies:[/dim] [bold]{len(cfg.strategies)}[/bold] "
                  f"(run [cyan]tradelab list[/cyan] to see them)")
    console.print()

    if test_reports:
        console.print("[dim]Running reporting smoke test...[/dim]")
        try:
            from .reporting.tearsheet import smoke_test_tearsheet
            report_path = smoke_test_tearsheet()
            console.print(f"[green]✓[/green] Smoke test report generated:")
            console.print(f"  [cyan]{report_path}[/cyan]")
            console.print(f"[dim]Open it in your browser to verify reporting works.[/dim]")
        except Exception as e:
            console.print(f"[red]✗ Smoke test failed:[/red] {e}")
            raise typer.Exit(code=1)


# ─────────────────────────────────────────────────────────────────────
#  LIST STRATEGIES
# ─────────────────────────────────────────────────────────────────────

@app.command("list")
def list_strategies():
    """List all registered strategies."""
    strategies = list_registered_strategies()
    if not strategies:
        console.print("[yellow]No strategies registered.[/yellow]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Description")
    table.add_column("Module", style="dim")

    status_color = {"ported": "green", "registered": "yellow", "pending": "dim", "archived": "red"}
    for name, entry in strategies.items():
        color = status_color.get(entry.status, "white")
        status_cell = f"[{color}]{entry.status}[/{color}]"
        table.add_row(name, status_cell, entry.description, entry.module)

    console.print()
    console.print(table)
    console.print()


# ─────────────────────────────────────────────────────────────────────
#  SHARED HELPERS
# ─────────────────────────────────────────────────────────────────────

def _check_strategy_exists(name: str):
    try:
        get_strategy_entry(name)
    except StrategyNotRegistered as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1)


def _load_data_for(strategy_name: str):
    """Load universe and instantiate strategy. Returns (strat, ticker_data, spy_close)."""
    from .data import load_universe, list_available_symbols

    cfg = get_config()
    bench = cfg.benchmarks.primary

    console.print(f"[dim]Loading universe...[/dim]")
    t0 = time.time()
    symbols = [s for s in list_available_symbols() if s != bench]
    ticker_data = load_universe(symbols, benchmark=bench)
    spy_close = ticker_data[bench].set_index("Date")["Close"]
    console.print(f"[dim]  loaded {len(ticker_data)} symbols in {time.time() - t0:.1f}s[/dim]")

    strat = instantiate_strategy(strategy_name)
    return strat, ticker_data, spy_close


def _print_metrics_table(title: str, metrics):
    """Render a BacktestMetrics object as a rich table."""
    t = Table(title=title, show_header=False, box=None)
    t.add_column("", style="dim")
    t.add_column("", justify="right")
    t.add_row("Trades", f"{metrics.total_trades}")
    t.add_row("Wins / Losses", f"{metrics.wins} / {metrics.losses}")
    t.add_row("Win Rate", f"{metrics.win_rate:.1f}%")
    t.add_row("Profit Factor", f"{metrics.profit_factor:.2f}")
    t.add_row("Avg Win / Loss", f"{metrics.avg_win_pct:.2f}% / {metrics.avg_loss_pct:.2f}%")
    t.add_row("Avg Bars Held", f"{metrics.avg_bars_held:.1f}")
    t.add_row("Annual Return", f"{metrics.annual_return:.1f}%")
    t.add_row("Max Drawdown", f"{metrics.max_drawdown_pct:.1f}%")
    t.add_row("Sharpe Ratio", f"{metrics.sharpe_ratio:.2f}")
    t.add_row("Final Equity", f"${metrics.final_equity:,.0f}")
    console.print(t)


# ─────────────────────────────────────────────────────────────────────
#  BACKTEST
# ─────────────────────────────────────────────────────────────────────

@app.command("backtest")
def backtest_cmd(
    strategy: str = typer.Argument(..., help="Registered strategy name"),
    tearsheet: bool = typer.Option(True, help="Generate QuantStats HTML tearsheet"),
):
    """Run a single baseline backtest."""
    _check_strategy_exists(strategy)
    from .engines import run_backtest

    strat, ticker_data, spy_close = _load_data_for(strategy)

    console.print(f"[dim]Running backtest...[/dim]")
    t0 = time.time()
    result = run_backtest(strat, ticker_data, spy_close=spy_close)
    console.print(f"[dim]  finished in {time.time() - t0:.1f}s[/dim]\n")

    _print_metrics_table(f"{strategy} — baseline", result.metrics)

    if tearsheet:
        from .reporting.tearsheet import render_backtest_tearsheet
        path = render_backtest_tearsheet(result, title=f"{strategy} baseline")
        console.print(f"\n[green]✓[/green] Tearsheet: [cyan]{path}[/cyan]")


# ─────────────────────────────────────────────────────────────────────
#  OPTIMIZE
# ─────────────────────────────────────────────────────────────────────

@app.command("optimize")
def optimize_cmd(
    strategy: str = typer.Argument(..., help="Registered strategy name"),
    trials: int = typer.Option(None, help="Number of Optuna trials (default from config)"),
    tearsheet: bool = typer.Option(True, help="Generate tearsheet of best-params backtest"),
):
    """Run Optuna parameter search."""
    _check_strategy_exists(strategy)
    from .engines import run_optimization

    strat, ticker_data, spy_close = _load_data_for(strategy)

    console.print(f"[dim]Running Optuna ({trials or 'default'} trials)...[/dim]")
    t0 = time.time()
    opt_result = run_optimization(
        strat, ticker_data,
        n_trials=trials, spy_close=spy_close,
        verbose=True, rerun_best=True,
    )
    console.print(f"[dim]  finished in {time.time() - t0:.1f}s[/dim]\n")

    # Best trial summary
    best = opt_result.best_trial
    console.print(f"[bold]Best trial:[/bold] #{best.number}  "
                  f"(fitness = [green]{best.fitness:.2f}[/green])")
    pt = Table(show_header=False, box=None)
    pt.add_column("", style="dim")
    pt.add_column("", justify="right")
    for k, v in best.params.items():
        pt.add_row(k, f"{v:.4f}")
    console.print(pt)
    console.print()

    if opt_result.best_backtest:
        _print_metrics_table(f"{strategy} — best params", opt_result.best_backtest.metrics)

    # Param importance
    if opt_result.param_importance:
        console.print("\n[bold]Parameter importance[/bold] (higher = more impact on fitness)")
        it = Table(show_header=False, box=None)
        it.add_column("", style="dim")
        it.add_column("", justify="right")
        for k, v in opt_result.param_importance.items():
            bar = "█" * int(v * 40)
            it.add_row(k, f"{v:.3f}  {bar}")
        console.print(it)

    # Top 5 trials
    all_sorted = sorted(opt_result.all_trials, key=lambda t: t.fitness, reverse=True)[:5]
    if all_sorted:
        console.print("\n[bold]Top 5 trials[/bold]")
        tt = Table(show_header=True, header_style="bold")
        tt.add_column("#", justify="right")
        tt.add_column("Fitness", justify="right")
        tt.add_column("PF", justify="right")
        tt.add_column("Trades", justify="right")
        tt.add_column("WR%", justify="right")
        tt.add_column("DD%", justify="right")
        tt.add_column("AnnRet%", justify="right")
        for t in all_sorted:
            m = t.metrics
            tt.add_row(
                str(t.number),
                f"{t.fitness:.2f}",
                f"{m.get('pf', 0):.2f}",
                str(m.get('trades', 0)),
                f"{m.get('win_rate', 0):.1f}",
                f"{m.get('max_dd', 0):.1f}",
                f"{m.get('annual_return', 0):.1f}",
            )
        console.print(tt)

    if tearsheet and opt_result.best_backtest:
        from .reporting.tearsheet import render_backtest_tearsheet
        path = render_backtest_tearsheet(
            opt_result.best_backtest,
            title=f"{strategy} Optuna best (trial #{best.number})",
        )
        console.print(f"\n[green]✓[/green] Tearsheet: [cyan]{path}[/cyan]")


# ─────────────────────────────────────────────────────────────────────
#  WALK-FORWARD
# ─────────────────────────────────────────────────────────────────────

@app.command("wf")
def walkforward_cmd(
    strategy: str = typer.Argument(..., help="Registered strategy name"),
    trials: int = typer.Option(None, help="Optuna trials per window (default from config)"),
):
    """Walk-forward validation with per-window Optuna."""
    _check_strategy_exists(strategy)
    from .engines import run_walkforward

    strat, ticker_data, spy_close = _load_data_for(strategy)

    console.print(f"[dim]Running walk-forward...[/dim]")
    t0 = time.time()
    wf = run_walkforward(
        strat, ticker_data, spy_close=spy_close,
        n_trials_per_window=trials, verbose=True,
    )
    console.print(f"[dim]  finished in {time.time() - t0:.1f}s[/dim]\n")

    # Per-window table
    tt = Table(title="Per-window OOS results", show_header=True, header_style="bold")
    tt.add_column("#", justify="right")
    tt.add_column("Train", no_wrap=True)
    tt.add_column("Test", no_wrap=True)
    tt.add_column("Tr", justify="right")
    tt.add_column("WR%", justify="right")
    tt.add_column("PF", justify="right")
    tt.add_column("DD%", justify="right")
    tt.add_column("Ret%", justify="right")

    for w in wf.windows:
        if w.test_metrics is None:
            tt.add_row(str(w.index + 1), w.train_start[:7], w.test_start[:7],
                       "—", "—", "—", "—", "—")
            continue
        m = w.test_metrics
        tt.add_row(
            str(w.index + 1),
            f"{w.train_start[:7]}→{w.train_end[:7]}",
            f"{w.test_start[:7]}→{w.test_end[:7]}",
            str(m.total_trades),
            f"{m.win_rate:.1f}",
            f"{m.profit_factor:.2f}",
            f"{m.max_drawdown_pct:.1f}",
            f"{m.pct_return:.1f}",
        )
    console.print(tt)

    # Aggregate OOS
    _print_metrics_table(f"{strategy} — aggregate OOS", wf.aggregate_oos)

    # WFE verdict
    wfe = wf.wfe_ratio
    if wfe < 0.5:
        verdict = "[red]WEAK: OOS retains <50% of IS edge — likely overfit[/red]"
    elif wfe < 0.75:
        verdict = "[yellow]MARGINAL: OOS retains 50–75% of IS edge[/yellow]"
    elif wfe < 0.90:
        verdict = "[green]GOOD: OOS retains 75–90% of IS edge — robust[/green]"
    else:
        verdict = "[bold green]EXCELLENT: OOS retains >90% of IS edge[/bold green]"

    console.print(f"\n[bold]WFE ratio:[/bold] {wfe:.2f}")
    console.print(verdict)


# ─────────────────────────────────────────────────────────────────────
#  ROBUSTNESS (Session 3 stub)
# ─────────────────────────────────────────────────────────────────────

@app.command("robustness")
def robustness_cmd(
    strategy: str = typer.Argument(..., help="Registered strategy name"),
):
    """5-test robustness suite. [Session 3]"""
    console.print(f"[yellow]robustness[/yellow] is a stub — Session 3 will implement it.")
    _check_strategy_exists(strategy)


from .cli_run import run as _run_cmd; app.command(name="run")(_run_cmd)
from .cli_history import history_app as _history_app; app.add_typer(_history_app, name="history")


if __name__ == "__main__":
    app()