"""
`tradelab run` — all-in-one command: download → backtest → optional Optuna/WF →
report + dashboard → open.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import typer

from .dashboard import build_dashboard
from .engines.backtest import run_backtest
from .engines.optimizer import run_optimization
from .engines.walkforward import run_walkforward
from .marketdata import download_symbols
from .registry import instantiate_strategy, StrategyNotRegistered
from .reporting import generate_executive_report


def run(
    strategy: str = typer.Argument(..., help="Strategy name (from registry)"),
    symbols: str = typer.Option("", help="Comma-separated tickers, or @file.txt"),
    start: str = typer.Option("2020-01-01", help="Data start date"),
    end: str = typer.Option("", help="Data end date (default: today)"),
    optimize: bool = typer.Option(False, "--optimize/--no-optimize", help="Run Optuna"),
    walkforward: bool = typer.Option(False, "--walkforward/--no-walkforward", help="Run walk-forward"),
    n_trials: int = typer.Option(100, help="Optuna trials (if --optimize)"),
    open_dashboard: bool = typer.Option(True, "--open-dashboard/--no-open-dashboard",
                                         help="Auto-open dashboard after build"),
) -> None:
    """
    Run a full strategy evaluation and produce a report + interactive dashboard.
    """
    # --- resolve universe ---
    if not symbols:
        typer.echo("No symbols provided (--symbols).", err=True)
        raise typer.Exit(2)
    if symbols.startswith("@"):
        path = Path(symbols[1:])
        if not path.exists():
            typer.echo(f"Symbol file not found: {path}", err=True)
            raise typer.Exit(2)
        symbol_list = [s.strip() for s in path.read_text().splitlines() if s.strip()]
    else:
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]

    if not end:
        end = datetime.now().strftime("%Y-%m-%d")

    typer.echo(f"Symbols: {symbol_list}")
    typer.echo(f"Window:  {start} \u2192 {end}")

    # --- download ---
    typer.echo("Downloading / reading cache ...")
    data = download_symbols(symbol_list, start=start, end=end)
    if not data:
        typer.echo("No data retrieved for any symbol.", err=True)
        raise typer.Exit(1)

    # --- resolve strategy via registry ---
    try:
        strat = instantiate_strategy(strategy)
    except StrategyNotRegistered as e:
        typer.echo(f"Strategy not found in registry: {strategy}", err=True)
        typer.echo(str(e), err=True)
        raise typer.Exit(2)

    spy_close = None
    if "SPY" in data and "Close" in data["SPY"].columns:
        spy_close = data["SPY"].set_index("Date")["Close"] if "Date" in data["SPY"].columns else data["SPY"]["Close"]

    # --- backtest ---
    typer.echo("Running backtest ...")
    bt = run_backtest(strat, data, start=start, end=end, spy_close=spy_close)
    typer.echo(f"  Trades: {bt.metrics.total_trades}  PF: {bt.metrics.profit_factor}  "
               f"Sharpe: {bt.metrics.sharpe_ratio}")

    # --- optional optimize ---
    opt_result = None
    if optimize:
        typer.echo(f"Running Optuna ({n_trials} trials) ...")
        opt_result = run_optimization(
            strat, data, n_trials=n_trials, spy_close=spy_close,
            start=start, end=end, verbose=False, rerun_best=True,
        )
        if opt_result.best_backtest is not None:
            bt = opt_result.best_backtest
            typer.echo(f"  Best trial PF: {bt.metrics.profit_factor}")

    # --- optional walk-forward ---
    wf_result = None
    if walkforward:
        typer.echo("Running walk-forward ...")
        wf_result = run_walkforward(
            strat, data, spy_close=spy_close,
            data_start=start, data_end=end, verbose=False,
        )
        typer.echo(f"  WFE: {wf_result.wfe_ratio}  OOS PF: {wf_result.aggregate_oos.profit_factor}")

    # --- reports ---
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = Path("reports") / f"{strategy}_{ts}"
    report_path = generate_executive_report(
        bt, optuna_result=opt_result, wf_result=wf_result,
        universe=data, out_dir=out_dir,
    )
    dashboard_path = build_dashboard(
        bt, optuna_result=opt_result, wf_result=wf_result,
        universe=data, out_dir=out_dir,
    )
    typer.echo(f"Report:    {report_path}")
    typer.echo(f"Dashboard: {dashboard_path}")

    if open_dashboard:
        try:
            typer.launch(str(dashboard_path))
        except Exception as e:
            typer.echo(f"(Could not auto-open: {e})", err=True)
