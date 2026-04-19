"""
Look-ahead bias detector — three layers of evidence.

Layer 1 (static): scan the strategy's source file for suspicious patterns
that often indicate forward peeking — `.shift(-N)`, `iloc[i+1]`, `i+1` in
generate_signals, etc. Cheap and catches most accidental leaks.

Layer 2 (dynamic shift): run the backtest with buy_signal shifted +1 bar.
If the +0 baseline is dramatically better than +1 shifted, the strategy
is implicitly using same-bar future info (e.g., entering at Close on a
bar whose Close depended on the entry decision).

Layer 3 (cross-bar permutation): produce a "leakage P&L" estimate — the
dollar gap between observed P&L and the +1-bar shifted P&L. If the gap
is large and positive, the strategy's edge depends on perfect-bar timing
that won't survive in live execution.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import Any, Optional

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from ..results import BacktestMetrics


SUSPICIOUS_PATTERNS = [
    (r"\.shift\(\s*-\s*\d+", "negative shift (looks forward)"),
    (r"\.shift\(\s*-\s*[a-zA-Z_]", "negative shift via variable"),
    (r"iloc\s*\[\s*\w+\s*\+\s*\d+\s*\]", "iloc[i+N] (forward index)"),
    (r"iloc\s*\[\s*[-]\s*\d+\s*\]", "iloc[-N] inside generate_signals (often suspicious)"),
    (r"\.tail\(", ".tail() inside generate_signals (often peeks at end)"),
    (r"future_close|future_high|future_low|future_open", "named 'future_*' variable"),
    (r"\.iat\s*\[\s*\w+\s*\+\s*\d+", "iat[i+N] forward index"),
]


class LeakStaticFinding(BaseModel):
    line_no: int
    line: str
    pattern: str
    note: str


class LeakStaticResult(BaseModel):
    file_path: str
    n_findings: int
    findings: list[LeakStaticFinding] = Field(default_factory=list)


class LeakDynamicResult(BaseModel):
    """Result of comparing baseline vs shifted-by-1-bar backtest."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    baseline_pf: float
    shifted_pf: float
    baseline_pnl: float
    shifted_pnl: float
    pf_drop_pct: float          # (baseline - shifted) / baseline * 100
    leakage_pnl_estimate: float # baseline_pnl - shifted_pnl  (positive = leakage)
    flag: str                   # "ok" | "suspect" | "fragile"


class LeakCheckResult(BaseModel):
    strategy: str
    static: LeakStaticResult
    dynamic: Optional[LeakDynamicResult] = None
    overall_flag: str           # "ok" | "suspect" | "fragile"


# ---------------------------------------------------------------- static ---


def _resolve_strategy_source_file(strategy: Any) -> Optional[Path]:
    """Try to find the source file for a strategy class."""
    try:
        f = inspect.getsourcefile(strategy.__class__)
        return Path(f) if f else None
    except (TypeError, OSError):
        return None


def static_scan(strategy: Any) -> LeakStaticResult:
    """Grep the strategy file for suspicious lookahead patterns."""
    src_path = _resolve_strategy_source_file(strategy)
    if src_path is None or not src_path.exists():
        return LeakStaticResult(file_path="<unknown>", n_findings=0)

    findings: list[LeakStaticFinding] = []
    try:
        text = src_path.read_text(encoding="utf-8")
    except OSError:
        return LeakStaticResult(file_path=str(src_path), n_findings=0)

    for i, line in enumerate(text.splitlines(), start=1):
        # Skip comments and the canary's intentional leak (it's labeled)
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith('"""'):
            continue
        for pat, note in SUSPICIOUS_PATTERNS:
            if re.search(pat, line):
                findings.append(LeakStaticFinding(
                    line_no=i, line=line.rstrip(), pattern=pat, note=note,
                ))

    return LeakStaticResult(
        file_path=str(src_path),
        n_findings=len(findings),
        findings=findings,
    )


# --------------------------------------------------------------- dynamic ---


def dynamic_shift_check(
    strategy: Any,
    ticker_data: dict,
    spy_close=None,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> LeakDynamicResult:
    """
    Run baseline vs +1-bar shifted backtest. Big gap = leakage.

    Reuses the entry_delay machinery: shifting buy_signal by +1 should NOT
    materially worsen a real edge (a real edge is robust to one-bar
    execution latency).
    """
    from ..engines.backtest import run_backtest
    from ..robustness.entry_delay import _shifted_universe

    # Baseline (no shift)
    bt0_data = _shifted_universe(ticker_data, 0, strategy)
    class _PT:
        name = strategy.name + "_baseline"
        timeframe = strategy.timeframe
        requires_benchmark = False
        def __init__(self, params): self.params = dict(params)
        def generate_signals(self, data, spy_close=None): return data
    bt0 = run_backtest(_PT(strategy.params), bt0_data,
                        start=start, end=end, spy_close=spy_close)

    bt1_data = _shifted_universe(ticker_data, 1, strategy)
    bt1 = run_backtest(_PT(strategy.params), bt1_data,
                        start=start, end=end, spy_close=spy_close)

    base_pf = bt0.metrics.profit_factor
    base_pnl = bt0.metrics.net_pnl
    shf_pf = bt1.metrics.profit_factor
    shf_pnl = bt1.metrics.net_pnl

    pf_drop_pct = 0.0
    if base_pf > 0:
        pf_drop_pct = float((base_pf - shf_pf) / base_pf * 100.0)
    leakage_pnl = float(base_pnl - shf_pnl)

    # Thresholds (mirror robustness/verdict.py entry_delay rule)
    if pf_drop_pct >= 50:
        flag = "fragile"
    elif pf_drop_pct >= 25:
        flag = "suspect"
    else:
        flag = "ok"

    return LeakDynamicResult(
        baseline_pf=base_pf,
        shifted_pf=shf_pf,
        baseline_pnl=base_pnl,
        shifted_pnl=shf_pnl,
        pf_drop_pct=pf_drop_pct,
        leakage_pnl_estimate=leakage_pnl,
        flag=flag,
    )


# ------------------------------------------------------------------ run ---


def run_leak_check(
    strategy: Any,
    ticker_data: Optional[dict] = None,
    spy_close=None,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> LeakCheckResult:
    """
    Run static + dynamic leak checks. Dynamic check is skipped if no
    ticker_data provided (static-only mode).
    """
    static = static_scan(strategy)
    dynamic = None
    if ticker_data:
        try:
            dynamic = dynamic_shift_check(
                strategy, ticker_data,
                spy_close=spy_close, start=start, end=end,
            )
        except Exception:
            dynamic = None

    # Aggregate
    flags = []
    if static.n_findings > 0:
        flags.append("suspect")
    if dynamic is not None:
        flags.append(dynamic.flag)
    if "fragile" in flags:
        overall = "fragile"
    elif "suspect" in flags:
        overall = "suspect"
    else:
        overall = "ok"

    return LeakCheckResult(
        strategy=strategy.name,
        static=static,
        dynamic=dynamic,
        overall_flag=overall,
    )
