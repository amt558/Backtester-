"""
Diagnostic helpers for the robustness verdict module.

These return single-number summaries that either drive a verdict signal
(wf_decay) or surface as diagnostics-only (trade_efficiency). All functions
are pure: same inputs always produce same outputs, no I/O, no global state.

Both functions return Optional[float] — None when the underlying data is
insufficient to compute a meaningful number. Callers must handle None.
"""
from __future__ import annotations

from typing import Optional

from ..results import BacktestResult, WalkForwardResult, WalkForwardWindow


def compute_wf_decay(wf: WalkForwardResult) -> Optional[float]:
    """
    Half-vs-half ratio of aggregate OOS profit factor across WF windows.

    Splits valid windows (those with test_metrics populated) into first and
    second halves. With odd N, the second half gets the extra window. For
    each half, recomputes PF from summed gross_profit / gross_loss across
    all windows in that half (correct aggregation; mean of per-window PFs
    would be biased by small-trade-count windows).

    Returns late_pf / early_pf. Lower values = strategy decaying across the
    WF span. Returns None when:
      - Fewer than 4 valid windows (signal undefined)
      - Either half has zero gross_loss (PF undefined)
      - Early-half PF is zero (division by zero)
    """
    valid = [w for w in wf.windows if w.test_metrics is not None]
    if len(valid) < 4:
        return None
    valid.sort(key=lambda w: w.index)

    n = len(valid)
    first = valid[:n // 2]
    second = valid[n // 2:]

    def _half_pf(half: list[WalkForwardWindow]) -> Optional[float]:
        # gp and gl are non-negative by engine convention: backtest.py defines
        # gross_profit = sum(winning pnls) and gross_loss = abs(sum(losing pnls)).
        gp = sum(w.test_metrics.gross_profit for w in half)
        gl = sum(w.test_metrics.gross_loss for w in half)
        if gl <= 0:
            return None
        return gp / gl

    early_pf = _half_pf(first)
    late_pf = _half_pf(second)
    if early_pf is None or late_pf is None or early_pf == 0:
        return None
    return late_pf / early_pf
