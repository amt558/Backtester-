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


def robustness_tab(
    bt: BacktestResult,
    wf: Optional[WalkForwardResult] = None,
    opt: Optional[OptunaResult] = None,
    robustness=None,
) -> str:
    import math
    import plotly.graph_objects as go
    from ..engines.dsr import classify_dsr, deflated_sharpe_ratio

    parts = []

    # --- DSR readout (always, if we have return history) ---
    returns = bt.daily_returns()
    dsr_html = ""
    if returns is not None and len(returns) >= 10:
        n_trials = opt.n_trials if opt else 1
        dsr = deflated_sharpe_ratio(returns.values, n_trials=n_trials)
        if not math.isnan(dsr):
            verdict = classify_dsr(dsr)
            colour = {"robust": "#2d9c3a", "inconclusive": "#d6a02a",
                      "fragile": "#d0443e", "undefined": "#888"}.get(verdict, "#888")
            dsr_html = (
                f'<div class="section"><div class="chart">'
                f'<h2>Deflated Sharpe Ratio</h2>'
                f'<p style="font-size:24px;margin:8px 0;">'
                f'<b style="color:{colour};">{dsr:.3f}</b> '
                f'<span style="color:#666;font-size:14px;">({verdict} · {n_trials} trial{"s" if n_trials != 1 else ""})</span>'
                f'</p>'
                f'<p style="color:#555;font-size:12px;">Probability the observed edge is not luck from multiple testing. '
                f'Bands: &lt;0.50 fragile · 0.50–0.95 inconclusive · &gt;0.95 robust.</p>'
                f'</div></div>'
            )
    parts.append(dsr_html if dsr_html else
                 '<div class="note">Deflated Sharpe: insufficient return history.</div>')

    # --- Full robustness section if suite was run ---
    if robustness is not None:
        v = robustness.verdict
        v_colour = {"ROBUST": "#2d9c3a", "INCONCLUSIVE": "#d6a02a",
                    "FRAGILE": "#d0443e"}.get(v.verdict, "#888")
        parts.append(
            f'<div class="section"><div class="chart">'
            f'<h2>Aggregate verdict</h2>'
            f'<p style="font-size:28px;margin:6px 0;"><b style="color:{v_colour};">{v.verdict}</b></p>'
            f'<table><thead><tr><th>Test</th><th>Outcome</th><th>Reason</th></tr></thead><tbody>'
        )
        for s in v.signals:
            s_col = {"robust": "#2d9c3a", "inconclusive": "#d6a02a",
                     "fragile": "#d0443e"}.get(s.outcome, "#888")
            parts.append(
                f'<tr><td><code>{s.name}</code></td>'
                f'<td><b style="color:{s_col};">{s.outcome}</b></td>'
                f'<td>{s.reason}</td></tr>'
            )
        parts.append('</tbody></table></div></div>')

        # MC heatmap of percentiles (methods × metrics)
        mc = robustness.monte_carlo
        if mc and mc.distributions:
    
            metrics = mc.metrics
            methods = mc.methods
            z = []
            for method in methods:
                row = []
                for metric in metrics:
                    try:
                        d = mc.get(method, metric)
                        row.append(d.percentile_of_observed)
                    except KeyError:
                        row.append(None)
                z.append(row)
            fig = go.Figure(data=go.Heatmap(
                z=z, x=metrics, y=methods,
                colorscale="RdYlGn",
                zmin=0, zmax=100,
                text=[[f"{v:.0f}" if v is not None else "-" for v in r] for r in z],
                texttemplate="%{text}",
                colorbar=dict(title="Percentile"),
            ))
            fig.update_layout(title="MC percentile of observed (lower = worse)",
                              height=260, margin=dict(l=80, r=20, t=50, b=40))
            parts.append(f'<div class="section"><div class="chart">{_div(fig)}</div></div>')

        # Param landscape heatmap
        lp = robustness.param_landscape
        if lp and lp.fitness_grid and len(lp.top_params) == 2:
    
            fig = go.Figure(data=go.Heatmap(
                z=lp.fitness_grid,
                x=[f"{v:.3g}" for v in lp.grid_values[1]],
                y=[f"{v:.3g}" for v in lp.grid_values[0]],
                colorscale="Viridis",
                colorbar=dict(title="Fitness"),
            ))
            fig.update_layout(
                title=f"Parameter landscape: {lp.top_params[0]} × {lp.top_params[1]}",
                xaxis_title=lp.top_params[1], yaxis_title=lp.top_params[0],
                height=380, margin=dict(l=80, r=20, t=50, b=40),
            )
            parts.append(f'<div class="section"><div class="chart">{_div(fig)}</div></div>')

        # Entry delay bar chart
        ed = robustness.entry_delay
        if ed and ed.points:
    
            delays = [str(p.delay) for p in ed.points]
            pfs = [p.metrics.profit_factor for p in ed.points]
            fig = go.Figure(data=go.Bar(x=delays, y=pfs, marker_color="#2a7ae2"))
            fig.update_layout(title="Profit factor vs entry delay (bars)",
                              xaxis_title="Delay (bars)", yaxis_title="PF",
                              height=260, margin=dict(l=50, r=20, t=50, b=40))
            parts.append(f'<div class="section"><div class="chart">{_div(fig)}</div></div>')

        # Noise injection — histogram of PF across seeds, with baseline marker
        ni = getattr(robustness, "noise_injection", None)
        if ni and ni.points:
            pfs = [p.metrics.profit_factor for p in ni.points]
            fig = go.Figure()
            fig.add_trace(go.Histogram(x=pfs, nbinsx=20, marker_color="#6a5acd",
                                        name=f"{ni.n_seeds} seeds"))
            fig.add_vline(x=ni.baseline_pf, line_dash="dash", line_color="#2d9c3a",
                          annotation_text=f"Baseline PF {ni.baseline_pf:.2f}")
            fig.update_layout(
                title=f"Noise injection: PF across {ni.n_seeds} noisy runs "
                      f"({ni.noise_sigma_bp}bp sigma)",
                xaxis_title="Profit factor", yaxis_title="Count",
                height=260, margin=dict(l=50, r=20, t=50, b=40),
            )
            parts.append(f'<div class="section"><div class="chart">{_div(fig)}</div></div>')

        # LOSO bar chart
        lo = robustness.loso
        if lo and lo.folds:
    
            syms = [f.held_out_symbol for f in lo.folds]
            pfs = [f.metrics.profit_factor for f in lo.folds]
            fig = go.Figure(data=go.Bar(x=syms, y=pfs, marker_color="#d0443e"))
            fig.update_layout(title="LOSO: OOS PF with each symbol removed",
                              xaxis_title="Held-out symbol", yaxis_title="PF",
                              height=260, margin=dict(l=50, r=20, t=50, b=40))
            parts.append(f'<div class="section"><div class="chart">{_div(fig)}</div></div>')
    else:
        parts.append(
            '<div class="note">Pass --robustness to run the full suite '
            '(Monte Carlo + param landscape + entry delay + LOSO + verdict).</div>'
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
