"""Assemble the full HTML dashboard."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from ..determinism import hash_config, hash_universe, render_footer
from ..results import BacktestResult, OptunaResult, WalkForwardResult
from . import tabs
from .templates import HTML_SKELETON


def build_dashboard(
    backtest_result: BacktestResult,
    optuna_result: Optional[OptunaResult] = None,
    wf_result: Optional[WalkForwardResult] = None,
    universe: Optional[dict] = None,
    out_dir: Optional[Path] = None,
) -> Path:
    ts = datetime.now()
    if out_dir is None:
        out_dir = Path("reports") / f"{backtest_result.strategy}_{ts.strftime('%Y-%m-%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)

    title = f"{backtest_result.strategy} — tradelab dashboard"
    universe_str = ", ".join(sorted(universe.keys())) if universe else "see config"
    meta = f"Window: {backtest_result.start_date} → {backtest_result.end_date} · Universe: {universe_str} · Run: {ts.strftime('%Y-%m-%d %H:%M:%S')}"

    performance_html = tabs.performance_tab(backtest_result, wf_result)
    robustness_html = tabs.robustness_tab(backtest_result, wf_result)
    parameters_html = tabs.parameters_tab(optuna_result)

    data_hash = hash_universe(universe) if universe else None
    config_hash = hash_config(backtest_result.params)
    footer_text = render_footer(data_hash=data_hash, config_hash=config_hash).replace("\n", "<br>")

    html = HTML_SKELETON.format(
        title=title, meta=meta,
        performance_html=performance_html,
        robustness_html=robustness_html,
        parameters_html=parameters_html,
        footer=footer_text,
    )

    out_path = out_dir / "dashboard.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path
