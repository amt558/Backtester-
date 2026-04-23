"""Cross-run strategy comparison report.

Loads two or more run folders (each containing a ``backtest_result.json`` that
``cli_run.run`` writes at the end of a run), builds a multi-column returns
DataFrame, and emits a single HTML page that combines:

  - A tradelab-native header: side-by-side metrics grid, verdict badges, links
    back to each run's full dashboard.
  - A QuantStats multi-strategy tearsheet body: overlaid equity curves,
    drawdown comparison, monthly heatmaps, rolling Sharpe, distribution plots.

Charts first: the overlaid equity curve and drawdown panels are the headline,
numbers are supporting.
"""
from __future__ import annotations

import warnings
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from ..results import BacktestResult
from ._theme import THEME_CSS


RESULT_FILE_NAME = "backtest_result.json"


class CompareError(Exception):
    pass


def _load_run(run_path: Path) -> BacktestResult:
    """Load a run folder's BacktestResult. Raises CompareError with a clear
    message if the folder predates JSON persistence."""
    run_path = Path(run_path)
    if not run_path.exists():
        raise CompareError(f"Run folder not found: {run_path}")
    jf = run_path / RESULT_FILE_NAME
    if not jf.exists():
        raise CompareError(
            f"{run_path.name}: no {RESULT_FILE_NAME} — this run predates the "
            f"JSON persistence feature. Re-run the strategy to enable compare."
        )
    return BacktestResult.model_validate_json(jf.read_text(encoding="utf-8"))


def _column_label(result: BacktestResult, run_path: Path) -> str:
    """Unique, human-readable column label: ``{strategy}__{run_folder_stem}``.

    The folder stem usually already contains a timestamp (e.g.
    ``s2_pocket_pivot_2026-04-19_173142``), so the label disambiguates
    multiple runs of the same strategy without being excessively long.
    """
    return f"{result.strategy}__{run_path.name}"


def _metrics_row(result: BacktestResult) -> dict:
    m = result.metrics
    row = {
        "Strategy": result.strategy,
        "Window": f"{result.start_date} -> {result.end_date}",
        "Trades": m.total_trades,
        "Win %": f"{m.win_rate:.1f}",
        "PF": f"{m.profit_factor:.2f}",
        "Ann Ret %": f"{m.annual_return:.1f}",
        "Max DD %": f"{m.max_drawdown_pct:.1f}",
        "Sharpe": f"{m.sharpe_ratio:.2f}",
        "Net P&L": f"${m.net_pnl:,.0f}",
    }

    # Regime summary (worst PF / spread) if available
    rb = getattr(result, "regime_breakdown", None) or {}
    pfs = [r.get("pf", 0.0) for r in rb.values()
           if r.get("n_trades", 0) >= 5 and r.get("pf", 0) > 0]
    if len(pfs) >= 2:
        lo, hi = min(pfs), max(pfs)
        row["Worst-Reg PF"] = f"{lo:.2f}"
        row["Reg Spread"] = f"{(lo / hi):.2f}" if hi > 0 else "-"
    else:
        row["Worst-Reg PF"] = "-"
        row["Reg Spread"] = "-"
    return row


def _render_header_html(results: list[BacktestResult], run_paths: list[Path]) -> str:
    """Tradelab-native header: metrics grid + links. Rendered at the top of
    the compare page, above QuantStats' multi-strategy tearsheet."""
    rows = [_metrics_row(r) for r in results]
    cols = list(rows[0].keys())

    # Find best/worst per numeric column for subtle highlighting
    def _num(v):
        try:
            return float(str(v).replace(",", "").replace("$", "").replace("%", ""))
        except (ValueError, AttributeError):
            return None

    highlights = {}
    for col in ("Trades", "Win %", "PF", "Ann Ret %", "Sharpe", "Net P&L",
                 "Worst-Reg PF", "Reg Spread"):
        if col not in rows[0]:
            continue
        vals = [_num(r[col]) for r in rows]
        if all(v is not None for v in vals) and len(set(vals)) > 1:
            highlights[col] = {"best": max(vals), "worst": min(vals)}
    # For Max DD, lower-magnitude (closer to 0) is better
    dd_vals = [_num(r["Max DD %"]) for r in rows]
    if all(v is not None for v in dd_vals) and len(set(dd_vals)) > 1:
        highlights["Max DD %"] = {"best": max(dd_vals), "worst": min(dd_vals)}

    header_cells = "".join(f"<th>{c}</th>" for c in cols)
    body_rows = []
    for r, rp in zip(rows, run_paths):
        cells = []
        for c in cols:
            v = r[c]
            cls = ""
            h = highlights.get(c)
            if h is not None:
                nv = _num(v)
                if nv == h["best"]:
                    cls = "best"
                elif nv == h["worst"]:
                    cls = "worst"
            cells.append(f'<td class="{cls}">{v}</td>')
        link = f'<a href="{rp.name}/dashboard.html">open run</a>'
        body_rows.append(f'<tr>{"".join(cells)}<td>{link}</td></tr>')

    metrics_table = (
        '<table class="tl-metrics">'
        f"<thead><tr>{header_cells}<th></th></tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table>"
    )

    subtitle = f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · {len(results)} runs"

    return f"""
<div class="tl-compare-header">
  <h1>tradelab — strategy comparison</h1>
  <p class="tl-subtitle">{subtitle}</p>
  {metrics_table}
  <p class="tl-note">
    Equity curves, drawdowns, monthly returns, and rolling metrics below are
    produced by QuantStats. Green = best per column, red = worst.
  </p>
</div>
<style>
  .tl-compare-header {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    padding: 24px; max-width: 1200px; margin: 0 auto;
    color: var(--fg);
  }}
  .tl-compare-header h1 {{ margin: 0 0 4px 0; font-size: 24px; color: var(--fg); }}
  .tl-subtitle {{ color: var(--fg-muted); margin: 0 0 16px 0; font-size: 13px; }}
  .tl-metrics {{ width: 100%; border-collapse: collapse; font-size: 13px;
                 background: var(--bg-panel); border-radius: 6px; overflow: hidden; }}
  .tl-metrics th, .tl-metrics td {{
    padding: 8px 12px; border-bottom: 1px solid var(--border-soft);
    text-align: right;
  }}
  .tl-metrics th:first-child, .tl-metrics td:first-child {{
    text-align: left; font-weight: 600;
  }}
  .tl-metrics thead th {{
    background: var(--bg-header); color: var(--fg-muted);
    font-weight: 600; font-size: 12px;
  }}
  .tl-metrics td.best  {{ color: var(--win);  font-weight: 600; }}
  .tl-metrics td.worst {{ color: var(--loss); }}
  .tl-metrics a {{ color: var(--accent); text-decoration: none; font-size: 12px; }}
  .tl-note {{ color: var(--fg-muted); font-size: 12px; margin-top: 12px; font-style: italic; }}
  /* QuantStats body overrides — force the dark background/text to propagate
     through its built-in tables and text so the page doesn't flip to light. */
  body {{ background: var(--bg) !important; color: var(--fg) !important; }}
  h1, h2, h3, h4, h5, h6, p, li, label {{ color: var(--fg); }}
  table {{ color: var(--fg); }}
  hr {{ border: none; border-top: 1px solid var(--border); margin: 32px auto; max-width: 1200px; }}
</style>
<hr>
"""


def _auto_benchmark_returns(
    results: list[BacktestResult], benchmark_symbol: str
) -> Optional[pd.Series]:
    """Try to load the benchmark symbol's daily returns over the union
    window of the provided runs. Returns None if unavailable.

    Uses the parquet cache via ``marketdata.download_symbols`` (Twelve Data).
    If the benchmark isn't cached, a cache hit will fail and this returns None.
    """
    try:
        from ..marketdata import download_symbols
        from ..config import get_config
    except Exception:
        return None
    try:
        cfg = get_config()
        data = download_symbols(
            [benchmark_symbol],
            start=cfg.defaults.data_start,
            end=cfg.defaults.data_end,
        )
    except Exception:
        return None
    df = data.get(benchmark_symbol)
    if df is None or "Date" not in df.columns or "Close" not in df.columns:
        return None
    s = df.set_index("Date")["Close"].sort_index()
    # Clip to the runs' overall window so qs doesn't show benchmark beyond data
    try:
        starts = [pd.Timestamp(r.start_date) for r in results]
        ends = [pd.Timestamp(r.end_date) for r in results]
        s = s.loc[(s.index >= min(starts)) & (s.index <= max(ends))]
    except Exception:
        pass
    rets = s.pct_change().dropna()
    rets.name = benchmark_symbol
    return rets if not rets.empty else None


def build_compare_report(
    run_paths: list[Path],
    out_path: Optional[Path] = None,
    benchmark_returns: Optional[pd.Series] = None,
    benchmark_symbol: str = "SPY",
    auto_benchmark: bool = True,
    title: Optional[str] = None,
) -> Path:
    """Render a cross-run comparison HTML.

    Args:
        run_paths: list of 2+ run folder paths (each must contain
            ``backtest_result.json``).
        out_path: output HTML path. Defaults to ``reports/compare_{ts}.html``.
        benchmark_returns: explicit benchmark series for QuantStats. If
            provided, takes precedence over ``auto_benchmark``.
        benchmark_symbol: symbol to load when ``auto_benchmark`` is True
            (default SPY).
        auto_benchmark: when True and ``benchmark_returns`` is None, try to
            load the benchmark symbol's close via ``marketdata.download_symbols``
            (parquet cache) and pass it to QuantStats.
        title: optional HTML title.

    Returns:
        Path to the rendered HTML.
    """
    if len(run_paths) < 2:
        raise CompareError("compare requires at least two run folders")

    run_paths = [Path(p) for p in run_paths]
    results = [_load_run(p) for p in run_paths]

    # Build multi-column returns DataFrame. Columns labeled uniquely so
    # quantstats doesn't collapse same-strategy runs onto one series.
    series_list = []
    labels = []
    for res, rp in zip(results, run_paths):
        r = res.daily_returns()
        if r is None or r.empty:
            raise CompareError(f"{rp.name}: empty equity curve; cannot compare")
        r.name = _column_label(res, rp)
        series_list.append(r)
        labels.append(r.name)

    returns_df = pd.concat(series_list, axis=1).sort_index()

    # Resolve benchmark
    if benchmark_returns is None and auto_benchmark:
        benchmark_returns = _auto_benchmark_returns(results, benchmark_symbol)

    # Resolve output path
    if out_path is None:
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        # Put alongside the runs, so relative links to each run's dashboard work
        out_path = Path("reports") / f"compare_{ts}.html"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    title = title or f"tradelab compare — {len(results)} runs"

    try:
        import matplotlib
        matplotlib.use("Agg")
        import quantstats as qs
    except ImportError as e:
        raise CompareError(
            "quantstats not installed. Run: pip install quantstats"
        ) from e

    # QuantStats emits a lot of noise from its seaborn/deprecation surfaces.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        qs.reports.html(
            returns_df,
            benchmark=benchmark_returns,
            output=str(out_path),
            title=title,
            download_filename=out_path.name,
        )

    # Prepend tradelab theme CSS + native header into the QuantStats HTML
    # so the whole page picks up our dark (CC-matched) colors.
    header = _render_header_html(results, run_paths)
    theme_head_inject = f"<style>{THEME_CSS}</style>"
    html = out_path.read_text(encoding="utf-8")
    head_close = html.lower().find("</head>")
    if head_close >= 0:
        html = html[:head_close] + theme_head_inject + html[head_close:]
    body_open = html.find("<body")
    if body_open >= 0:
        close = html.find(">", body_open) + 1
        html = html[:close] + header + html[close:]
    out_path.write_text(html, encoding="utf-8")

    return out_path
