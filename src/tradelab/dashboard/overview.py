"""Portfolio overview page: one row per registered strategy, showing its
latest run. Answers "where does my whole strategy portfolio stand right now"
in one URL.

Unlike ``index.py`` which pivots on *runs*, this pivots on *strategies* —
so a strategy that's been run 20 times only shows up once here, with its
most-recent metrics.
"""
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..audit.history import DEFAULT_DB_PATH, HistoryRow, list_runs
from ..config import get_config
from ._theme import THEME_CSS
from .index import (
    _duration_badge,
    _load_result,
    _load_return_distribution,
    _load_verdict_signals,
    _pill_class,
    _resolve_run_folder,
    _sparkline_svg,
)


def _latest_row_per_strategy(db_path: Optional[Path] = None) -> dict[str, HistoryRow]:
    """Walk the audit DB newest-first, keep the first row per strategy."""
    db_path = db_path or DEFAULT_DB_PATH
    rows = list_runs(limit=5000, db_path=db_path)
    latest: dict[str, HistoryRow] = {}
    for r in rows:
        if r.strategy_name and r.strategy_name not in latest:
            latest[r.strategy_name] = r
    return latest


def _strategy_row(
    name: str,
    entry,
    latest_row: Optional[HistoryRow],
    reports_dir: Path,
) -> dict:
    """Build a single strategy's overview row."""
    folder = None
    result = None
    spark = ""
    duration = ""
    verdict = "NEVER RUN"
    verdict_html = (
        '<span class="v-pill v-unknown">NEVER RUN</span>'
    )
    last_when = "—"
    metrics = {k: "—" for k in ("trades", "pf", "ret_pct", "max_dd", "win_rate",
                                  "worst_regime_pf", "regime_spread", "exp_ret_ann")}
    rel_dashboard = ""

    if latest_row is not None:
        folder = _resolve_run_folder(latest_row, reports_dir)
        result = _load_result(folder) if folder else None
        last_when = (latest_row.timestamp_utc or "")[:16].replace("T", " ")
        verdict = (latest_row.verdict or "UNKNOWN").upper()

        signals = _load_verdict_signals(folder) if folder else []
        fragile = [s for s in signals if s["outcome"] == "fragile"]
        if fragile:
            tooltip = "Why {v}:\n".format(v=verdict) + "\n".join(
                f"- [{s['name']}] {s['reason']}" for s in fragile
            )
            verdict_html = (
                f'<span class="v-pill {_pill_class(verdict)}" '
                f'title="{html.escape(tooltip, quote=True)}">'
                f'{html.escape(verdict)} <span class="v-why">ⓘ</span></span>'
            )
        else:
            verdict_html = (
                f'<span class="v-pill {_pill_class(verdict)}">'
                f'{html.escape(verdict)}</span>'
            )

        if result is not None:
            spark = _sparkline_svg(result.equity_curve)
            duration = _duration_badge(result.start_date, result.end_date)
            m = result.metrics
            metrics = {
                "trades": str(m.total_trades),
                "pf": f"{m.profit_factor:.2f}",
                "ret_pct": f"{m.pct_return:.1f}",
                "max_dd": f"{m.max_drawdown_pct:.1f}",
                "win_rate": f"{m.win_rate:.1f}",
                "worst_regime_pf": "—",
                "regime_spread": "—",
                "exp_ret_ann": "—",
            }
            rb = getattr(result, "regime_breakdown", None) or {}
            pfs = [r.get("pf", 0.0) for r in rb.values()
                   if r.get("n_trades", 0) >= 5 and r.get("pf", 0) > 0]
            if len(pfs) >= 2:
                lo, hi = min(pfs), max(pfs)
                metrics["worst_regime_pf"] = f"{lo:.2f}"
                if hi > 0:
                    metrics["regime_spread"] = f"{(lo / hi):.2f}"

        # Expected annual return (from MC)
        rd = _load_return_distribution(folder) if folder else {}
        if rd and "annual_p50" in rd:
            metrics["exp_ret_ann"] = f"{rd['annual_p50']:+.1f}"

        if folder is not None:
            try:
                rel = str(folder.resolve().relative_to(reports_dir.resolve()))
                rel_dashboard = f"{rel.replace(chr(92), '/')}/dashboard.html"
            except ValueError:
                rel_dashboard = f"{folder.resolve()}/dashboard.html".replace("\\", "/")

    return {
        "name": name,
        "status": entry.status,
        "description": entry.description or "",
        "verdict": verdict,
        "verdict_html": verdict_html,
        "last_when": last_when,
        "trades": metrics["trades"],
        "pf": metrics["pf"],
        "ret_pct": metrics["ret_pct"],
        "max_dd": metrics["max_dd"],
        "win_rate": metrics["win_rate"],
        "worst_regime_pf": metrics["worst_regime_pf"],
        "regime_spread": metrics["regime_spread"],
        "exp_ret_ann": metrics["exp_ret_ann"],
        "sparkline_svg": spark,
        "duration": duration,
        "rel_dashboard": rel_dashboard,
        "has_run": latest_row is not None,
    }


def _render_html(rows: list[dict]) -> str:
    total = len(rows)
    with_runs = sum(1 for r in rows if r["has_run"])
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Status summary counts
    by_verdict: dict[str, int] = {}
    for r in rows:
        v = r["verdict"] if r["has_run"] else "NEVER RUN"
        by_verdict[v] = by_verdict.get(v, 0) + 1
    summary_chips = " ".join(
        f'<span class="chip v-{ (_pill_class(k) if k != "NEVER RUN" else "unknown").replace("v-", "") }">'
        f'{html.escape(k)} · {v}</span>'
        for k, v in sorted(by_verdict.items())
    )

    # Build rows HTML
    body_rows = []
    for r in rows:
        dash_cell = (
            f'<a href="{r["rel_dashboard"]}">open</a>'
            if r["rel_dashboard"] else
            '<span class="tl-muted">—</span>'
        )
        status_cell = f'<span class="status s-{r["status"]}">{html.escape(r["status"])}</span>'
        equity_cell = (
            f'<div class="tl-equity-cell">{r["sparkline_svg"]}'
            f'{("<span class=\"tl-duration\">" + r["duration"] + "</span>") if r["duration"] else ""}</div>'
            if r["sparkline_svg"] else '<span class="tl-muted">—</span>'
        )
        desc = html.escape(r["description"])
        body_rows.append(f"""
<tr>
  <td class="strategy">{html.escape(r['name'])}<div class="desc">{desc}</div></td>
  <td>{status_cell}</td>
  <td>{r['verdict_html']}</td>
  <td class="when">{r['last_when']}</td>
  <td class="num">{r['trades']}</td>
  <td class="num">{r['pf']}</td>
  <td class="num">{r['win_rate']}</td>
  <td class="num">{r['ret_pct']}</td>
  <td class="num">{r['max_dd']}</td>
  <td class="num" title="Worst-regime PF">{r['worst_regime_pf']}</td>
  <td class="num" title="Worst/best regime PF ratio">{r['regime_spread']}</td>
  <td class="num" title="Median annualized return from MC bootstrap">{r['exp_ret_ann']}</td>
  <td>{equity_cell}</td>
  <td>{dash_cell}</td>
</tr>""")

    page_css = r"""
header { padding: 20px 28px 12px; border-bottom: 1px solid var(--border); }
h1 { margin: 0; font-size: 22px; font-weight: 600; color: var(--fg); }
.sub { color: var(--fg-muted); margin-top: 4px; font-size: 12px; }
.chips { margin-top: 10px; display: flex; flex-wrap: wrap; gap: 6px; }
.chip { padding: 4px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; }
thead th { position: sticky; top: 0; }
td.strategy .desc {
  font-weight: 400; color: var(--fg-muted); font-size: 12px; margin-top: 2px;
}
.tl-muted { color: var(--fg-muted); }
"""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>tradelab - portfolio overview</title>
<style>
{THEME_CSS}
{page_css}
</style>
</head>
<body>
<header>
  <h1>tradelab - portfolio overview</h1>
  <p class="sub">{with_runs} of {total} strategies have run - regenerated {now} -
     <a href="index.html">full run history</a>
  </p>
  <div class="chips">{summary_chips}</div>
</header>
<table>
<thead><tr>
  <th>Strategy</th>
  <th>Status</th>
  <th>Verdict</th>
  <th>Last run</th>
  <th class="num">Trades</th>
  <th class="num">PF</th>
  <th class="num">Win%</th>
  <th class="num">Ret%</th>
  <th class="num">MaxDD%</th>
  <th class="num">Worst-Reg PF</th>
  <th class="num">Reg Spread</th>
  <th class="num">Exp Ret % (ann)</th>
  <th>Equity</th>
  <th></th>
</tr></thead>
<tbody>{''.join(body_rows)}</tbody>
</table>
</body>
</html>
"""


def build_overview(
    db_path: Optional[Path] = None,
    reports_dir: Optional[Path] = None,
) -> Path:
    """Generate ``reports/overview.html`` — one row per registered strategy."""
    cfg = get_config()
    reports_dir = Path(reports_dir) if reports_dir else Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)

    latest_map = _latest_row_per_strategy(db_path)
    rows = []
    for name, entry in cfg.strategies.items():
        rows.append(_strategy_row(name, entry, latest_map.get(name), reports_dir))

    # Sort: ported strategies with runs first, then canaries/other
    def sort_key(r):
        run_first = 0 if r["has_run"] else 1
        status_order = {"ported": 0, "registered": 1, "scaffold": 2,
                         "pending": 3, "archived": 4, "canary": 5}.get(r["status"], 6)
        return (run_first, status_order, r["name"])
    rows.sort(key=sort_key)

    html_str = _render_html(rows)
    out = reports_dir / "overview.html"
    out.write_text(html_str, encoding="utf-8")
    return out
