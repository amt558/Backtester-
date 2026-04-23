"""Static home page for tradelab.

Reads the audit DB (``audit.list_runs``) and renders a single
``reports/index.html`` that lists every run with:

  - sortable columns (click header to sort)
  - verdict filter pills (ALL / ROBUST / MARGINAL / FRAGILE / INCONCLUSIVE)
  - strategy dropdown + text search
  - inline SVG equity sparkline per row (loaded from each run's
    ``backtest_result.json`` if present)
  - multi-select checkboxes + "Copy compare command" button that puts a
    ready-to-paste ``tradelab compare <paths>`` on the clipboard

Static HTML only — no server, no external CDN for JS. Plotly isn't needed
here (sparklines are plain SVG). Auto-regenerated at the end of every
``tradelab run``; can be rebuilt on demand with ``tradelab rebuild-index``.
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..audit.history import DEFAULT_DB_PATH, HistoryRow, list_runs
from ..results import BacktestResult
from ._theme import THEME_CSS


SPARK_W = 160
SPARK_H = 32


def _load_return_distribution(folder: Path) -> dict:
    """Best-effort: read the MC return distribution from a run folder."""
    jf = folder / "robustness_result.json"
    if not jf.exists():
        return {}
    try:
        data = json.loads(jf.read_text(encoding="utf-8"))
    except Exception:
        return {}
    mc = data.get("monte_carlo") or {}
    return mc.get("return_distribution") or {}


def _load_verdict_signals(folder: Path) -> list[dict]:
    """Best-effort: read ``robustness_result.json`` and return its fragile
    signal list. We parse as raw JSON (not through the Pydantic class)
    because ``RobustnessSuiteResult`` pulls in many nested types that may
    not be worth importing for a lightweight index page."""
    jf = folder / "robustness_result.json"
    if not jf.exists():
        return []
    try:
        data = json.loads(jf.read_text(encoding="utf-8"))
    except Exception:
        return []
    signals = (data.get("verdict") or {}).get("signals") or []
    out: list[dict] = []
    for s in signals:
        if not isinstance(s, dict):
            continue
        out.append({
            "name": s.get("name") or "",
            "outcome": (s.get("outcome") or "").lower(),
            "reason": s.get("reason") or "",
        })
    return out


def _duration_badge(start_date: str, end_date: str) -> str:
    """Render a compact duration label like '2.0y' or '6mo' or '12d'."""
    try:
        start = datetime.fromisoformat(start_date[:10])
        end = datetime.fromisoformat(end_date[:10])
    except Exception:
        return ""
    days = max(0, (end - start).days)
    if days >= 365:
        years = days / 365.25
        return f"{years:.1f}y"
    if days >= 60:
        months = days / 30.44
        return f"{months:.0f}mo"
    return f"{days}d"


def _resolve_run_folder(row: HistoryRow, reports_dir: Path) -> Optional[Path]:
    """Best-effort: map a ``report_card_html_path`` back to its run folder."""
    if not row.report_card_html_path:
        return None
    p = Path(row.report_card_html_path)
    if not p.is_absolute():
        # Stored path may be relative to the working dir at record time
        cand = (reports_dir.parent / p).resolve() if (reports_dir.parent / p).exists() else p
        p = cand
    folder = p.parent
    return folder if folder.exists() else None


def _load_result(folder: Path) -> Optional[BacktestResult]:
    jf = folder / "backtest_result.json"
    if not jf.exists():
        return None
    try:
        return BacktestResult.model_validate_json(jf.read_text(encoding="utf-8"))
    except Exception:
        return None


def _sparkline_svg(equity_curve: list[dict], width: int = SPARK_W,
                    height: int = SPARK_H) -> str:
    """Render an inline SVG equity sparkline. Green if up, red if down."""
    if not equity_curve or len(equity_curve) < 2:
        return ""
    eqs = [float(p["equity"]) for p in equity_curve]
    n = len(eqs)
    mx = max(eqs)
    mn = min(eqs)
    rng = (mx - mn) or 1.0
    # Build path
    coords = []
    for i, eq in enumerate(eqs):
        x = i / (n - 1) * (width - 2) + 1
        y = height - 1 - (eq - mn) / rng * (height - 2)
        coords.append(f"{x:.1f},{y:.1f}")
    path = f"M{coords[0]} " + " ".join(f"L{c}" for c in coords[1:])
    color = "#22c55e" if eqs[-1] >= eqs[0] else "#ef4444"
    # Baseline at start-equity to give eye a reference line
    start_y = height - 1 - (eqs[0] - mn) / rng * (height - 2)
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'class="tl-spark" role="img" aria-label="equity curve">'
        f'<line x1="1" y1="{start_y:.1f}" x2="{width - 1}" y2="{start_y:.1f}" '
        f'stroke="#2a2d38" stroke-width="0.5" stroke-dasharray="2,2"/>'
        f'<path d="{path}" fill="none" stroke="{color}" stroke-width="1.25" '
        f'stroke-linejoin="round"/>'
        f"</svg>"
    )


_VERDICT_CLASSES = {
    "ROBUST": "v-robust",
    "MARGINAL": "v-marginal",
    "FRAGILE": "v-fragile",
    "INCONCLUSIVE": "v-inconclusive",
    "UNEVALUATED": "v-unknown",
    "UNKNOWN": "v-unknown",
}


def _pill_class(verdict: str) -> str:
    return _VERDICT_CLASSES.get(verdict.upper(), "v-unknown")


def _verdict_pill(verdict: Optional[str]) -> str:
    v = (verdict or "UNKNOWN").upper()
    return f'<span class="v-pill {_pill_class(v)}">{html.escape(v)}</span>'


def _format_timestamp(iso: str) -> str:
    """Make ISO 8601 UTC readable: 2026-04-19 22:13:08 UTC."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso[:16] if iso else ""


def _enrich_row(row: HistoryRow, reports_dir: Path) -> dict:
    """Build a single row dict for the template."""
    folder = _resolve_run_folder(row, reports_dir)
    result = _load_result(folder) if folder else None

    spark = ""
    duration = ""
    metrics = {
        "trades": "—",
        "pf": "—",
        "ret_pct": "—",
        "max_dd": "—",
        "win_rate": "—",
        "worst_regime_pf": "—",
        "regime_spread": "—",
        "exp_ret_ann": "—",
    }
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
        # Regime summary — worst-regime PF + spread ratio (lo/hi) across regimes
        rb = getattr(result, "regime_breakdown", None) or {}
        pfs = [r.get("pf", 0.0) for r in rb.values()
               if r.get("n_trades", 0) >= 5 and r.get("pf", 0) > 0]
        if len(pfs) >= 2:
            lo, hi = min(pfs), max(pfs)
            metrics["worst_regime_pf"] = f"{lo:.2f}"
            if hi > 0:
                metrics["regime_spread"] = f"{(lo / hi):.2f}"
    rd = _load_return_distribution(folder) if folder else {}
    if rd and "annual_p50" in rd:
        metrics["exp_ret_ann"] = f"{rd['annual_p50']:+.1f}"

    # Fragile-signal reasons — surfaced as a tooltip on the verdict pill
    # so you can see *why* a run failed without opening it.
    signals = _load_verdict_signals(folder) if folder else []
    fragile = [s for s in signals if s["outcome"] == "fragile"]
    fragile_names = [s["name"] for s in fragile]

    verdict_str = (row.verdict or "UNKNOWN").upper()
    if fragile:
        tooltip = "Why {v}:\n".format(v=verdict_str) + "\n".join(
            f"- [{s['name']}] {s['reason']}" for s in fragile
        )
        verdict_html = (
            f'<span class="v-pill {_pill_class(verdict_str)}" '
            f'title="{html.escape(tooltip, quote=True)}">'
            f'{html.escape(verdict_str)} <span class="v-why">ⓘ</span></span>'
        )
    else:
        verdict_html = _verdict_pill(row.verdict)

    # Relative path from index.html (which sits in reports/) to the run folder
    rel_folder = ""
    rel_dashboard = ""
    if folder is not None:
        try:
            rel_folder = str(folder.resolve().relative_to(reports_dir.resolve())).replace("\\", "/")
            rel_dashboard = f"{rel_folder}/dashboard.html"
        except ValueError:
            rel_folder = str(folder.resolve()).replace("\\", "/")
            rel_dashboard = f"{rel_folder}/dashboard.html"

    return {
        "run_id": row.run_id,
        "strategy": row.strategy_name or "",
        "when": _format_timestamp(row.timestamp_utc or ""),
        "when_sortkey": row.timestamp_utc or "",
        "verdict": verdict_str,
        "verdict_html": verdict_html,
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
        "fragile_names": fragile_names,
        "rel_folder": rel_folder,
        "rel_dashboard": rel_dashboard,
        "has_folder": folder is not None,
        "has_result": result is not None,
    }


def _render_html(rows: list[dict], strategies: list[str], storage_url: str) -> str:
    """Render the full index.html string."""
    # Unique strategies for filter dropdown
    strategies_sorted = sorted(set(r["strategy"] for r in rows if r["strategy"]))

    # Compact JSON blob embedded for client-side sort/filter
    rows_json = json.dumps([{
        "run_id": r["run_id"],
        "strategy": r["strategy"],
        "when": r["when"],
        "when_sortkey": r["when_sortkey"],
        "verdict": r["verdict"],
        "trades": r["trades"],
        "pf": r["pf"],
        "ret_pct": r["ret_pct"],
        "max_dd": r["max_dd"],
        "win_rate": r["win_rate"],
        "worst_regime_pf": r.get("worst_regime_pf", "—"),
        "regime_spread": r.get("regime_spread", "—"),
        "exp_ret_ann": r.get("exp_ret_ann", "—"),
        "rel_folder": r["rel_folder"],
        "rel_dashboard": r["rel_dashboard"],
        "has_folder": r["has_folder"],
        "sparkline_svg": r["sparkline_svg"],
        "verdict_html": r["verdict_html"],
        "duration": r.get("duration", ""),
        "fragile_names": r.get("fragile_names", []),
    } for r in rows], separators=(",", ":"))

    strategy_options = "".join(
        f'<option value="{html.escape(s)}">{html.escape(s)}</option>' for s in strategies_sorted
    )

    # Failure-mode filter options — union of fragile signal names across rows
    fm_set: set[str] = set()
    for r in rows:
        fm_set.update(r.get("fragile_names", []))
    failure_options = "".join(
        f'<option value="{html.escape(fm)}">{html.escape(fm)}</option>'
        for fm in sorted(fm_set)
    )

    total = len(rows)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Canary-health quick signal
    canary_names = {"rand_canary", "overfit_canary", "leak_canary", "survivor_canary"}
    canary_rows = [r for r in rows if r["strategy"] in canary_names]
    bad_canaries = [r for r in canary_rows if r["verdict"] == "ROBUST"]
    canary_banner = ""
    if bad_canaries:
        names = ", ".join(sorted(set(r["strategy"] for r in bad_canaries)))
        canary_banner = (
            f'<div class="tl-alert">⚠ Canary alert: {html.escape(names)} '
            f'returned ROBUST. Tool trust is degraded — run <code>tradelab doctor</code>.</div>'
        )

    # Page-specific CSS on top of the shared theme (variables + shared
    # components are in THEME_CSS; only layout/feature-specific rules here).
    page_css = r"""
header { padding: 20px 28px 12px; border-bottom: 1px solid var(--border); }
h1 { margin: 0; font-size: 22px; font-weight: 600; color: var(--fg); }
.tl-sub { color: var(--fg-muted); margin-top: 4px; font-size: 12px; }
.tl-toolbar {
  display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
  padding: 12px 28px; border-bottom: 1px solid var(--border);
  background: var(--bg-header);
}
.tl-toolbar input { width: 200px; }
.tl-toolbar .tl-count { margin-left: auto; color: var(--fg-muted); font-size: 12px; }
.tl-pills button {
  padding: 5px 10px; margin-right: 4px; font-size: 12px;
}
.tl-pills button.active {
  background: var(--accent); color: #fff; border-color: var(--accent);
}
.tl-compare-bar {
  padding: 10px 28px; background: var(--accent-soft);
  border-bottom: 1px solid var(--border);
  font-size: 13px; display: none; align-items: center; gap: 12px;
}
.tl-compare-bar.shown { display: flex; }
.tl-compare-bar button {
  padding: 6px 14px; background: var(--accent); color: #fff;
  border: 0; border-radius: 4px; font-size: 13px;
}
.tl-compare-bar button.secondary {
  background: var(--bg-panel); color: var(--fg); border: 1px solid var(--border);
}
#toast {
  position: fixed; top: 56px; right: 18px;
  background: var(--bg-panel); color: var(--fg);
  border: 1px solid var(--border);
  padding: 10px 16px; border-radius: 4px;
  opacity: 0; transition: opacity 0.2s;
  z-index: 999; font-size: 13px;
}
#toast.shown { opacity: 1; }
thead th {
  position: sticky; top: 0;
  cursor: pointer;
}
thead th.sort-asc::after { content: " \25B2"; color: var(--accent); font-size: 10px; }
thead th.sort-desc::after { content: " \25BC"; color: var(--accent); font-size: 10px; }
tbody tr.hidden { display: none; }
.tl-empty { padding: 60px 28px; text-align: center; color: var(--fg-muted); }
"""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>tradelab — all runs</title>
<style>
{THEME_CSS}
{page_css}
</style>
</head>
<body>
<header>
  <h1>tradelab — all runs</h1>
  <p class="tl-sub">
    {total} runs · regenerated {now} ·
    launch Optuna dashboard: <code>optuna-dashboard {html.escape(storage_url)}</code>
  </p>
</header>
{canary_banner}
<div class="tl-toolbar">
  <input id="q" type="search" placeholder="Search strategy…" autocomplete="off"/>
  <select id="strategy-filter">
    <option value="">All strategies</option>
    {strategy_options}
  </select>
  <select id="failure-filter" title="Filter rows that tripped this fragile signal">
    <option value="">All failure modes</option>
    {failure_options}
  </select>
  <span class="tl-pills" id="verdict-pills">
    <button data-v="" class="active">All</button>
    <button data-v="ROBUST">Robust</button>
    <button data-v="MARGINAL">Marginal</button>
    <button data-v="FRAGILE">Fragile</button>
    <button data-v="INCONCLUSIVE">Inconclusive</button>
  </span>
  <span class="tl-count" id="count"></span>
</div>
<div class="tl-compare-bar" id="cmpbar">
  <span id="cmpcount">0 selected</span>
  <button id="btn-copy">Copy compare command</button>
  <button id="btn-clear" class="secondary">Clear</button>
</div>
<table id="runs">
  <thead><tr>
    <th style="width: 32px;"><input type="checkbox" id="check-all"/></th>
    <th data-sort="strategy">Strategy</th>
    <th data-sort="when_sortkey">When</th>
    <th data-sort="verdict">Verdict</th>
    <th data-sort="trades" class="num">Trades</th>
    <th data-sort="pf" class="num">PF</th>
    <th data-sort="win_rate" class="num">Win%</th>
    <th data-sort="ret_pct" class="num">Ret%</th>
    <th data-sort="max_dd" class="num">MaxDD%</th>
    <th data-sort="worst_regime_pf" class="num" title="Smallest PF among regimes with 5+ trades (bull/chop/bear)">Worst-Regime PF</th>
    <th data-sort="regime_spread" class="num" title="Ratio of worst-regime PF to best-regime PF (<0.4 flags fragile)">Regime Spread</th>
    <th data-sort="exp_ret_ann" class="num" title="Median annualized return from Monte Carlo bootstrap — use for sizing">Exp Ret % (ann)</th>
    <th>Equity</th>
    <th></th>
  </tr></thead>
  <tbody id="rows"></tbody>
</table>
<div id="toast"></div>
<script>
const ROWS = {rows_json};
const $ = sel => document.querySelector(sel);
const tbody = $("#rows");
let sortCol = "when_sortkey";
let sortDir = "desc";
const selected = new Set();

function numeric(col) {{
  return ["trades", "pf", "win_rate", "ret_pct", "max_dd", "worst_regime_pf", "regime_spread", "exp_ret_ann"].includes(col);
}}
function parseNum(v) {{
  if (v === "—" || v == null) return null;
  const n = parseFloat(String(v).replace(/,/g, ""));
  return Number.isFinite(n) ? n : null;
}}
function compare(a, b, col, dir) {{
  if (numeric(col)) {{
    const na = parseNum(a[col]); const nb = parseNum(b[col]);
    if (na === null && nb === null) return 0;
    if (na === null) return 1;
    if (nb === null) return -1;
    return dir === "asc" ? na - nb : nb - na;
  }}
  const sa = (a[col] || "").toString();
  const sb = (b[col] || "").toString();
  return dir === "asc" ? sa.localeCompare(sb) : sb.localeCompare(sa);
}}

function render() {{
  const q = $("#q").value.trim().toLowerCase();
  const sf = $("#strategy-filter").value;
  const vf = document.querySelector("#verdict-pills .active").dataset.v;

  const ff = $("#failure-filter").value;
  let filtered = ROWS.filter(r => {{
    if (sf && r.strategy !== sf) return false;
    if (vf && r.verdict !== vf) return false;
    if (ff && !(r.fragile_names || []).includes(ff)) return false;
    if (q && !r.strategy.toLowerCase().includes(q)) return false;
    return true;
  }});
  filtered.sort((a, b) => compare(a, b, sortCol, sortDir));

  tbody.innerHTML = filtered.map(r => {{
    const checked = selected.has(r.run_id) ? "checked" : "";
    const openLink = r.has_folder && r.rel_dashboard
      ? `<a href="${{r.rel_dashboard}}">open</a>`
      : `<span class="tl-stale">missing</span>`;
    return `<tr data-id="${{r.run_id}}" data-folder="${{r.rel_folder}}">
      <td><input type="checkbox" class="row-check" ${{checked}} ${{r.has_folder ? "" : "disabled"}}/></td>
      <td class="strategy">${{r.strategy}}</td>
      <td class="when">${{r.when}}</td>
      <td>${{r.verdict_html}}</td>
      <td class="num">${{r.trades}}</td>
      <td class="num">${{r.pf}}</td>
      <td class="num">${{r.win_rate}}</td>
      <td class="num">${{r.ret_pct}}</td>
      <td class="num">${{r.max_dd}}</td>
      <td class="num">${{r.worst_regime_pf}}</td>
      <td class="num">${{r.regime_spread}}</td>
      <td class="num">${{r.exp_ret_ann}}</td>
      <td><div class="tl-equity-cell">${{r.sparkline_svg || ""}}${{r.duration ? `<span class="tl-duration">${{r.duration}}</span>` : ""}}</div></td>
      <td>${{openLink}}</td>
    </tr>`;
  }}).join("");
  $("#count").textContent = `${{filtered.length}} of ${{ROWS.length}}`;
  updateSortIndicators();
}}

function updateSortIndicators() {{
  document.querySelectorAll("thead th").forEach(th => {{
    th.classList.remove("sort-asc", "sort-desc");
    if (th.dataset.sort === sortCol) {{
      th.classList.add(sortDir === "asc" ? "sort-asc" : "sort-desc");
    }}
  }});
}}

document.querySelectorAll("thead th[data-sort]").forEach(th => {{
  th.addEventListener("click", () => {{
    const col = th.dataset.sort;
    if (sortCol === col) {{ sortDir = sortDir === "asc" ? "desc" : "asc"; }}
    else {{ sortCol = col; sortDir = numeric(col) || col === "when_sortkey" ? "desc" : "asc"; }}
    render();
  }});
}});
$("#q").addEventListener("input", render);
$("#strategy-filter").addEventListener("change", render);
$("#failure-filter").addEventListener("change", render);
document.querySelectorAll("#verdict-pills button").forEach(btn => {{
  btn.addEventListener("click", () => {{
    document.querySelectorAll("#verdict-pills button").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    render();
  }});
}});
tbody.addEventListener("change", e => {{
  if (!e.target.classList.contains("row-check")) return;
  const tr = e.target.closest("tr");
  const id = tr.dataset.id;
  if (e.target.checked) selected.add(id); else selected.delete(id);
  updateCompareBar();
}});
$("#check-all").addEventListener("change", e => {{
  const chk = e.target.checked;
  document.querySelectorAll(".row-check:not(:disabled)").forEach(cb => {{
    cb.checked = chk;
    const id = cb.closest("tr").dataset.id;
    if (chk) selected.add(id); else selected.delete(id);
  }});
  updateCompareBar();
}});

function updateCompareBar() {{
  const bar = $("#cmpbar");
  if (selected.size >= 1) bar.classList.add("shown"); else bar.classList.remove("shown");
  $("#cmpcount").textContent = `${{selected.size}} selected`;
}}
function folderPathsForSelected() {{
  const ids = Array.from(selected);
  return ids.map(id => {{
    const r = ROWS.find(x => x.run_id === id);
    return r && r.rel_folder ? `reports/${{r.rel_folder}}` : null;
  }}).filter(Boolean);
}}
function toast(msg) {{
  const t = $("#toast"); t.textContent = msg; t.classList.add("shown");
  setTimeout(() => t.classList.remove("shown"), 2000);
}}
$("#btn-copy").addEventListener("click", () => {{
  const paths = folderPathsForSelected();
  if (paths.length < 2) {{ toast("Select at least 2 runs to compare"); return; }}
  const cmd = "tradelab compare " + paths.map(p => `"${{p}}"`).join(" ");
  navigator.clipboard.writeText(cmd).then(
    () => toast(`Command copied (${{paths.length}} runs)`),
    () => toast("Clipboard blocked — see console"),
  );
  console.log(cmd);
}});
$("#btn-clear").addEventListener("click", () => {{
  selected.clear();
  document.querySelectorAll(".row-check").forEach(cb => cb.checked = false);
  $("#check-all").checked = false;
  updateCompareBar();
}});

if (ROWS.length === 0) {{
  document.querySelector("table").style.display = "none";
  const e = document.createElement("div");
  e.className = "tl-empty";
  e.innerHTML = "No runs yet. Run <code>tradelab run &lt;strategy&gt; --universe &lt;name&gt;</code> to populate.";
  document.body.appendChild(e);
}} else {{
  render();
}}
</script>
</body>
</html>
"""


def build_index(
    db_path: Optional[Path] = None,
    reports_dir: Optional[Path] = None,
    limit: int = 500,
) -> Path:
    """Generate ``reports/index.html`` from the audit DB."""
    db_path = db_path or DEFAULT_DB_PATH
    reports_dir = Path(reports_dir) if reports_dir else Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)

    rows = list_runs(limit=limit, db_path=db_path)
    enriched = [_enrich_row(r, reports_dir) for r in rows]

    # Build Optuna storage URL string for the dashboard launch hint — match
    # the convention in engines/_optuna_store.py without importing it (keeps
    # this module loadable even if the engine hasn't run yet).
    from ..config import get_config
    cfg = get_config()
    cache_dir = Path(cfg.paths.cache_dir).resolve()
    storage_url = f"sqlite:///{(cache_dir / 'optuna_studies.db').as_posix()}"

    strategies = sorted(set(r["strategy"] for r in enriched if r["strategy"]))
    html_str = _render_html(enriched, strategies, storage_url)
    out_path = reports_dir / "index.html"
    out_path.write_text(html_str, encoding="utf-8")
    return out_path
