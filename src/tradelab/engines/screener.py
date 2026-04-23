"""
Smart screener — find which symbols a strategy works best on.

Runs the strategy on each symbol INDIVIDUALLY (one symbol per backtest run),
then ranks the per-symbol results. Useful for:
  - Building a focused universe ("only run S2 on stocks where S2 actually has
    an edge")
  - Diagnosing per-symbol fragility (echoes LOSO, but starts from "1 stock at
    a time" rather than "drop 1 stock from N")
  - Quick exploration of a strategy on an unfamiliar universe
"""
from __future__ import annotations

import copy
import math
from typing import Optional

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from ..results import BacktestMetrics
from .backtest import run_backtest


class ScreenRow(BaseModel):
    """One symbol's screen result."""
    symbol: str
    metrics: BacktestMetrics
    composite_score: float


class ScreenResult(BaseModel):
    """Aggregate screener output, sorted descending by composite_score."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    strategy: str
    n_symbols: int
    rows: list[ScreenRow] = Field(default_factory=list)
    benchmark: str = "SPY"

    def top(self, n: int) -> list[str]:
        return [r.symbol for r in self.rows[:n]]

    def filter(self, min_trades: int = 5, min_pf: float = 1.0) -> "ScreenResult":
        kept = [r for r in self.rows
                if r.metrics.total_trades >= min_trades and r.metrics.profit_factor >= min_pf]
        return ScreenResult(
            strategy=self.strategy,
            n_symbols=len(kept),
            rows=kept,
            benchmark=self.benchmark,
        )


def _composite_score(m: BacktestMetrics, min_trades: int = 3) -> float:
    """
    Same shape as the Optuna default fitness:
        PF * sqrt(trades) * (1 - |DD|/100)

    Zero if too few trades. Negative if PF below 1 (i.e., a loser).
    """
    if m.total_trades < min_trades:
        return 0.0
    pf = m.profit_factor
    if pf <= 0 or not math.isfinite(pf):
        return 0.0
    pf_eff = min(pf, 10.0)
    if pf < 1.0:
        # Penalize losers — composite goes negative so they sort last
        return float(-1.0 * (1.0 / pf_eff) * math.sqrt(m.total_trades))
    dd_penalty = max(0.0, 1.0 - min(abs(m.max_drawdown_pct), 99.0) / 100.0)
    return float(pf_eff * math.sqrt(m.total_trades) * dd_penalty)


def run_screener(
    strategy_factory,
    enriched_data: dict,
    benchmark: str = "SPY",
    spy_close=None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    progress_cb=None,
) -> ScreenResult:
    """
    Run the strategy on each non-benchmark symbol individually.

    Args:
        strategy_factory: callable returning a fresh Strategy instance, or
            an already-instantiated Strategy (will be deep-copied per symbol).
            Using a factory is preferred for thread-safety later.
        enriched_data: enriched OHLCV universe dict (must include benchmark
            for RS computations).
        benchmark: symbol that won't be screened but stays available for RS.
        progress_cb: optional callable(symbol, idx, total) for progress UI.

    Returns:
        ScreenResult with per-symbol metrics + composite score, sorted desc.
    """
    if callable(strategy_factory) and not hasattr(strategy_factory, "params"):
        base_strategy = strategy_factory()
    else:
        base_strategy = strategy_factory

    symbols = [s for s in enriched_data.keys() if s != benchmark]
    rows: list[ScreenRow] = []
    total = len(symbols)

    for i, sym in enumerate(symbols, start=1):
        if progress_cb:
            try:
                progress_cb(sym, i, total)
            except Exception:
                pass

        # Build a 2-symbol mini-universe: benchmark + this symbol
        sub = {benchmark: enriched_data[benchmark], sym: enriched_data[sym]} \
            if benchmark in enriched_data else {sym: enriched_data[sym]}

        # Fresh strategy clone so per-symbol state doesn't leak between runs
        strat = copy.copy(base_strategy)
        strat.params = dict(base_strategy.params)

        try:
            bt = run_backtest(strat, sub,
                              start=start, end=end, spy_close=spy_close)
        except Exception:
            continue

        score = _composite_score(bt.metrics)
        rows.append(ScreenRow(symbol=sym, metrics=bt.metrics, composite_score=score))

    rows.sort(key=lambda r: r.composite_score, reverse=True)
    return ScreenResult(
        strategy=base_strategy.name,
        n_symbols=total,
        rows=rows,
        benchmark=benchmark,
    )


def render_screen_html(result: ScreenResult, out_path) -> None:
    """Render a sortable HTML page of the screen results."""
    from pathlib import Path
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows_html = []
    for r in result.rows:
        m = r.metrics
        cls_pf = "win" if m.profit_factor >= 1.0 else "loss"
        cls_score = "win" if r.composite_score > 0 else "loss"
        rows_html.append(
            f'<tr>'
            f'<td>{r.symbol}</td>'
            f'<td data-sort="{r.composite_score}" class="{cls_score}" style="text-align:right;">{r.composite_score:.2f}</td>'
            f'<td data-sort="{m.total_trades}" style="text-align:right;">{m.total_trades}</td>'
            f'<td data-sort="{m.profit_factor}" class="{cls_pf}" style="text-align:right;">{m.profit_factor:.2f}</td>'
            f'<td data-sort="{m.win_rate}" style="text-align:right;">{m.win_rate:.1f}%</td>'
            f'<td data-sort="{m.net_pnl}" style="text-align:right;">${m.net_pnl:,.0f}</td>'
            f'<td data-sort="{m.pct_return}" style="text-align:right;">{m.pct_return:.1f}%</td>'
            f'<td data-sort="{m.max_drawdown_pct}" style="text-align:right;">{m.max_drawdown_pct:.1f}%</td>'
            f'<td data-sort="{m.sharpe_ratio}" style="text-align:right;">{m.sharpe_ratio:.2f}</td>'
            f'</tr>'
        )

    from ..dashboard._theme import THEME_CSS
    # Escape THEME_CSS braces for the f-string host below
    theme_css_esc = THEME_CSS.replace("{", "{{").replace("}", "}}")

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{result.strategy} — screener</title>
<style>
{theme_css_esc}
.header {{
  padding: 20px 30px; background: var(--bg-header);
  border-bottom: 1px solid var(--border);
}}
.header h1 {{ margin: 0; font-size: 22px; color: var(--fg); }}
.header .sub {{ font-size: 13px; color: var(--fg-muted); margin-top: 4px; }}
.body {{ padding: 24px; max-width: 1200px; margin: 0 auto; }}
table {{
  border-collapse: collapse; width: 100%; font-size: 13px;
  background: var(--bg-panel); border: 1px solid var(--border);
  border-radius: var(--radius); overflow: hidden;
}}
th {{ cursor: pointer; user-select: none; }}
th:hover {{ background: var(--bg-hover); }}
.win  {{ color: var(--win);  font-weight: 600; }}
.loss {{ color: var(--loss); font-weight: 600; }}
</style></head><body>
<div class="header">
<h1>{result.strategy} — per-symbol screener</h1>
<div class="sub">
Composite score = PF * sqrt(trades) * (1 - |DD|/100). Click any column header to sort.
</div>
</div>
<div class="body">
<table id="t"><thead><tr>
<th>Symbol</th>
<th>Score</th>
<th>Trades</th>
<th>PF</th>
<th>WR</th>
<th>Net P&amp;L</th>
<th>Return</th>
<th>Max DD</th>
<th>Sharpe</th>
</tr></thead><tbody>
{''.join(rows_html)}
</tbody></table>
</div>
<script>
const table = document.getElementById('t');
table.querySelectorAll('thead th').forEach((th, idx) => {{
  th.addEventListener('click', () => {{
    const tbody = table.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    const dir = th.dataset.sortDir === 'asc' ? 'desc' : 'asc';
    th.dataset.sortDir = dir;
    const num = !isNaN(parseFloat(rows[0]?.children[idx]?.dataset.sort ?? rows[0]?.children[idx]?.textContent));
    rows.sort((a,b) => {{
      const av = a.children[idx].dataset.sort ?? a.children[idx].textContent;
      const bv = b.children[idx].dataset.sort ?? b.children[idx].textContent;
      if (num) return (dir==='asc'?1:-1) * (parseFloat(av)-parseFloat(bv));
      return (dir==='asc'?1:-1) * av.localeCompare(bv);
    }});
    rows.forEach(r => tbody.appendChild(r));
  }});
}});
</script>
</body></html>"""
    out_path.write_text(html, encoding="utf-8")
