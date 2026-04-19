"""
`tradelab run` — all-in-one command: download → backtest → optional Optuna/WF →
report + dashboard → open.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import typer

from .audit import record_run
from .dashboard import build_dashboard
from .determinism import hash_config, hash_universe
from .engines.backtest import run_backtest
from .engines.cost_sweep import format_cost_sweep_markdown, run_cost_sweep
from .engines.dsr import classify_dsr, deflated_sharpe_ratio
from .engines.optimizer import run_optimization, run_param_sensitivity
from .engines.walkforward import run_walkforward
from .robustness import run_robustness_suite
from .marketdata import (
    MissingTwelveDataKey,
    PITViolation,
    assert_pit_valid,
    download_symbols,
    enrich_universe,
)
from .registry import instantiate_strategy, StrategyNotRegistered
from .reporting import (
    generate_executive_report,
    render_backtest_tearsheet,
    render_robustness_tearsheet,
)


def run(
    strategy: str = typer.Argument(..., help="Strategy name (from registry)"),
    symbols: str = typer.Option("", help="Comma-separated tickers, or @file.txt"),
    universe: str = typer.Option("", help="Named universe from tradelab.yaml (overrides --symbols)"),
    start: str = typer.Option("2020-01-01", help="Data start date"),
    end: str = typer.Option("", help="Data end date (default: today)"),
    optimize: bool = typer.Option(False, "--optimize/--no-optimize", help="Run Optuna"),
    walkforward: bool = typer.Option(False, "--walkforward/--no-walkforward", help="Run walk-forward"),
    n_trials: int = typer.Option(100, help="Optuna trials (if --optimize)"),
    fitness: str = typer.Option(
        "pf_sqrt_trades_dd",
        help="Optuna fitness: pf_sqrt_trades_dd | pf | sharpe | sortino | annual_return | calmar",
    ),
    pruner: str = typer.Option("none", help="Optuna pruner: none | median"),
    sensitivity_pct: float = typer.Option(
        20.0, help="Post-Optuna sensitivity sweep span (% above/below best, 0 = skip)",
    ),
    cost_sweep: bool = typer.Option(False, "--cost-sweep/--no-cost-sweep",
                                     help="Append cost-sensitivity sweep to the report"),
    robustness: bool = typer.Option(False, "--robustness/--no-robustness",
                                     help="Run the full robustness suite (MC + param landscape "
                                          "+ entry delay + LOSO + verdict)"),
    full: bool = typer.Option(False, "--full/--no-full",
                               help="Mega-flag: turns on --optimize, --walkforward, "
                                    "--cost-sweep, and --robustness simultaneously"),
    mc_simulations: int = typer.Option(500, help="Monte Carlo simulations per method"),
    noise_seeds: int = typer.Option(50, help="Noise injection seed count"),
    noise_sigma_bp: float = typer.Option(5.0, help="Noise sigma in basis points"),
    loso_trials_per_fold: int = typer.Option(0, help="Optuna trials per LOSO fold (0 = baseline params)"),
    allow_yfinance_fallback: bool = typer.Option(
        False, "--allow-yfinance-fallback/--no-allow-yfinance-fallback",
        help="Permit yfinance fallback when TWELVEDATA_API_KEY is missing "
             "(default: refuse, Twelve Data is authoritative)",
    ),
    tearsheet: bool = typer.Option(True, "--tearsheet/--no-tearsheet",
                                     help="Generate QuantStats HTML tearsheet alongside report+dashboard"),
    open_dashboard: bool = typer.Option(True, "--open-dashboard/--no-open-dashboard",
                                         help="Auto-open dashboard after build"),
) -> None:
    """
    Run a full strategy evaluation and produce a report + interactive dashboard.
    """
    # --- mega-flag: --full implies all four pillars ---
    if full:
        optimize = True
        walkforward = True
        cost_sweep = True
        robustness = True

    # --- resolve universe ---
    symbol_list: list[str] = []
    if universe:
        # Named universe from tradelab.yaml takes precedence
        from .config import get_config
        try:
            cfg = get_config()
        except Exception as e:
            typer.echo(f"Cannot load config to resolve --universe: {e}", err=True)
            raise typer.Exit(2)
        if universe not in cfg.universes:
            import difflib
            available = sorted(cfg.universes.keys())
            close = difflib.get_close_matches(universe, available, n=3, cutoff=0.5)
            hint = f" Did you mean: {', '.join(close)}?" if close else ""
            typer.echo(
                f"Universe '{universe}' not in tradelab.yaml.{hint} "
                f"Available: {', '.join(available) or '(none)'}",
                err=True,
            )
            raise typer.Exit(2)
        symbol_list = list(cfg.universes[universe])
    elif symbols.startswith("@"):
        path = Path(symbols[1:])
        if not path.exists():
            typer.echo(f"Symbol file not found: {path}", err=True)
            raise typer.Exit(2)
        symbol_list = [s.strip() for s in path.read_text().splitlines() if s.strip()]
    elif symbols:
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    else:
        typer.echo(
            "No symbols provided. Use --symbols, --universe, or --symbols @file.txt.",
            err=True,
        )
        raise typer.Exit(2)

    if not end:
        end = datetime.now().strftime("%Y-%m-%d")

    typer.echo(f"Symbols: {symbol_list}")
    typer.echo(f"Window:  {start} -> {end}")

    # --- download ---
    typer.echo("Downloading / reading cache ...")
    try:
        data = download_symbols(
            symbol_list, start=start, end=end,
            allow_yfinance_fallback=allow_yfinance_fallback,
        )
    except MissingTwelveDataKey as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(4)

    if not data:
        typer.echo("No data retrieved for any symbol.", err=True)
        raise typer.Exit(1)

    # --- PIT inception check ---
    try:
        assert_pit_valid(data, start=start)
    except PITViolation as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(3)

    # --- enrich with indicators ---
    typer.echo("Computing indicators ...")
    data = enrich_universe(data, benchmark="SPY")

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
    sensitivity_result = None
    if optimize:
        typer.echo(f"Running Optuna ({n_trials} trials, fitness={fitness}, pruner={pruner}) ...")
        opt_result = run_optimization(
            strat, data, n_trials=n_trials, spy_close=spy_close,
            start=start, end=end, verbose=False, rerun_best=True,
            fitness=fitness, pruner=pruner,
        )
        if opt_result.best_backtest is not None:
            bt = opt_result.best_backtest
            typer.echo(f"  Best trial PF: {bt.metrics.profit_factor}")

        # Post-Optuna sensitivity sweep around the optimum
        if sensitivity_pct > 0 and opt_result.best_trial:
            typer.echo(f"Sensitivity sweep around best (±{sensitivity_pct}%) ...")
            sensitivity_result = run_param_sensitivity(
                strat, data, opt_result.best_trial.params,
                spy_close=spy_close, start=start, end=end,
                span_pct=sensitivity_pct, n_steps=5, fitness=fitness,
            )

    # --- optional walk-forward ---
    wf_result = None
    if walkforward:
        typer.echo("Running walk-forward ...")
        wf_result = run_walkforward(
            strat, data, spy_close=spy_close,
            data_start=start, data_end=end, verbose=False,
        )
        typer.echo(f"  WFE: {wf_result.wfe_ratio}  OOS PF: {wf_result.aggregate_oos.profit_factor}")

    # --- optional robustness suite ---
    robustness_result = None
    if robustness:
        typer.echo("Running robustness suite ...")
        robustness_result = run_robustness_suite(
            strat, data, bt,
            optuna_result=opt_result, wf_result=wf_result,
            spy_close=spy_close, start=start, end=end,
            mc_n_simulations=mc_simulations,
            loso_n_trials_per_fold=loso_trials_per_fold or None,
            noise_n_seeds=noise_seeds,
            noise_sigma_bp=noise_sigma_bp,
            show_progress=True,
        )
        v = robustness_result.verdict
        typer.echo(f"  Verdict: {v.verdict} "
                   f"({sum(1 for s in v.signals if s.outcome=='robust')} robust / "
                   f"{sum(1 for s in v.signals if s.outcome=='inconclusive')} inconclusive / "
                   f"{sum(1 for s in v.signals if s.outcome=='fragile')} fragile)")

    # --- optional cost-sensitivity sweep ---
    cost_sweep_result = None
    if cost_sweep:
        typer.echo("Running cost-sensitivity sweep ...")
        cost_sweep_result = run_cost_sweep(
            strat, data, spy_close=spy_close, start=start, end=end,
        )
        for p in cost_sweep_result.points:
            typer.echo(f"  {p.multiplier:g}x cost: trades={p.metrics.total_trades} "
                       f"PF={p.metrics.profit_factor} ret={p.metrics.pct_return}%")

    # --- reports ---
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = Path("reports") / f"{strategy}_{ts}"
    report_path = generate_executive_report(
        bt, optuna_result=opt_result, wf_result=wf_result,
        universe=data, out_dir=out_dir,
        robustness_result=robustness_result,
    )

    # If cost-sweep was run, append its markdown section to the executive report
    if cost_sweep_result is not None:
        with report_path.open("a", encoding="utf-8") as f:
            f.write("\n\n---\n\n")
            f.write(format_cost_sweep_markdown(cost_sweep_result))

    dashboard_path = build_dashboard(
        bt, optuna_result=opt_result, wf_result=wf_result,
        universe=data, out_dir=out_dir,
        robustness_result=robustness_result,
        sensitivity=sensitivity_result,
    )
    typer.echo(f"Report:    {report_path}")
    typer.echo(f"Dashboard: {dashboard_path}")

    # --- QuantStats tearsheet (optional, default on) ---
    tearsheet_path = None
    if tearsheet:
        try:
            tearsheet_path = render_backtest_tearsheet(
                bt, output_path=out_dir / "quantstats_tearsheet.html",
                title=f"{strategy} — QuantStats tearsheet",
            )
            typer.echo(f"Tearsheet: {tearsheet_path}")
        except Exception as e:
            typer.echo(f"(QuantStats tearsheet skipped: {type(e).__name__}: {e})", err=True)

    # --- Robustness tearsheet (when robustness suite ran) ---
    if robustness_result is not None:
        try:
            qs_link = "quantstats_tearsheet.html" if tearsheet_path else None
            rob_tearsheet = render_robustness_tearsheet(
                bt, optuna_result=opt_result, wf_result=wf_result,
                robustness_result=robustness_result,
                universe=data,
                out_path=out_dir / "robustness_tearsheet.html",
                quantstats_link=qs_link,
            )
            typer.echo(f"Robustness tearsheet: {rob_tearsheet}")
        except Exception as e:
            typer.echo(f"(Robustness tearsheet skipped: {type(e).__name__}: {e})", err=True)

    # --- audit trail ---
    returns = bt.daily_returns()
    dsr_p = None
    verdict = None
    if returns is not None and len(returns) >= 10:
        n_tr = opt_result.n_trials if opt_result else 1
        p = deflated_sharpe_ratio(returns.values, n_trials=n_tr)
        import math as _math
        if not _math.isnan(p):
            dsr_p = float(p)
            verdict = classify_dsr(p).upper()
    # If the full robustness suite ran, its verdict supersedes the DSR classifier
    if robustness_result is not None:
        verdict = robustness_result.verdict.verdict
    try:
        run_id = record_run(
            strategy_name=strategy,
            verdict=verdict,
            dsr_probability=dsr_p,
            input_data_hash=hash_universe(data),
            config_hash=hash_config(bt.params),
            report_card_markdown=report_path.read_text(encoding="utf-8"),
            report_card_html_path=str(dashboard_path),
        )
        typer.echo(f"Audit:     run_id={run_id[:8]}")
    except Exception as e:
        typer.echo(f"(Audit write failed: {e})", err=True)

    if open_dashboard:
        try:
            typer.launch(str(dashboard_path))
        except Exception as e:
            typer.echo(f"(Could not auto-open: {e})", err=True)
