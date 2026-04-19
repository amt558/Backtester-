"""
Robustness HTML tearsheet — single-page combination of QuantStats output
and tradelab's robustness-suite custom div blocks.

Why this exists alongside the dashboard:
  - Dashboard is interactive (tabs, click-to-sort) — best for live exploration.
  - This tearsheet is FLAT (one long scroll page) — best for sharing,
    printing, or pasting into a research note. Everything visible at once.

Sections (in order):
  1. Header with verdict pill + headline P&L
  2. QuantStats summary block (link to full QS tearsheet beside it)
  3. Verdict signal table (which tests said robust/fragile/inconclusive + why)
  4. Robustness charts: MC heatmap + per-metric distributions, param landscape
     heatmap, entry-delay bars, LOSO bars, noise injection histogram
  5. Determinism footer
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from ..determinism import hash_config, hash_universe, render_footer
from ..results import BacktestResult, OptunaResult, WalkForwardResult


_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
body {{ font-family: system-ui, -apple-system, sans-serif; margin: 0; background: #fafafa; color: #222; line-height: 1.45; }}
.header {{ padding: 22px 32px; background: #1a1a1a; color: #fafafa; }}
.header h1 {{ margin: 0; font-size: 22px; }}
.header .verdict {{ display: inline-block; padding: 4px 12px; border-radius: 4px;
                    font-weight: 700; font-size: 13px; margin-right: 10px; }}
.verdict.ROBUST {{ background: #2d9c3a; color: white; }}
.verdict.INCONCLUSIVE {{ background: #d6a02a; color: white; }}
.verdict.FRAGILE {{ background: #d0443e; color: white; }}
.verdict.UNKNOWN {{ background: #666; color: white; }}
.header .meta {{ font-size: 13px; opacity: 0.85; margin-top: 8px; line-height: 1.55; }}
.body {{ padding: 24px 32px; max-width: 1200px; margin: 0 auto; }}
.section {{ margin-bottom: 32px; background: white; border: 1px solid #e0e0e0;
            border-radius: 6px; padding: 18px 22px; }}
.section h2 {{ font-size: 17px; color: #444; margin: 0 0 12px; padding-bottom: 8px;
              border-bottom: 1px solid #eee; }}
.section h3 {{ font-size: 14px; color: #555; margin: 16px 0 6px; }}
.kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
             gap: 12px; margin: 12px 0; }}
.kpi {{ background: #fafafa; border: 1px solid #e8e8e8; border-radius: 6px;
        padding: 10px 14px; }}
.kpi .label {{ font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: 0.04em; }}
.kpi .value {{ font-size: 18px; font-weight: 600; margin-top: 4px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ padding: 6px 10px; text-align: left; border-bottom: 1px solid #eee; }}
th {{ background: #f5f5f5; font-weight: 600; }}
.outcome-robust {{ color: #2d9c3a; font-weight: 600; }}
.outcome-fragile {{ color: #d0443e; font-weight: 600; }}
.outcome-inconclusive {{ color: #d6a02a; font-weight: 600; }}
.note {{ background: #fff8e0; padding: 10px 14px; border-left: 3px solid #f0c040;
         color: #555; font-size: 13px; margin: 12px 0; border-radius: 2px; }}
.dual-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
@media (max-width: 900px) {{ .dual-grid {{ grid-template-columns: 1fr; }} }}
.footer {{ padding: 20px 32px; color: #888; font-size: 11px; border-top: 1px solid #e0e0e0;
           max-width: 1200px; margin: 0 auto; }}
.linkrow {{ font-size: 13px; color: #555; }}
.linkrow a {{ color: #2a7ae2; text-decoration: none; }}
.linkrow a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<div class="header">
<span class="verdict {verdict}">{verdict}</span>
<h1 style="display:inline;">{title}</h1>
<div class="meta">
<b>Net P&amp;L: ${net_pnl:,.0f}</b> · {pct_return}% return · {trades} trades ·
WR {win_rate}% · PF {pf} · Sharpe {sharpe} · Max DD {max_dd}%
<br>Window: {start} → {end} · Universe: {universe}
</div>
</div>
<div class="body">
{sections}
</div>
<div class="footer">{footer_html}</div>
</body>
</html>
"""


def _verdict_table(robust) -> str:
    if robust is None or not robust.verdict.signals:
        return '<div class="note">No verdict signals available.</div>'
    rows = []
    for s in robust.verdict.signals:
        cls = f"outcome-{s.outcome}"
        rows.append(
            f'<tr><td><code>{s.name}</code></td>'
            f'<td class="{cls}">{s.outcome}</td>'
            f'<td>{s.reason}</td></tr>'
        )
    return (
        '<table><thead><tr><th>Test</th><th>Outcome</th><th>Reason</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
    )


def _quantstats_metrics_section(qs_metrics: dict) -> str:
    if not qs_metrics:
        return '<div class="note">QuantStats metrics unavailable (insufficient return history).</div>'
    cells = []
    for name, value in qs_metrics.items():
        if abs(value) >= 1000:
            vstr = f"{value:,.2f}"
        elif abs(value) >= 1:
            vstr = f"{value:.3f}"
        else:
            vstr = f"{value:.4f}"
        cells.append(
            f'<div class="kpi"><div class="label">{name}</div>'
            f'<div class="value" style="font-size:15px;">{vstr}</div></div>'
        )
    return f'<div class="kpi-grid">{"".join(cells)}</div>'


def _build_robustness_charts(robust) -> str:
    """Re-use dashboard tabs.robustness_tab logic to produce the same charts."""
    from ..dashboard import tabs as dash_tabs
    if robust is None:
        return '<div class="note">Robustness suite was not run for this strategy.</div>'
    html = dash_tabs.robustness_tab(
        bt=robust.monte_carlo and robust.monte_carlo or None,   # noqa
        wf=None, opt=None, robustness=robust,
    )
    return html if html else '<div class="note">No robustness output to render.</div>'


def render_robustness_tearsheet(
    backtest_result: BacktestResult,
    optuna_result: Optional[OptunaResult] = None,
    wf_result: Optional[WalkForwardResult] = None,
    robustness_result=None,
    universe: Optional[dict] = None,
    out_path: Optional[Path] = None,
    quantstats_link: Optional[str] = None,
) -> Path:
    """
    Render a flat single-page robustness tearsheet HTML.

    Args:
        backtest_result: baseline backtest
        robustness_result: tradelab.robustness.RobustnessSuiteResult (or None)
        quantstats_link: relative path to a sibling QuantStats HTML, if generated
        out_path: where to write; defaults to reports/<strategy>_<ts>/robustness_tearsheet.html
    """
    ts = datetime.now()
    if out_path is None:
        out_path = Path("reports") / f"{backtest_result.strategy}_{ts.strftime('%Y-%m-%d_%H%M%S')}" / "robustness_tearsheet.html"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    m = backtest_result.metrics
    universe_str = ", ".join(sorted(universe.keys())) if universe else "see config"

    # Verdict label
    verdict_label = "UNKNOWN"
    if robustness_result is not None:
        verdict_label = robustness_result.verdict.verdict
    else:
        try:
            from ..engines.dsr import classify_dsr, deflated_sharpe_ratio
            import math
            r = backtest_result.daily_returns()
            if r is not None and len(r) >= 10:
                p = deflated_sharpe_ratio(r.values, n_trials=optuna_result.n_trials if optuna_result else 1)
                if not math.isnan(p):
                    verdict_label = classify_dsr(p).upper()
        except Exception:
            pass

    # Build the sequential sections
    sections: list[str] = []

    # Section: link to QuantStats full HTML if present
    if quantstats_link:
        sections.append(
            '<div class="section linkrow">'
            f'Full QuantStats interactive tearsheet: '
            f'<a href="{quantstats_link}" target="_blank">{quantstats_link}</a>'
            '</div>'
        )

    # Section: QuantStats metric panel
    try:
        from .tearsheet import compute_quantstats_metrics
        qs_metrics = compute_quantstats_metrics(backtest_result)
    except Exception:
        qs_metrics = {}
    sections.append(
        '<div class="section">'
        f'<h2>QuantStats metrics ({len(qs_metrics)})</h2>'
        + _quantstats_metrics_section(qs_metrics)
        + '</div>'
    )

    # Section: verdict signal table
    sections.append(
        '<div class="section">'
        f'<h2>Robustness verdict — {verdict_label}</h2>'
        + _verdict_table(robustness_result)
        + '</div>'
    )

    # Section: full robustness charts (reused from dashboard.tabs.robustness_tab)
    if robustness_result is not None:
        from ..dashboard.tabs import robustness_tab as _rob_tab
        rob_html = _rob_tab(backtest_result, wf=wf_result,
                             opt=optuna_result, robustness=robustness_result)
        sections.append(
            '<div class="section">'
            '<h2>Robustness charts</h2>'
            + rob_html
            + '</div>'
        )
    else:
        sections.append(
            '<div class="section"><h2>Robustness charts</h2>'
            '<div class="note">Pass --robustness on tradelab run to populate this section.</div>'
            '</div>'
        )

    # Footer
    data_hash = hash_universe(universe) if universe else None
    config_hash = hash_config(backtest_result.params)
    footer_text = render_footer(data_hash=data_hash, config_hash=config_hash).replace("\n", "<br>")

    html = _HTML.format(
        title=f"{backtest_result.strategy} — robustness tearsheet",
        verdict=verdict_label,
        net_pnl=m.net_pnl,
        pct_return=m.pct_return,
        trades=m.total_trades,
        win_rate=m.win_rate,
        pf=m.profit_factor,
        sharpe=m.sharpe_ratio,
        max_dd=m.max_drawdown_pct,
        start=backtest_result.start_date,
        end=backtest_result.end_date,
        universe=universe_str,
        sections="\n".join(sections),
        footer_html=footer_text,
    )

    out_path.write_text(html, encoding="utf-8")
    return out_path
