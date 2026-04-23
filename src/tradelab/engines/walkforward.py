"""
Walk-forward validation engine.

Port of C:/TradingScripts/s2_walkforward.py.

Methodology:
  - Rolling train / test / step windows (configurable, defaults from config)
  - Optuna optimizes at each train window
  - Best params evaluated on subsequent test (OOS) window
  - OOS trades stitched into a single chronological stream
  - WFE ratio computed as OOS_PF / IS_PF for robustness assessment

The original leakage bug is fixed automatically because run_backtest now
uses window-end close for end-of-window liquidation rather than end-of-data.
"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Optional

import numpy as np
import optuna
import pandas as pd
from dateutil.relativedelta import relativedelta

from ..config import get_config
from ..results import (
    BacktestMetrics,
    Trade,
    WalkForwardResult,
    WalkForwardWindow,
)
from ._live import print_wf_chart
from ._optuna_store import make_study_name, optuna_storage_url
from .backtest import run_backtest


def compute_splits(
    data_start: str,
    data_end: str,
    warmup_months: int,
    train_months: int,
    test_months: int,
    step_months: int,
) -> list[dict]:
    """Generate train/test window tuples, stepping forward by step_months."""
    start = pd.Timestamp(data_start) + relativedelta(months=warmup_months)
    end = pd.Timestamp(data_end)

    splits = []
    cur = start
    while True:
        train_end = cur + relativedelta(months=train_months) - pd.Timedelta(days=1)
        test_start = train_end + pd.Timedelta(days=1)
        test_end = test_start + relativedelta(months=test_months) - pd.Timedelta(days=1)
        if test_end > end:
            break
        splits.append({
            "train_start": cur.strftime("%Y-%m-%d"),
            "train_end": train_end.strftime("%Y-%m-%d"),
            "test_start": test_start.strftime("%Y-%m-%d"),
            "test_end": test_end.strftime("%Y-%m-%d"),
        })
        cur += relativedelta(months=step_months)

    return splits


def _wf_fitness(metrics, min_trades: int) -> float:
    """Same fitness as full Optuna but with lower min_trades threshold for short windows."""
    n_trades = metrics.total_trades
    if n_trades < min_trades:
        return 0.0
    pf = metrics.profit_factor
    if pf <= 0 or not np.isfinite(pf):
        return 0.0
    pf = min(pf, 10.0)
    max_dd = abs(metrics.max_drawdown_pct)
    dd_penalty = max(0.0, 1 - min(max_dd, 99.0) / 100)
    return float(pf * np.sqrt(n_trades) * dd_penalty)


def _wf_objective(trial, base_strategy, ticker_data, spy_close, train_start, train_end, min_trades):
    strat = copy.copy(base_strategy)
    strat.params = {
        **base_strategy.params,
        **{name: trial.suggest_float(name, lo, hi) for name, (lo, hi) in base_strategy.tunable_params.items()},
    }
    try:
        result = run_backtest(
            strat, ticker_data,
            start=train_start, end=train_end, spy_close=spy_close,
        )
    except Exception as e:
        trial.set_user_attr("error", str(e)[:100])
        return 0.0

    m = result.metrics
    trial.set_user_attr("pf", m.profit_factor)
    trial.set_user_attr("trades", m.total_trades)
    trial.set_user_attr("win_rate", m.win_rate)
    trial.set_user_attr("max_dd", m.max_drawdown_pct)
    trial.set_user_attr("annual_return", m.annual_return)

    return _wf_fitness(m, min_trades)


def _optimize_train_window(
    strategy, ticker_data, spy_close,
    train_start, train_end,
    n_trials, seed, min_trades,
    study_name: Optional[str] = None,
):
    """Return (best_params_dict, train_metrics) or (None, None) if no viable trial."""
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=seed),
        study_name=study_name or make_study_name(strategy.name, "wf"),
        storage=optuna_storage_url(),
        load_if_exists=False,
    )
    study.optimize(
        lambda trial: _wf_objective(
            trial, strategy, ticker_data, spy_close,
            train_start, train_end, min_trades,
        ),
        n_trials=n_trials,
        show_progress_bar=False,
    )

    if study.best_value is None or study.best_value == 0.0:
        return None, None

    # Re-run best params on the train window to get clean metrics
    best_strat = copy.copy(strategy)
    best_strat.params = {**strategy.params, **study.best_params}
    train_result = run_backtest(
        best_strat, ticker_data,
        start=train_start, end=train_end, spy_close=spy_close,
    )
    return dict(study.best_params), train_result.metrics


def run_walkforward(
    strategy,
    ticker_data,
    spy_close=None,
    data_start: Optional[str] = None,
    data_end: Optional[str] = None,
    train_months: Optional[int] = None,
    test_months: Optional[int] = None,
    step_months: Optional[int] = None,
    warmup_months: Optional[int] = None,
    n_trials_per_window: Optional[int] = None,
    seed: Optional[int] = None,
    min_trades_per_window: int = 10,
    verbose: bool = True,
) -> WalkForwardResult:
    """Run the full walk-forward validation."""
    cfg = get_config()
    data_start = data_start or cfg.defaults.data_start
    data_end = data_end or cfg.defaults.data_end
    train_months = train_months or cfg.walkforward.train_months
    test_months = test_months or cfg.walkforward.test_months
    step_months = step_months or cfg.walkforward.step_months
    warmup_months = warmup_months if warmup_months is not None else cfg.walkforward.warmup_months
    n_trials_per_window = n_trials_per_window or cfg.walkforward.n_trials_per_window
    seed = seed if seed is not None else cfg.optuna.seed

    splits = compute_splits(
        data_start, data_end,
        warmup_months, train_months, test_months, step_months,
    )

    wf_windows: list[WalkForwardWindow] = []
    all_oos_trades: list[Trade] = []

    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Build a Rich progress display when verbose; fall back to plain prints.
    if verbose:
        from rich.progress import (
            BarColumn, Progress, SpinnerColumn, TextColumn,
            TimeElapsedColumn, TimeRemainingColumn,
        )
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=None),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            refresh_per_second=4,
        )
        progress.__enter__()
        wf_task = progress.add_task(
            f"[{strategy.name}] walk-forward", total=len(splits),
        )
        log = progress.console.print
    else:
        progress = None
        wf_task = None
        log = lambda *a, **k: None

    try:
        log(f"Walk-forward: {len(splits)} splits, "
            f"{train_months}mo train / {test_months}mo test, "
            f"{n_trials_per_window} trials per window")

        for i, sp in enumerate(splits):
            log(f"[dim][{i+1}/{len(splits)}] "
                f"Train {sp['train_start']} -> {sp['train_end']}  |  "
                f"Test {sp['test_start']} -> {sp['test_end']}[/dim]")

            best_params, train_metrics = _optimize_train_window(
                strategy, ticker_data, spy_close,
                sp["train_start"], sp["train_end"],
                n_trials=n_trials_per_window,
                seed=seed,
                min_trades=min_trades_per_window,
                study_name=make_study_name(strategy.name, "wf", timestamp=run_ts, window_idx=i + 1),
            )

            if best_params is None:
                wf_windows.append(WalkForwardWindow(
                    index=i,
                    train_start=sp["train_start"], train_end=sp["train_end"],
                    test_start=sp["test_start"], test_end=sp["test_end"],
                    train_metrics=None, test_metrics=None, best_params={},
                ))
                log("  [yellow](no viable params)[/yellow]")
                if progress is not None:
                    progress.update(wf_task, advance=1)
                continue

            # Evaluate on OOS window — leakage fix is in run_backtest already
            best_strat = copy.copy(strategy)
            best_strat.params = {**strategy.params, **best_params}
            test_result = run_backtest(
                best_strat, ticker_data,
                start=sp["test_start"], end=sp["test_end"], spy_close=spy_close,
            )

            wf_windows.append(WalkForwardWindow(
                index=i,
                train_start=sp["train_start"], train_end=sp["train_end"],
                test_start=sp["test_start"], test_end=sp["test_end"],
                train_metrics=train_metrics,
                test_metrics=test_result.metrics,
                best_params=best_params,
            ))

            all_oos_trades.extend(test_result.trades)

            tm = train_metrics
            om = test_result.metrics
            log(f"  IS : PF={tm.profit_factor:.2f}  Tr={tm.total_trades:>4}  "
                f"WR={tm.win_rate:.1f}%  DD={tm.max_drawdown_pct:.1f}%")
            log(f"  OOS: PF=[bold]{om.profit_factor:.2f}[/bold]  "
                f"Tr={om.total_trades:>4}  WR={om.win_rate:.1f}%  "
                f"DD={om.max_drawdown_pct:.1f}%  Ret={om.pct_return:.1f}%")
            if progress is not None:
                progress.update(wf_task, advance=1)
    finally:
        if progress is not None:
            progress.__exit__(None, None, None)

    # --- AGGREGATE OOS METRICS ---
    sorted_trades = sorted(all_oos_trades, key=lambda t: t.exit_date)
    pnls = [t.pnl for t in sorted_trades]
    pnl_pcts = [t.pnl_pct for t in sorted_trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gp = sum(wins) if wins else 0.0
    gl = abs(sum(losses)) if losses else 0.001

    capital = cfg.defaults.initial_capital
    equity_list = [capital]
    running = capital
    for p in pnls:
        running += p
        equity_list.append(running)
    equity_arr = np.array(equity_list)
    peak = np.maximum.accumulate(equity_arr)
    drawdowns = (equity_arr - peak) / peak * 100 if len(equity_arr) else np.array([0])
    oos_max_dd = float(abs(drawdowns.min())) if len(drawdowns) else 0.0

    active_windows = sum(1 for w in wf_windows if w.test_metrics is not None)
    years = (active_windows * test_months) / 12.0 if active_windows else 1.0
    total_pct = (running / capital - 1) * 100 if capital else 0.0
    annual_return = ((running / capital) ** (1 / years) - 1) * 100 if years > 0 else 0.0

    sharpe = 0.0
    if len(pnl_pcts) > 1 and np.std(pnl_pcts) > 0:
        sharpe = float(np.mean(pnl_pcts) / np.std(pnl_pcts) * np.sqrt(252))

    oos_metrics = BacktestMetrics(
        total_trades=len(sorted_trades),
        wins=len(wins),
        losses=len(losses),
        win_rate=round(len(wins) / max(len(sorted_trades), 1) * 100, 2),
        profit_factor=round(gp / gl, 3),
        gross_profit=round(gp, 2),
        gross_loss=round(gl, 2),
        net_pnl=round(running - capital, 2),
        pct_return=round(total_pct, 2),
        annual_return=round(annual_return, 2),
        final_equity=round(running, 2),
        avg_win_pct=round(float(np.mean([t.pnl_pct for t in sorted_trades if t.pnl > 0])), 3) if wins else 0.0,
        avg_loss_pct=round(float(np.mean([t.pnl_pct for t in sorted_trades if t.pnl <= 0])), 3) if losses else 0.0,
        avg_bars_held=round(float(np.mean([t.bars_held for t in sorted_trades])), 2) if sorted_trades else 0.0,
        max_drawdown_pct=round(oos_max_dd, 3),
        sharpe_ratio=round(sharpe, 3),
    )

    # WFE ratio: OOS PF vs mean IS PF across windows
    is_pfs = [w.train_metrics.profit_factor for w in wf_windows
              if w.train_metrics and w.train_metrics.profit_factor > 0]
    mean_is_pf = float(np.mean(is_pfs)) if is_pfs else 0.0
    wfe = (oos_metrics.profit_factor / mean_is_pf) if mean_is_pf > 0 else 0.0

    oos_equity_curve = [
        {"date": t.exit_date, "equity": round(equity_list[i + 1], 2)}
        for i, t in enumerate(sorted_trades)
    ]

    result = WalkForwardResult(
        strategy=strategy.name,
        n_windows=len(wf_windows),
        windows=wf_windows,
        aggregate_oos=oos_metrics,
        wfe_ratio=round(wfe, 3),
        oos_trades=sorted_trades,
        oos_equity_curve=oos_equity_curve,
    )

    if verbose:
        print_wf_chart(result, title=f"Walk-forward IS vs OOS PF - {strategy.name}")

    return result