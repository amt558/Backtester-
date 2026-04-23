"""Per-tab HTML fragment generators."""
from __future__ import annotations

from collections import Counter
from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.io import to_html

from ..results import BacktestResult, OptunaResult, WalkForwardResult
from ._theme import apply_plotly_theme


def _div(fig: go.Figure) -> str:
    # Apply the tradelab dark template before rendering so every chart
    # in every tab ships with consistent dark colors baked in.
    apply_plotly_theme(fig)
    return to_html(fig, include_plotlyjs=False, full_html=False, config={"displayModeBar": False})


def _kpi(label: str, value: str) -> str:
    return f'<div class="kpi"><div class="label">{label}</div><div class="value">{value}</div></div>'


def performance_tab(
    bt: BacktestResult,
    wf: Optional[WalkForwardResult] = None,
    benchmark_close: Optional[pd.Series] = None,
    benchmark_label: str = "SPY",
    robustness=None,
) -> str:
    parts = []
    m = bt.metrics

    # KPI strip — instant orientation
    parts.append('<div class="section"><div class="kpi-grid">')
    parts.append(_kpi("Net P&L", f"${m.net_pnl:,.0f}"))
    parts.append(_kpi("Return", f"{m.pct_return}%"))
    parts.append(_kpi("Annual return", f"{m.annual_return}%"))
    parts.append(_kpi("Trades", f"{m.total_trades}"))
    parts.append(_kpi("Win rate", f"{m.win_rate}%"))
    parts.append(_kpi("Profit factor", f"{m.profit_factor}"))
    parts.append(_kpi("Sharpe", f"{m.sharpe_ratio}"))
    parts.append(_kpi("Max drawdown", f"{m.max_drawdown_pct}%"))
    parts.append('</div></div>')

    # Expected-return distribution from MC (if robustness was run)
    rd = None
    if robustness is not None and getattr(robustness, "monte_carlo", None):
        rd = getattr(robustness.monte_carlo, "return_distribution", None) or None
    if rd and "annual_p50" in rd:
        parts.append(
            '<div class="section"><h2>Expected annual return (from MC)</h2>'
            '<p style="color:#999;font-size:13px;margin-top:-4px;">'
            f'Annualized over {rd.get("years", 0):.2f}y window · '
            f'{rd.get("n_samples", 0)} bootstrap simulations. '
            'Use the 5th percentile for conservative sizing.'
            '</p><div class="kpi-grid">'
            + _kpi("Median ann", f"{rd['annual_p50']:+.1f}%")
            + _kpi("5th pct ann", f"{rd['annual_p5']:+.1f}%")
            + _kpi("25th pct ann", f"{rd['annual_p25']:+.1f}%")
            + _kpi("75th pct ann", f"{rd['annual_p75']:+.1f}%")
            + _kpi("95th pct ann", f"{rd['annual_p95']:+.1f}%")
            + '</div></div>'
        )

    # Equity curve + drawdown (paired)
    equity_source = wf.oos_equity_curve if wf and wf.oos_equity_curve else bt.equity_curve
    if equity_source:
        df = pd.DataFrame(equity_source)
        df["date"] = pd.to_datetime(df["date"])

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df["date"], y=df["equity"], mode="lines",
                                  name="Strategy equity",
                                  line=dict(color="#3b82f6", width=2),
                                  fill="tozeroy", fillcolor="rgba(59,130,246,0.10)"))
        # Benchmark overlay — normalized to same starting equity so the
        # chart answers "did I beat buy-and-hold of the benchmark?" at a glance.
        if benchmark_close is not None and not benchmark_close.empty and len(df) > 1:
            bench = pd.Series(benchmark_close).copy()
            bench.index = pd.to_datetime(bench.index)
            start_date = df["date"].iloc[0]
            end_date = df["date"].iloc[-1]
            bench = bench.loc[(bench.index >= start_date) & (bench.index <= end_date)]
            if len(bench) >= 2 and bench.iloc[0] > 0:
                initial = float(df["equity"].iloc[0])
                bench_dollars = bench / float(bench.iloc[0]) * initial
                fig.add_trace(go.Scatter(
                    x=bench.index, y=bench_dollars.values, mode="lines",
                    name=f"{benchmark_label} buy-and-hold",
                    line=dict(color="#888", width=1.2, dash="dot"),
                    opacity=0.75,
                ))
        fig.update_layout(title="Equity curve", height=340,
                          margin=dict(l=40, r=20, t=50, b=40),
                          yaxis_title="$",
                          legend=dict(orientation="h", y=-0.18))
        parts.append(f'<div class="section"><div class="chart">{_div(fig)}</div></div>')

        equity = df["equity"].values
        peak = np.maximum.accumulate(equity)
        dd = (equity - peak) / peak * 100
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=df["date"], y=dd, fill="tozeroy",
                                   line=dict(color="#ef4444"), name="Drawdown"))
        fig2.update_layout(title="Drawdown (%)", height=220,
                           margin=dict(l=40, r=20, t=40, b=40))
        parts.append(f'<div class="section"><div class="chart">{_div(fig2)}</div></div>')

        # Rolling annualized Sharpe — stability-over-time indicator that
        # complements the single aggregate Sharpe KPI. A strategy with good
        # overall Sharpe but volatile rolling Sharpe is hiding regime risk.
        daily_ret = pd.Series(equity, index=df["date"].values).pct_change().dropna()
        if len(daily_ret) >= 126:   # ~2 * rolling window
            window = 63
            rolling_mean = daily_ret.rolling(window).mean()
            rolling_std = daily_ret.rolling(window).std()
            rolling_sharpe = (rolling_mean / rolling_std * np.sqrt(252)).dropna()
            if len(rolling_sharpe) > 0:
                fig_rs = go.Figure()
                fig_rs.add_trace(go.Scatter(
                    x=rolling_sharpe.index, y=rolling_sharpe.values, mode="lines",
                    line=dict(color="#a78bfa", width=1.5),
                    name=f"Rolling {window}d Sharpe",
                ))
                fig_rs.add_hline(y=0, line_dash="dot", line_color="#999", opacity=0.6)
                fig_rs.add_hline(y=1, line_dash="dash", line_color="#22c55e",
                                  opacity=0.6, annotation_text="Sharpe=1",
                                  annotation_position="top right")
                fig_rs.update_layout(
                    title=f"Rolling {window}-day annualized Sharpe — stability over time",
                    height=240, margin=dict(l=40, r=20, t=50, b=40),
                    yaxis_title="Sharpe",
                )
                parts.append(f'<div class="section"><div class="chart">{_div(fig_rs)}</div></div>')

    # Regime breakdown — answers "does this strategy depend on a specific
    # market regime (bull / chop / bear)?" If PF is concentrated in one
    # regime, the aggregate edge is regime-conditional, not durable.
    if getattr(bt, "regime_breakdown", None):
        rb = bt.regime_breakdown
        regimes = [r for r in ("bull", "chop", "bear") if r in rb]
        if regimes and any(rb[r].get("n_trades", 0) > 0 for r in regimes):
            pf_vals = [rb[r].get("pf", 0.0) for r in regimes]
            trades_vals = [rb[r].get("n_trades", 0) for r in regimes]
            ret_vals = [rb[r].get("avg_ret_pct", 0.0) for r in regimes]
            wr_vals = [rb[r].get("win_rate", 0.0) for r in regimes]
            regime_labels = [r.upper() for r in regimes]

            # 2-column: PF bars + trade-count bars
            parts.append('<div class="section dual-grid">')
            fig_pf = go.Figure()
            bar_colors = ["#22c55e" if v >= 1.0 else "#ef4444" for v in pf_vals]
            fig_pf.add_trace(go.Bar(
                x=regime_labels, y=pf_vals, marker_color=bar_colors,
                text=[f"{v:.2f}" for v in pf_vals], textposition="outside",
            ))
            fig_pf.add_hline(y=1.0, line_dash="dot", line_color="gray",
                              annotation_text="break-even", annotation_position="right")
            fig_pf.update_layout(
                title="Profit Factor by benchmark regime (entry date)",
                height=260, margin=dict(l=40, r=20, t=50, b=40),
                yaxis_title="PF (capped 10)", showlegend=False,
            )
            parts.append(f'<div class="chart">{_div(fig_pf)}</div>')

            fig_tr = go.Figure()
            fig_tr.add_trace(go.Bar(
                x=regime_labels, y=trades_vals, marker_color="#3b82f6",
                text=trades_vals, textposition="outside",
            ))
            fig_tr.update_layout(
                title="Trade count by regime",
                height=260, margin=dict(l=40, r=20, t=50, b=40),
                yaxis_title="Trades", showlegend=False,
            )
            parts.append(f'<div class="chart">{_div(fig_tr)}</div>')
            parts.append('</div>')

            # Supporting metrics table
            rows_html = ['<table class="sortable"><thead><tr>'
                         '<th>Regime</th><th>Trades</th><th>Win %</th>'
                         '<th>PF</th><th>Avg Ret %</th><th>Net P&L</th>'
                         '</tr></thead><tbody>']
            for r in regimes:
                row = rb[r]
                rows_html.append(
                    f"<tr><td><b>{r.upper()}</b></td>"
                    f"<td>{row.get('n_trades', 0)}</td>"
                    f"<td>{row.get('win_rate', 0):.1f}</td>"
                    f"<td>{row.get('pf', 0):.2f}</td>"
                    f"<td>{row.get('avg_ret_pct', 0):+.2f}</td>"
                    f"<td>${row.get('net_pnl', 0):,.0f}</td></tr>"
                )
            rows_html.append("</tbody></table>")
            parts.append(
                '<div class="section"><div class="chart" style="padding:0;">'
                '<div style="padding:10px 14px;font-size:14px;font-weight:600;color:var(--fg);">'
                "Regime breakdown — concentrated PF in one regime is fragility"
                '</div>' + "".join(rows_html) + '</div></div>'
            )

        # Monthly returns heatmap (year × month)
        df_idx = df.set_index("date").sort_index()
        monthly = df_idx["equity"].resample("ME").last().pct_change().dropna() * 100
        if len(monthly) >= 2:
            mtab = pd.DataFrame({
                "year": monthly.index.year,
                "month": monthly.index.month,
                "ret": monthly.values,
            })
            pivot = mtab.pivot(index="year", columns="month", values="ret")
            # Reindex so all 12 months present even if missing
            pivot = pivot.reindex(columns=range(1, 13))
            month_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            fig_mh = go.Figure(data=go.Heatmap(
                z=pivot.values,
                x=month_labels,
                y=[str(y) for y in pivot.index],
                colorscale="RdYlGn",
                zmid=0,
                text=[[f"{v:.1f}%" if pd.notna(v) else "" for v in row] for row in pivot.values],
                texttemplate="%{text}",
                colorbar=dict(title="Return %"),
            ))
            fig_mh.update_layout(title="Monthly returns (%)", height=max(220, 36 * len(pivot) + 100),
                                  margin=dict(l=60, r=20, t=50, b=40))
            parts.append(f'<div class="section"><div class="chart">{_div(fig_mh)}</div></div>')

    # Per-trade P&L scatter
    trades = wf.oos_trades if wf and wf.oos_trades else bt.trades
    if trades:
        exit_dates = [t.exit_date for t in trades]
        pnl_pcts = [t.pnl_pct for t in trades]
        colors = ["#22c55e" if p > 0 else "#ef4444" for p in pnl_pcts]
        sizes = [6 + min(20, abs(p)) for p in pnl_pcts]   # bigger marker = bigger trade
        fig3 = go.Figure()
        fig3.add_trace(go.Scatter(
            x=exit_dates, y=pnl_pcts, mode="markers",
            marker=dict(color=colors, size=sizes, opacity=0.6,
                         line=dict(width=0.5, color="rgba(255,255,255,0.3)")),
            text=[f"{t.ticker}: {t.pnl_pct:.2f}% over {t.bars_held} bars" for t in trades],
            hovertemplate="%{text}<extra></extra>",
            name="Trade P&L%",
        ))
        fig3.add_hline(y=0, line_dash="dot", line_color="gray", opacity=0.5)
        fig3.update_layout(title="Per-trade P&L (%) by exit date — marker size = magnitude",
                           height=320, margin=dict(l=40, r=20, t=50, b=40))
        parts.append(f'<div class="section"><div class="chart">{_div(fig3)}</div></div>')

        # Trade returns distribution
        fig_dist = go.Figure()
        fig_dist.add_trace(go.Histogram(
            x=pnl_pcts, nbinsx=30,
            marker_color="#3b82f6",
            opacity=0.75,
            name="Trade returns",
        ))
        fig_dist.add_vline(x=0, line_dash="dot", line_color="gray")
        fig_dist.add_vline(x=float(np.mean(pnl_pcts)), line_dash="dash",
                            line_color="#22c55e",
                            annotation_text=f"Mean {np.mean(pnl_pcts):.2f}%")
        fig_dist.update_layout(title="Distribution of per-trade returns (%)",
                                height=260, margin=dict(l=40, r=20, t=50, b=40),
                                xaxis_title="Return %", yaxis_title="Count")
        parts.append(f'<div class="section"><div class="chart">{_div(fig_dist)}</div></div>')

    if not parts:
        parts.append('<div class="note">No performance data available.</div>')

    return "\n".join(parts)


def trades_tab(bt: BacktestResult, wf: Optional[WalkForwardResult] = None) -> str:
    """Trade-level analysis: per-symbol P&L, exit reasons, durations, full table."""
    trades = wf.oos_trades if wf and wf.oos_trades else bt.trades
    if not trades:
        return '<div class="note">No trades to display.</div>'

    parts = []

    # Monthly P&L attribution — answers "when did this strategy make/lose money?"
    # Pulls from bt.monthly_pnl (computed post-backtest in _diagnostics.py).
    monthly = getattr(bt, "monthly_pnl", None) or []
    if monthly:
        months = [m["month"] for m in monthly]
        net = [m["net_pnl"] for m in monthly]
        counts = [m["n_trades"] for m in monthly]
        colors = ["#22c55e" if v > 0 else "#ef4444" for v in net]

        fig_mpnl = go.Figure()
        fig_mpnl.add_trace(go.Bar(
            x=months, y=net, marker_color=colors,
            text=[f"${v:,.0f}<br>{c} tr" for v, c in zip(net, counts)],
            textposition="outside",
            hovertemplate="%{x}<br>net: $%{y:,.0f}<extra></extra>",
        ))
        fig_mpnl.add_hline(y=0, line_dash="dot", line_color="gray")
        fig_mpnl.update_layout(
            title="Monthly P&L (grouped by trade exit date)",
            height=320, margin=dict(l=40, r=20, t=50, b=60),
            yaxis_title="$ P&L",
        )
        parts.append(f'<div class="section"><div class="chart">{_div(fig_mpnl)}</div></div>')

        # Best / worst month KPIs
        best = max(monthly, key=lambda r: r["net_pnl"])
        worst = min(monthly, key=lambda r: r["net_pnl"])
        best_label = f"{best['month']} · ${best['net_pnl']:+,.0f}"
        worst_label = f"{worst['month']} · ${worst['net_pnl']:+,.0f}"
        pos_months = sum(1 for m in monthly if m["net_pnl"] > 0)
        kpi_bits = (
            '<div class="section"><div class="kpi-grid">'
            + _kpi("Best month", best_label)
            + _kpi("Worst month", worst_label)
            + _kpi("Months traded", str(len(monthly)))
            + _kpi("Positive months", str(pos_months))
            + '</div></div>'
        )
        parts.append(kpi_bits)

    # Per-symbol P&L (sum across trades)
    by_sym: dict[str, float] = {}
    by_sym_count: dict[str, int] = {}
    for t in trades:
        by_sym[t.ticker] = by_sym.get(t.ticker, 0.0) + t.pnl
        by_sym_count[t.ticker] = by_sym_count.get(t.ticker, 0) + 1
    sorted_syms = sorted(by_sym.items(), key=lambda kv: kv[1], reverse=True)
    syms = [s for s, _ in sorted_syms]
    pnls = [p for _, p in sorted_syms]
    colors = ["#22c55e" if p > 0 else "#ef4444" for p in pnls]
    fig_sym = go.Figure()
    fig_sym.add_trace(go.Bar(
        x=syms, y=pnls, marker_color=colors,
        text=[f"${p:,.0f}<br>{by_sym_count[s]} tr" for s, p in sorted_syms],
        textposition="outside",
        name="Per-symbol P&L",
    ))
    fig_sym.update_layout(title="Net P&L by symbol",
                           height=max(280, 60 + 24 * len(syms)),
                           margin=dict(l=40, r=20, t=50, b=80),
                           yaxis_title="$ P&L")
    parts.append(f'<div class="section"><div class="chart">{_div(fig_sym)}</div></div>')

    # Two-column: exit reason pie + trade duration histogram
    parts.append('<div class="section dual-grid">')

    reason_counts = Counter(t.exit_reason for t in trades)
    fig_pie = go.Figure(data=[go.Pie(
        labels=list(reason_counts.keys()),
        values=list(reason_counts.values()),
        hole=0.4,
        marker=dict(colors=["#3b82f6", "#ef4444", "#eab308", "#a78bfa", "#22c55e"]),
    )])
    fig_pie.update_layout(title="Exit reasons", height=320,
                          margin=dict(l=20, r=20, t=50, b=40))
    parts.append(f'<div class="chart">{_div(fig_pie)}</div>')

    bars_held = [t.bars_held for t in trades]
    fig_dur = go.Figure()
    fig_dur.add_trace(go.Histogram(
        x=bars_held, nbinsx=20, marker_color="#a78bfa", opacity=0.8,
    ))
    fig_dur.add_vline(x=float(np.mean(bars_held)), line_dash="dash",
                       line_color="#22c55e",
                       annotation_text=f"Mean {np.mean(bars_held):.1f} bars")
    fig_dur.update_layout(title="Trade duration (bars held)",
                           height=320, margin=dict(l=40, r=20, t=50, b=40),
                           xaxis_title="Bars", yaxis_title="Count")
    parts.append(f'<div class="chart">{_div(fig_dur)}</div>')
    parts.append('</div>')

    # Trade KPI strip
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    avg_win_pct = float(np.mean([t.pnl_pct for t in wins])) if wins else 0.0
    avg_loss_pct = float(np.mean([t.pnl_pct for t in losses])) if losses else 0.0
    avg_win_d = float(np.mean([t.bars_held for t in wins])) if wins else 0.0
    avg_loss_d = float(np.mean([t.bars_held for t in losses])) if losses else 0.0
    best = max(trades, key=lambda t: t.pnl)
    worst = min(trades, key=lambda t: t.pnl)
    parts.append('<div class="section"><div class="kpi-grid">')
    parts.append(_kpi("Avg win %", f"{avg_win_pct:.2f}%"))
    parts.append(_kpi("Avg loss %", f"{avg_loss_pct:.2f}%"))
    parts.append(_kpi("Avg win bars", f"{avg_win_d:.1f}"))
    parts.append(_kpi("Avg loss bars", f"{avg_loss_d:.1f}"))
    parts.append(_kpi("Best trade", f"${best.pnl:,.0f} ({best.ticker})"))
    parts.append(_kpi("Worst trade", f"${worst.pnl:,.0f} ({worst.ticker})"))
    parts.append('</div></div>')

    # Sortable trade table
    rows_html: list[str] = []
    for t in trades:
        cls = "win" if t.pnl > 0 else "loss"
        rows_html.append(
            f'<tr>'
            f'<td>{t.ticker}</td>'
            f'<td data-sort="{t.entry_date}">{t.entry_date}</td>'
            f'<td data-sort="{t.exit_date}">{t.exit_date}</td>'
            f'<td data-sort="{t.bars_held}" style="text-align:right;">{t.bars_held}</td>'
            f'<td data-sort="{t.entry_price}" style="text-align:right;">${t.entry_price:.2f}</td>'
            f'<td data-sort="{t.exit_price}" style="text-align:right;">${t.exit_price:.2f}</td>'
            f'<td data-sort="{t.pnl}" class="{cls}" style="text-align:right;">${t.pnl:,.2f}</td>'
            f'<td data-sort="{t.pnl_pct}" class="{cls}" style="text-align:right;">{t.pnl_pct:.2f}%</td>'
            f'<td>{t.exit_reason}</td>'
            f'</tr>'
        )
    parts.append(
        '<div class="section"><h2>All trades — click any column header to sort</h2>'
        '<div class="chart" style="padding:0;">'
        '<table class="sortable">'
        '<thead><tr>'
        '<th>Symbol</th><th>Entry date</th><th>Exit date</th>'
        '<th style="text-align:right;">Bars</th>'
        '<th style="text-align:right;">Entry $</th><th style="text-align:right;">Exit $</th>'
        '<th style="text-align:right;">P&amp;L $</th><th style="text-align:right;">P&amp;L %</th>'
        '<th>Exit reason</th>'
        '</tr></thead><tbody>'
        + "".join(rows_html) +
        '</tbody></table></div></div>'
    )

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
            colour = {"robust": "#22c55e", "inconclusive": "#eab308",
                      "fragile": "#ef4444", "undefined": "#888"}.get(verdict, "#888")
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
        v_colour = {"ROBUST": "#22c55e", "INCONCLUSIVE": "#eab308",
                    "FRAGILE": "#ef4444"}.get(v.verdict, "#888")
        parts.append(
            f'<div class="section"><div class="chart">'
            f'<h2>Aggregate verdict</h2>'
            f'<p style="font-size:28px;margin:6px 0;"><b style="color:{v_colour};">{v.verdict}</b></p>'
            f'<table><thead><tr><th>Test</th><th>Outcome</th><th>Reason</th></tr></thead><tbody>'
        )
        for s in v.signals:
            s_col = {"robust": "#22c55e", "inconclusive": "#eab308",
                     "fragile": "#ef4444"}.get(s.outcome, "#888")
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

            # Per-metric distribution histograms (overlay 3 methods + observed line)
            method_colors = {"shuffle": "#3b82f6", "bootstrap": "#a78bfa",
                             "block_bootstrap": "#eab308"}
            metric_titles = {
                "max_dd": "Max drawdown %",
                "max_loss_streak": "Max consecutive losses",
                "time_underwater": "Time underwater (frac)",
                "ulcer_index": "Ulcer index",
            }
            parts.append('<div class="section dual-grid">')
            for metric in metrics:
                fig_m = go.Figure()
                obs_val = None
                for method in methods:
                    try:
                        d = mc.get(method, metric)
                    except KeyError:
                        continue
                    if not d.samples:
                        continue
                    fig_m.add_trace(go.Histogram(
                        x=d.samples, name=method, opacity=0.55,
                        marker_color=method_colors.get(method, "#888"),
                        nbinsx=30,
                    ))
                    obs_val = d.observed
                if obs_val is not None:
                    fig_m.add_vline(x=obs_val, line_dash="dash", line_color="#ef4444",
                                     line_width=2,
                                     annotation_text=f"observed {obs_val:.2f}")
                fig_m.update_layout(
                    title=f"{metric_titles.get(metric, metric)} — MC distributions",
                    barmode="overlay", height=240,
                    margin=dict(l=40, r=20, t=50, b=40),
                    showlegend=True,
                    legend=dict(orientation="h", y=-0.18),
                )
                parts.append(f'<div class="chart">{_div(fig_m)}</div>')
            parts.append('</div>')

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
            fig = go.Figure(data=go.Bar(x=delays, y=pfs, marker_color="#3b82f6"))
            fig.update_layout(title="Profit factor vs entry delay (bars)",
                              xaxis_title="Delay (bars)", yaxis_title="PF",
                              height=260, margin=dict(l=50, r=20, t=50, b=40))
            parts.append(f'<div class="section"><div class="chart">{_div(fig)}</div></div>')

        # Noise injection — histogram of PF across seeds, with baseline marker
        ni = getattr(robustness, "noise_injection", None)
        if ni and ni.points:
            pfs = [p.metrics.profit_factor for p in ni.points]
            fig = go.Figure()
            fig.add_trace(go.Histogram(x=pfs, nbinsx=20, marker_color="#a78bfa",
                                        name=f"{ni.n_seeds} seeds"))
            fig.add_vline(x=ni.baseline_pf, line_dash="dash", line_color="#22c55e",
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
            fig = go.Figure(data=go.Bar(x=syms, y=pfs, marker_color="#ef4444"))
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
            fig.add_trace(go.Bar(x=indices, y=is_pfs, name="IS PF", marker_color="#3b82f6"))
            fig.add_trace(go.Bar(x=indices, y=oos_pfs, name="OOS PF", marker_color="#ef4444"))
            fig.update_layout(title="IS vs OOS Profit Factor per window", barmode="group",
                              height=320, margin=dict(l=40, r=20, t=50, b=40))
            parts.append(f'<div class="section"><div class="chart">{_div(fig)}</div></div>')
    else:
        parts.append('<div class="note">No walk-forward result — pass --walkforward to populate this tab.</div>')

    return "\n".join(parts)


def parameters_tab(opt: Optional[OptunaResult] = None,
                    sensitivity: Optional[dict] = None) -> str:
    parts = []
    if opt is None:
        return '<div class="note">No optimization was run for this strategy.</div>'

    # Best-params card — most important info first
    if opt.best_trial:
        bt = opt.best_trial
        param_cells = "".join(
            f'<div class="kpi"><div class="label">{k}</div>'
            f'<div class="value" style="font-size:16px;">{v:.4g}</div></div>'
            for k, v in bt.params.items()
        )
        m = bt.metrics or {}
        trial_pf = m.get("pf", "-")
        trial_tr = m.get("trades", "-")
        trial_dd = m.get("max_dd", "-")
        parts.append(
            '<div class="section">'
            f'<h2>Best trial #{bt.number} — fitness <b style="color:#22c55e;">{bt.fitness:.3f}</b> '
            f'(PF {trial_pf} · {trial_tr} trades · DD {trial_dd}%)</h2>'
            f'<div class="kpi-grid">{param_cells}</div>'
            '</div>'
        )

    # Param importance
    if opt.param_importance:
        names = list(opt.param_importance.keys())
        vals = list(opt.param_importance.values())
        pairs = sorted(zip(names, vals), key=lambda kv: kv[1], reverse=True)
        names, vals = zip(*pairs)
        fig = go.Figure()
        fig.add_trace(go.Bar(x=list(vals), y=list(names), orientation="h",
                              marker_color="#3b82f6"))
        fig.update_layout(title="Optuna parameter importance", height=320,
                          margin=dict(l=140, r=20, t=50, b=40))
        parts.append(f'<div class="section"><div class="chart">{_div(fig)}</div></div>')

    # Parallel coordinates of all trials — the canonical Optuna view
    if opt.all_trials and len(opt.all_trials) >= 2:
        param_keys = list(opt.all_trials[0].params.keys())
        if param_keys:
            dims = []
            for k in param_keys:
                vals_k = [t.params.get(k) for t in opt.all_trials
                          if t.params.get(k) is not None]
                if not vals_k:
                    continue
                dims.append(dict(label=k, values=vals_k))
            fitness_vals = [t.fitness for t in opt.all_trials]
            dims.append(dict(label="fitness", values=fitness_vals))
            fig_pc = go.Figure(data=go.Parcoords(
                line=dict(color=fitness_vals, colorscale="Viridis",
                           showscale=True, colorbar=dict(title="Fitness")),
                dimensions=dims,
            ))
            fig_pc.update_layout(title="Parallel coordinates — all trials (color = fitness)",
                                  height=420, margin=dict(l=80, r=80, t=70, b=40))
            parts.append(f'<div class="section"><div class="chart">{_div(fig_pc)}</div></div>')

    # Fitness trajectory + Top-20 table side by side
    if opt.all_trials:
        parts.append('<div class="section dual-grid">')
        ordered = sorted(opt.all_trials, key=lambda t: t.number)
        x = [t.number for t in ordered]
        y = [t.fitness for t in ordered]
        running_max = []
        peak = -float("inf")
        for v in y:
            peak = max(peak, v)
            running_max.append(peak)
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=x, y=y, mode="markers", name="trial fitness",
                                    marker=dict(size=6, color="#3b82f6", opacity=0.5)))
        fig2.add_trace(go.Scatter(x=x, y=running_max, mode="lines", name="running best",
                                    line=dict(color="#ef4444", width=2)))
        fig2.update_layout(title="Fitness per trial · running best in red",
                            height=320, margin=dict(l=40, r=20, t=50, b=40),
                            legend=dict(orientation="h", y=-0.18))
        parts.append(f'<div class="chart">{_div(fig2)}</div>')

        top = sorted(opt.all_trials, key=lambda t: t.fitness, reverse=True)[:20]
        rows = ['<table class="sortable"><thead><tr>'
                '<th>#</th><th>Fitness</th><th>Trades</th><th>PF</th><th>Params</th>'
                '</tr></thead><tbody>']
        for t in top:
            params_str = ", ".join(f"{k}={v:.3g}" for k, v in t.params.items())
            pf = t.metrics.get("pf", "-")
            trades = t.metrics.get("trades", "-")
            rows.append(
                f"<tr><td>{t.number}</td>"
                f'<td data-sort="{t.fitness}">{t.fitness:.3f}</td>'
                f"<td>{trades}</td><td>{pf}</td>"
                f"<td><code style='font-size:11px;'>{params_str}</code></td></tr>"
            )
        rows.append("</tbody></table>")
        parts.append(
            '<div class="chart" style="padding:0;">'
            '<div style="padding:10px 14px;font-size:14px;font-weight:600;color:var(--fg);">'
            'Top 20 trials</div>'
            + "".join(rows) + '</div>'
        )
        parts.append('</div>')

    # Param sensitivity around the optimum (post-Optuna 1-axis sweep)
    if sensitivity:
        parts.append(
            '<div class="section"><h2>Sensitivity around the best trial</h2>'
            '<p style="color:#999;font-size:13px;">'
            'Each chart varies one param around its optimum (others held at best). '
            'Flat = robust; spike at best = cliff.'
            '</p></div><div class="section dual-grid">'
        )
        for pname, points in sensitivity.items():
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            best_x = xs[len(xs) // 2] if xs else None
            fig_s = go.Figure()
            fig_s.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers",
                                        line=dict(color="#3b82f6"),
                                        marker=dict(size=8, color="#3b82f6")))
            if best_x is not None:
                fig_s.add_vline(x=best_x, line_dash="dash", line_color="#22c55e",
                                  annotation_text="best")
            fig_s.update_layout(title=f"Sensitivity: {pname}",
                                 height=240, margin=dict(l=40, r=20, t=50, b=40),
                                 xaxis_title=pname, yaxis_title="Fitness")
            parts.append(f'<div class="chart">{_div(fig_s)}</div>')
        parts.append('</div>')

    return "\n".join(parts) if parts else '<div class="note">No parameter data to display.</div>'
