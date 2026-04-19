"""Per-tab HTML fragment generators."""
from __future__ import annotations

from typing import Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.io import to_html

from ..results import BacktestResult, OptunaResult, WalkForwardResult


def _div(fig: go.Figure) -> str:
    return to_html(fig, include_plotlyjs=False, full_html=False, config={"displayModeBar": False})


def performance_tab(bt: BacktestResult, wf: Optional[WalkForwardResult] = None) -> str:
    parts = []

    # Equity curve
    equity_source = wf.oos_equity_curve if wf and wf.oos_equity_curve else bt.equity_curve
    if equity_source:
        df = pd.DataFrame(equity_source)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df["date"], y=df["equity"], mode="lines",
                                  name="Equity", line=dict(color="#2a7ae2", width=2)))
        fig.update_layout(title="Equity curve", height=360, margin=dict(l=40, r=20, t=50, b=40))
        parts.append(f'<div class="section"><div class="chart">{_div(fig)}</div></div>')

        # Drawdown
        equity = df["equity"].values
        import numpy as np
        peak = np.maximum.accumulate(equity)
        dd = (equity - peak) / peak * 100
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=df["date"], y=dd, fill="tozeroy",
                                   line=dict(color="#d0443e"), name="Drawdown"))
        fig2.update_layout(title="Drawdown (%)", height=220, margin=dict(l=40, r=20, t=40, b=40))
        parts.append(f'<div class="section"><div class="chart">{_div(fig2)}</div></div>')

    # Trade scatter
    trades = wf.oos_trades if wf and wf.oos_trades else bt.trades
    if trades:
        exit_dates = [t.exit_date for t in trades]
        pnl_pcts = [t.pnl_pct for t in trades]
        colors = ["#2d9c3a" if p > 0 else "#d0443e" for p in pnl_pcts]
        fig3 = go.Figure()
        fig3.add_trace(go.Scatter(x=exit_dates, y=pnl_pcts, mode="markers",
                                   marker=dict(color=colors, size=6, opacity=0.7),
                                   name="Trade P&L%"))
        fig3.update_layout(title="Per-trade P&L (%)", height=300, margin=dict(l=40, r=20, t=40, b=40))
        parts.append(f'<div class="section"><div class="chart">{_div(fig3)}</div></div>')

    if not parts:
        parts.append('<div class="note">No performance data available.</div>')

    return "\n".join(parts)


def robustness_tab(bt: BacktestResult, wf: Optional[WalkForwardResult] = None) -> str:
    parts = []

    parts.append(
        '<div class="note">Full robustness suite (MC, param landscape, entry delay, LOSO) '
        'lands in Phase 1. Current view is walk-forward only. DSR: <b>pending Phase 0</b>.</div>'
    )

    if wf and wf.windows:
        indices = []
        is_pfs = []
        oos_pfs = []
        for w in wf.windows:
            if w.train_metrics and w.test_metrics:
                indices.append(f"W{w.index}")
                is_pfs.append(w.train_metrics.profit_factor)
                oos_pfs.append(w.test_metrics.profit_factor)

        if indices:
            fig = go.Figure()
            fig.add_trace(go.Bar(x=indices, y=is_pfs, name="IS PF", marker_color="#2a7ae2"))
            fig.add_trace(go.Bar(x=indices, y=oos_pfs, name="OOS PF", marker_color="#d0443e"))
            fig.update_layout(title="IS vs OOS Profit Factor per window", barmode="group",
                              height=320, margin=dict(l=40, r=20, t=50, b=40))
            parts.append(f'<div class="section"><div class="chart">{_div(fig)}</div></div>')
    else:
        parts.append('<div class="note">No walk-forward result — pass --walkforward to populate this tab.</div>')

    return "\n".join(parts)


def parameters_tab(opt: Optional[OptunaResult] = None) -> str:
    parts = []
    if opt is None:
        return '<div class="note">No optimization was run for this strategy.</div>'

    # Param importance
    if opt.param_importance:
        names = list(opt.param_importance.keys())
        vals = list(opt.param_importance.values())
        pairs = sorted(zip(names, vals), key=lambda kv: kv[1], reverse=True)
        names, vals = zip(*pairs)
        fig = go.Figure()
        fig.add_trace(go.Bar(x=list(vals), y=list(names), orientation="h",
                              marker_color="#2a7ae2"))
        fig.update_layout(title="Optuna parameter importance", height=360,
                          margin=dict(l=120, r=20, t=50, b=40))
        parts.append(f'<div class="section"><div class="chart">{_div(fig)}</div></div>')

    # Fitness trajectory
    if opt.all_trials:
        ordered = sorted(opt.all_trials, key=lambda t: t.number)
        x = [t.number for t in ordered]
        y = [t.fitness for t in ordered]
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=x, y=y, mode="markers",
                                   marker=dict(size=6, color="#2d9c3a", opacity=0.6)))
        fig2.update_layout(title="Fitness per trial", height=300,
                           margin=dict(l=40, r=20, t=50, b=40))
        parts.append(f'<div class="section"><div class="chart">{_div(fig2)}</div></div>')

    # Top-20 trials table
    if opt.all_trials:
        top = sorted(opt.all_trials, key=lambda t: t.fitness, reverse=True)[:20]
        rows = ['<table><thead><tr><th>#</th><th>Fitness</th><th>Trades</th><th>PF</th><th>Params</th></tr></thead><tbody>']
        for t in top:
            params_str = ", ".join(f"{k}={v:.3f}" for k, v in t.params.items())
            pf = t.metrics.get("pf", "-")
            trades = t.metrics.get("trades", "-")
            rows.append(f"<tr><td>{t.number}</td><td>{t.fitness:.3f}</td><td>{trades}</td><td>{pf}</td><td><code>{params_str}</code></td></tr>")
        rows.append("</tbody></table>")
        parts.append(f'<div class="section"><h2>Top 20 trials by fitness</h2>{"".join(rows)}</div>')

    return "\n".join(parts) if parts else '<div class="note">No parameter data to display.</div>'
