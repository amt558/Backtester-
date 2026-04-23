"""Assemble the full HTML dashboard."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from ..determinism import hash_config, hash_universe, render_footer
from ..results import BacktestResult, OptunaResult, WalkForwardResult
from . import tabs
from .templates import render_dashboard


def build_dashboard(
    backtest_result: BacktestResult,
    optuna_result: Optional[OptunaResult] = None,
    wf_result: Optional[WalkForwardResult] = None,
    universe: Optional[dict] = None,
    out_dir: Optional[Path] = None,
    robustness_result = None,
    sensitivity: Optional[dict] = None,
) -> Path:
    ts = datetime.now()
    if out_dir is None:
        out_dir = Path("reports") / f"{backtest_result.strategy}_{ts.strftime('%Y-%m-%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)

    title = f"{backtest_result.strategy} — tradelab dashboard"
    universe_str = ", ".join(sorted(universe.keys())) if universe else "see config"
    m = backtest_result.metrics
    # Verdict pill — pulled from robustness suite if it ran, else from DSR
    verdict_label = "UNKNOWN"
    if robustness_result is not None:
        verdict_label = robustness_result.verdict.verdict
    elif backtest_result.daily_returns() is not None:
        from ..engines.dsr import classify_dsr, deflated_sharpe_ratio
        import math
        n_tr = optuna_result.n_trials if optuna_result else 1
        try:
            p = deflated_sharpe_ratio(backtest_result.daily_returns().values, n_trials=n_tr)
            if not math.isnan(p):
                verdict_label = classify_dsr(p).upper()
        except Exception:
            pass

    # Headline P&L line gets prime real estate in the header
    pnl_line = (
        f"Net P&amp;L: ${m.net_pnl:,.0f} · "
        f"{m.pct_return}% return · "
        f"{m.total_trades} trades · "
        f"WR {m.win_rate}% · PF {m.profit_factor} · Sharpe {m.sharpe_ratio}"
    )
    meta = (
        f'<span class="verdict {verdict_label}">{verdict_label}</span> '
        f"<b>{pnl_line}</b><br>"
        f"Window: {backtest_result.start_date} → {backtest_result.end_date} · "
        f"Universe: {universe_str} · Run: {ts.strftime('%Y-%m-%d %H:%M:%S')}"
    )

    # Extract benchmark close series (SPY by default) for equity overlay.
    benchmark_close = None
    try:
        from ..config import get_config as _gc
        bench_sym = _gc().benchmarks.primary
    except Exception:
        bench_sym = "SPY"
    if universe and bench_sym in universe:
        bdf = universe[bench_sym]
        if hasattr(bdf, "columns") and "Date" in bdf.columns and "Close" in bdf.columns:
            try:
                benchmark_close = bdf.set_index("Date")["Close"]
            except Exception:
                benchmark_close = None

    performance_html = tabs.performance_tab(
        backtest_result, wf_result,
        benchmark_close=benchmark_close, benchmark_label=bench_sym,
        robustness=robustness_result,
    )
    trades_html = tabs.trades_tab(backtest_result, wf_result)
    robustness_html = tabs.robustness_tab(
        backtest_result, wf_result, optuna_result, robustness=robustness_result
    )
    parameters_html = tabs.parameters_tab(optuna_result, sensitivity=sensitivity)

    data_hash = hash_universe(universe) if universe else None
    config_hash = hash_config(backtest_result.params)
    footer_text = render_footer(data_hash=data_hash, config_hash=config_hash).replace("\n", "<br>")

    html = render_dashboard(
        title=title, meta=meta,
        performance_html=performance_html,
        trades_html=trades_html,
        robustness_html=robustness_html,
        parameters_html=parameters_html,
        footer=footer_text,
    )

    out_path = out_dir / "dashboard.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path
