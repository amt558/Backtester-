# Robustness — Rolling WFE Decay Signal + Trade Efficiency Diagnostic — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `wf_decay` (verdict signal, half-vs-half OOS PF ratio) and `trade_efficiency` (diagnostic, portfolio captured/ideal $ ratio) to tradelab's robustness/verdict module. No engine changes — both consume data already populated on `WalkForwardWindow.test_metrics` and `Trade.mfe_pct`.

**Architecture:** New pure-function module `src/tradelab/robustness/diagnostics.py` with two functions returning `Optional[float]`. `verdict.py` imports both, integrates `wf_decay` as a new `VerdictSignal` and packs `trade_efficiency` into a new `diagnostics: dict` field on `VerdictResult`. Thresholds wired through three standard locations (`_FALLBACK_THRESHOLDS`, `RobustnessThresholds`, `tradelab.yaml`). Spec: `docs/superpowers/specs/2026-05-01-robustness-rolling-wfe-trade-efficiency-design.md`.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `src/tradelab/robustness/diagnostics.py` | **NEW** | Pure functions: `compute_wf_decay()`, `compute_trade_efficiency()` |
| `src/tradelab/robustness/verdict.py` | Modify | Add `wf_decay` signal block; add diagnostics dict to return; add 2 keys to `_FALLBACK_THRESHOLDS` |
| `src/tradelab/results.py` | Modify | Add `diagnostics: dict[str, Optional[float]]` field to `VerdictResult` |
| `src/tradelab/config.py` | Modify | Add 2 fields to `RobustnessThresholds` |
| `tradelab.yaml` | Modify | Add 2 entries under `robustness.thresholds` |
| `tests/robustness/test_diagnostics.py` | **NEW** | Unit tests for both pure functions |
| `tests/robustness/test_verdict.py` | Modify | Add wf_decay signal cases, diagnostics-dict cases, reclassification, schema round-trip |

---

## Task 0: Pre-flight verification (no code changes)

Per spec §4.3, three things must be confirmed against current engine code before any formula or test is written. This task produces a short findings note appended to the plan as a comment block; it does NOT commit.

**Files:** None modified. Read-only investigation.

- [ ] **Step 1: Confirm `mfe_pct` sign convention for shorts**

Run: `grep -rn "mfe_pct" C:/TradingScripts/tradelab/src/tradelab/engines/`

Read the engine code that populates `mfe_pct` on Trade objects. Determine:
- For LONG trades, does favorable excursion (price up) produce positive `mfe_pct`?
- For SHORT trades, does favorable excursion (price down) produce positive `mfe_pct`, or is it stored as a directional price change (negative for favorable shorts)?

Expected result: positive-when-favorable in both cases. If shorts store directional change instead, **stop and update the spec** — `compute_trade_efficiency()` will need sign-aware logic.

- [ ] **Step 2: Confirm `gross_profit` and `gross_loss` populated on `WalkForwardWindow.test_metrics`**

Run: `grep -rn "gross_profit\|gross_loss" C:/TradingScripts/tradelab/src/tradelab/engines/walkforward.py`

Verify each window's `test_metrics: BacktestMetrics` actually has these fields filled (not left at default 0.0). If they're not populated, the wf_decay formula is invalid — **stop and update spec/plan** to use a different per-window aggregation (e.g., reconstruct from `test_metrics.profit_factor` × `total_trades` weighting).

- [ ] **Step 3: Find a test fixture with non-zero `mfe_pct`**

Run: `grep -rn "mfe_pct" C:/TradingScripts/tradelab/tests/`

Note any existing fixture file that has trades with populated `mfe_pct > 0`. If none exists, all trade_efficiency happy-path tests will need to construct synthetic `Trade` objects inline (acceptable — Task 4 already plans for this).

- [ ] **Step 4: Document findings**

Add findings as a comment in the plan file (`docs/superpowers/plans/2026-05-01-robustness-rolling-wfe-trade-efficiency.md`) under a new "## Pre-flight findings" section above the tasks. Format:

```markdown
## Pre-flight findings (Task 0)

- **mfe_pct sign convention:** [findings + file references]
- **gross_profit/gross_loss per WF window:** [findings + file references]
- **Existing fixtures with MFE:** [findings + file references]
- **Spec adjustments required:** [yes/no, what changes]
```

Do not commit yet — Task 1 will commit the data-model change and we'll bundle the findings note with that.

---

## Task 1: Add `diagnostics` field to `VerdictResult`

**Files:**
- Modify: `src/tradelab/results.py` (around line 138 where `VerdictResult` is — but `VerdictResult` is actually defined in `verdict.py`, not `results.py`; verify in Step 1)
- Test: `tests/robustness/test_verdict.py` (extend)

- [ ] **Step 1: Locate the VerdictResult class**

Run: `grep -n "class VerdictResult" C:/TradingScripts/tradelab/src/tradelab/`

`VerdictResult` is defined in `src/tradelab/robustness/verdict.py` (lines 39–50 per the spec's exploration). Note this for the modification. The spec's §3.1 says `src/tradelab/results.py` — that was incorrect; the modification target is `verdict.py`.

- [ ] **Step 2: Write the failing test**

Append to `tests/robustness/test_verdict.py`:

```python
def test_verdict_result_has_diagnostics_field_default_empty():
    """VerdictResult must include a diagnostics dict, default to empty."""
    from tradelab.robustness.verdict import VerdictResult
    v = VerdictResult(verdict="ROBUST")
    assert v.diagnostics == {}


def test_verdict_result_diagnostics_round_trips_through_json():
    """diagnostics field must serialize and deserialize."""
    from tradelab.robustness.verdict import VerdictResult, VerdictSignal
    v = VerdictResult(
        verdict="ROBUST",
        signals=[VerdictSignal(name="x", outcome="robust", reason="test")],
        diagnostics={"trade_efficiency": 0.62, "future_metric": None},
    )
    payload = v.model_dump_json()
    parsed = VerdictResult.model_validate_json(payload)
    assert parsed.diagnostics == {"trade_efficiency": 0.62, "future_metric": None}


def test_verdict_result_old_json_without_diagnostics_still_parses():
    """Backwards compat: JSON written before diagnostics field must still parse."""
    from tradelab.robustness.verdict import VerdictResult
    old_payload = '{"verdict": "ROBUST", "signals": []}'
    v = VerdictResult.model_validate_json(old_payload)
    assert v.diagnostics == {}
```

- [ ] **Step 3: Run tests, verify they fail**

Run: `cd C:/TradingScripts/tradelab && pytest tests/robustness/test_verdict.py::test_verdict_result_has_diagnostics_field_default_empty tests/robustness/test_verdict.py::test_verdict_result_diagnostics_round_trips_through_json tests/robustness/test_verdict.py::test_verdict_result_old_json_without_diagnostics_still_parses -v`

Expected: All 3 FAIL with `AttributeError` or pydantic validation errors mentioning unknown field `diagnostics`.

- [ ] **Step 4: Add the `diagnostics` field**

Edit `src/tradelab/robustness/verdict.py`. Find:

```python
class VerdictResult(BaseModel):
    """Aggregate verdict + the signals that drove it."""
    verdict: str   # ROBUST | INCONCLUSIVE | FRAGILE
    signals: list[VerdictSignal] = Field(default_factory=list)
```

Replace with:

```python
class VerdictResult(BaseModel):
    """Aggregate verdict + the signals that drove it."""
    verdict: str   # ROBUST | INCONCLUSIVE | FRAGILE
    signals: list[VerdictSignal] = Field(default_factory=list)
    diagnostics: dict[str, Optional[float]] = Field(default_factory=dict)
```

Note: `Optional` is already imported at line 20. No new imports needed.

- [ ] **Step 5: Run tests, verify they pass**

Run: `cd C:/TradingScripts/tradelab && pytest tests/robustness/test_verdict.py -v`

Expected: all tests in the file PASS, including the 3 new ones. No regressions.

- [ ] **Step 6: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/robustness/verdict.py tests/robustness/test_verdict.py docs/superpowers/plans/2026-05-01-robustness-rolling-wfe-trade-efficiency.md
git commit -m "feat(robustness): add diagnostics dict to VerdictResult

Backwards-compatible: existing JSON without 'diagnostics' parses with empty
default. Will hold trade_efficiency and future per-strategy diagnostics that
don't drive verdict aggregation."
```

---

## Task 2: Add `wf_decay` thresholds (3 files synchronized)

Per spec §5, the threshold pair must exist in three places (verdict fallback, Pydantic class, yaml) for runtime YAML overrides to work.

**Files:**
- Modify: `src/tradelab/robustness/verdict.py` (`_FALLBACK_THRESHOLDS` dict, around lines 57–90)
- Modify: `src/tradelab/config.py` (`RobustnessThresholds` class, around lines 59–87)
- Modify: `tradelab.yaml` (`robustness.thresholds` block, around lines 38–58)
- Test: `tests/robustness/test_verdict_config.py` (existing file — extend)

- [ ] **Step 1: Read existing config test pattern**

Run: `cd C:/TradingScripts/tradelab && cat tests/robustness/test_verdict_config.py | head -80`

Note the pattern used to verify a threshold flows from yaml → config → resolved `THRESHOLDS` dict in verdict.py. Mirror that pattern for the new keys in Step 2.

- [ ] **Step 2: Write the failing tests**

Append to `tests/robustness/test_verdict_config.py`:

```python
def test_robustness_thresholds_includes_wf_decay_defaults():
    """Pydantic class must expose wf_decay_robust=0.90 and wf_decay_fragile=0.70."""
    from tradelab.config import RobustnessThresholds
    t = RobustnessThresholds()
    assert t.wf_decay_robust == 0.90
    assert t.wf_decay_fragile == 0.70


def test_verdict_fallback_includes_wf_decay_keys():
    """_FALLBACK_THRESHOLDS dict must contain both wf_decay keys."""
    from tradelab.robustness.verdict import _FALLBACK_THRESHOLDS
    assert _FALLBACK_THRESHOLDS["wf_decay_robust"] == 0.90
    assert _FALLBACK_THRESHOLDS["wf_decay_fragile"] == 0.70


def test_yaml_thresholds_resolved_includes_wf_decay():
    """_resolve_thresholds() must surface wf_decay keys (config or fallback)."""
    from tradelab.robustness.verdict import _resolve_thresholds
    th = _resolve_thresholds()
    assert "wf_decay_robust" in th
    assert "wf_decay_fragile" in th
    assert th["wf_decay_robust"] == 0.90
    assert th["wf_decay_fragile"] == 0.70
```

- [ ] **Step 3: Run tests, verify they fail**

Run: `cd C:/TradingScripts/tradelab && pytest tests/robustness/test_verdict_config.py::test_robustness_thresholds_includes_wf_decay_defaults tests/robustness/test_verdict_config.py::test_verdict_fallback_includes_wf_decay_keys tests/robustness/test_verdict_config.py::test_yaml_thresholds_resolved_includes_wf_decay -v`

Expected: All 3 FAIL — `AttributeError` for the Pydantic test, `KeyError` for the dict tests.

- [ ] **Step 4: Add to `_FALLBACK_THRESHOLDS` in verdict.py**

Edit `src/tradelab/robustness/verdict.py`. Find the `_FALLBACK_THRESHOLDS` dict (lines ~57–90) and append two entries before the closing brace, after `"hold_out_fragile_pf": 1.00,`:

```python
    # wf_decay: half-vs-half ratio of aggregate OOS PF across walk-forward
    # windows. Late-half / early-half. Below fragile = decaying; above robust
    # = stable. Requires >= 4 valid windows for the signal to emit.
    "wf_decay_robust": 0.90,
    "wf_decay_fragile": 0.70,
```

- [ ] **Step 5: Add to `RobustnessThresholds` in config.py**

Edit `src/tradelab/config.py`. Find the `RobustnessThresholds` class and append two fields after `hold_out_fragile_pf: float = 1.00`:

```python
    # wf_decay (rolling OOS PF, half-vs-half): late-half / early-half ratio.
    # Below fragile threshold = strategy is decaying across the WF span.
    wf_decay_robust: float = 0.90
    wf_decay_fragile: float = 0.70
```

- [ ] **Step 6: Add to tradelab.yaml**

Edit `C:/TradingScripts/tradelab/tradelab.yaml`. Find the `robustness.thresholds` block (lines 38–58) and append two entries after `hold_out_fragile_pf: 1.0`:

```yaml
    wf_decay_robust: 0.9
    wf_decay_fragile: 0.7
```

- [ ] **Step 7: Run tests, verify they pass**

Run: `cd C:/TradingScripts/tradelab && pytest tests/robustness/test_verdict_config.py -v`

Expected: all tests in the file PASS (existing tests should also still pass). No regressions.

- [ ] **Step 8: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/robustness/verdict.py src/tradelab/config.py tradelab.yaml tests/robustness/test_verdict_config.py
git commit -m "feat(robustness): add wf_decay thresholds (0.90 robust, 0.70 fragile)

Three-location wiring (fallback dict, Pydantic class, yaml) per existing
threshold pattern. Used by upcoming wf_decay signal."
```

---

## Task 3: Implement `compute_wf_decay()`

Per spec §4.1: half-vs-half ratio of aggregate OOS profit factor across walk-forward windows.

**Files:**
- Create: `src/tradelab/robustness/diagnostics.py`
- Test: `tests/robustness/test_diagnostics.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `tests/robustness/test_diagnostics.py`:

```python
"""Tests for robustness diagnostic helpers (wf_decay, trade_efficiency)."""
from __future__ import annotations

from tradelab.results import (
    BacktestMetrics, BacktestResult, Trade,
    WalkForwardResult, WalkForwardWindow,
)
from tradelab.robustness.diagnostics import (
    compute_trade_efficiency, compute_wf_decay,
)


def _window(idx: int, gp: float, gl: float) -> WalkForwardWindow:
    """Build a minimal WF window with the given gross profit/loss in test_metrics."""
    pf = (gp / gl) if gl > 0 else 0.0
    metrics = BacktestMetrics(
        total_trades=20, wins=12, losses=8, win_rate=60.0,
        profit_factor=pf, gross_profit=gp, gross_loss=gl,
    )
    return WalkForwardWindow(
        index=idx,
        train_start="2022-01-01", train_end="2022-06-30",
        test_start="2022-07-01", test_end="2022-12-31",
        train_metrics=None, test_metrics=metrics, best_params={},
    )


def _wf(windows: list[WalkForwardWindow]) -> WalkForwardResult:
    return WalkForwardResult(
        strategy="x", n_windows=len(windows), windows=windows,
        wfe_ratio=0.8,
    )


def test_wf_decay_decay_pattern():
    """Late-half PF lower than early-half should give ratio < 1.0."""
    # 6 windows; first 3 strong, last 3 weak.
    # Early aggregate PF = 300/100 = 3.0; Late aggregate PF = 90/100 = 0.9
    # Ratio = 0.9 / 3.0 = 0.30
    windows = [
        _window(0, 100, 33), _window(1, 100, 33), _window(2, 100, 34),
        _window(3, 30, 33),  _window(4, 30, 33),  _window(5, 30, 34),
    ]
    result = compute_wf_decay(_wf(windows))
    assert result is not None
    assert abs(result - 0.30) < 0.01


def test_wf_decay_stable_pattern():
    """Equal PFs across windows should give ratio ~ 1.0."""
    windows = [_window(i, 100, 50) for i in range(6)]
    result = compute_wf_decay(_wf(windows))
    assert result is not None
    assert abs(result - 1.0) < 0.01


def test_wf_decay_improving_pattern():
    """Late-half PF higher than early-half should give ratio > 1.0."""
    # Early: 60/100 = 0.6 PF aggregate; Late: 200/100 = 2.0 PF aggregate.
    # Ratio = 2.0 / 0.6 = 3.33
    windows = [
        _window(0, 20, 33), _window(1, 20, 33), _window(2, 20, 34),
        _window(3, 65, 33), _window(4, 65, 33), _window(5, 70, 34),
    ]
    result = compute_wf_decay(_wf(windows))
    assert result is not None
    assert result > 2.0


def test_wf_decay_insufficient_windows_returns_none():
    """N < 4 valid windows should return None."""
    windows = [_window(i, 100, 50) for i in range(3)]
    assert compute_wf_decay(_wf(windows)) is None


def test_wf_decay_skips_windows_with_no_test_metrics():
    """Windows where test_metrics is None should be filtered out, not crash."""
    valid = [_window(i, 100, 50) for i in range(4)]
    # Add a window with no test_metrics
    no_metrics = WalkForwardWindow(
        index=4,
        train_start="2024-01-01", train_end="2024-06-30",
        test_start="2024-07-01", test_end="2024-12-31",
        train_metrics=None, test_metrics=None, best_params={},
    )
    result = compute_wf_decay(_wf(valid + [no_metrics]))
    assert result is not None  # 4 valid windows is enough
    assert abs(result - 1.0) < 0.01


def test_wf_decay_zero_gross_loss_returns_none():
    """If either half has zero gross_loss, PF undefined → return None."""
    # Late half has zero gross_loss in every window
    windows = [
        _window(0, 100, 50), _window(1, 100, 50),
        _window(2, 100, 0),  _window(3, 100, 0),
    ]
    assert compute_wf_decay(_wf(windows)) is None


def test_wf_decay_all_zero_metrics_returns_none():
    """Windows with all-zero metrics should produce None (no PF computable)."""
    windows = [_window(i, 0, 0) for i in range(6)]
    assert compute_wf_decay(_wf(windows)) is None
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd C:/TradingScripts/tradelab && pytest tests/robustness/test_diagnostics.py -v`

Expected: All FAIL with `ModuleNotFoundError: No module named 'tradelab.robustness.diagnostics'`.

- [ ] **Step 3: Create `diagnostics.py` with `compute_wf_decay`**

Create `src/tradelab/robustness/diagnostics.py`:

```python
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

from ..results import BacktestResult, WalkForwardResult


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

    def _half_pf(half: list) -> Optional[float]:
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
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `cd C:/TradingScripts/tradelab && pytest tests/robustness/test_diagnostics.py -v`

Expected: All 7 wf_decay tests PASS. (`compute_trade_efficiency` tests don't exist yet — not in this task.)

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/robustness/diagnostics.py tests/robustness/test_diagnostics.py
git commit -m "feat(robustness): add compute_wf_decay helper

Half-vs-half aggregate OOS PF ratio across walk-forward windows. Returns
late_pf/early_pf using summed gross_profit / gross_loss per half (correct
PF aggregation). Returns None when <4 valid windows or PF undefined.

Pure function; consumed by verdict.py in the next task."
```

---

## Task 4: Implement `compute_trade_efficiency()`

Per spec §4.2: portfolio-level captured / ideal $ ratio.

**Files:**
- Modify: `src/tradelab/robustness/diagnostics.py` (extend with second function)
- Test: `tests/robustness/test_diagnostics.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/robustness/test_diagnostics.py`:

```python
def _trade(pnl: float, mfe_pct: float, shares: int = 100,
           entry_price: float = 50.0) -> Trade:
    """Build a minimal Trade with the given pnl and mfe_pct."""
    return Trade(
        ticker="TEST",
        entry_date="2024-01-01", exit_date="2024-01-05",
        entry_price=entry_price, exit_price=entry_price + pnl / shares,
        shares=shares, pnl=pnl, pnl_pct=(pnl / (shares * entry_price)) * 100,
        bars_held=4, exit_reason="signal", mae_pct=0.0, mfe_pct=mfe_pct,
    )


def _bt_with_trades(trades: list[Trade]) -> BacktestResult:
    return BacktestResult(
        strategy="x", start_date="2024-01-01", end_date="2024-12-31",
        params={}, metrics=BacktestMetrics(), trades=trades, equity_curve=[],
    )


def test_trade_efficiency_winner_exact_capture():
    """Winner that captured exactly its MFE → ratio 1.0."""
    # entry=50, shares=100, mfe_pct=2.0 → ideal $ = 0.02 * 100 * 50 = 100.0
    # pnl = 100.0 → captured / ideal = 1.0
    trade = _trade(pnl=100.0, mfe_pct=2.0, shares=100, entry_price=50.0)
    result = compute_trade_efficiency(_bt_with_trades([trade]))
    assert result is not None
    assert abs(result - 1.0) < 0.001


def test_trade_efficiency_winner_half_capture():
    """Winner that captured half its MFE → ratio 0.5."""
    # ideal $ = 0.02 * 100 * 50 = 100.0; pnl = 50.0 → ratio 0.5
    trade = _trade(pnl=50.0, mfe_pct=2.0, shares=100, entry_price=50.0)
    result = compute_trade_efficiency(_bt_with_trades([trade]))
    assert result is not None
    assert abs(result - 0.5) < 0.001


def test_trade_efficiency_mixed_winners_and_losers():
    """Mix of winners and losers: portfolio aggregate."""
    # Winner: pnl=80, ideal=100  (efficiency 0.8 alone)
    # Loser:  pnl=-30, mfe_pct=1.0 → ideal = 0.01*100*50 = 50; pnl=-30 contributes -30
    # Aggregate: captured = 80 + (-30) = 50; ideal = 100 + 50 = 150
    # Ratio = 50/150 = 0.333
    winner = _trade(pnl=80.0, mfe_pct=2.0)
    loser = _trade(pnl=-30.0, mfe_pct=1.0)
    result = compute_trade_efficiency(_bt_with_trades([winner, loser]))
    assert result is not None
    assert abs(result - (50.0 / 150.0)) < 0.001


def test_trade_efficiency_empty_trades_returns_none():
    """No trades → None."""
    assert compute_trade_efficiency(_bt_with_trades([])) is None


def test_trade_efficiency_all_zero_mfe_returns_none():
    """All trades with mfe_pct=0 (old fixture) → ideal sum is 0 → None."""
    trades = [
        _trade(pnl=10.0, mfe_pct=0.0),
        _trade(pnl=-5.0, mfe_pct=0.0),
    ]
    assert compute_trade_efficiency(_bt_with_trades(trades)) is None


def test_trade_efficiency_loser_with_zero_mfe_drags_numerator():
    """Loser that never went favorable: contributes pnl to numerator,
    0 to denominator. Should NOT be filtered — that would hide real losses."""
    # Winner with mfe>0: ideal=100, pnl=80
    # Loser with mfe=0: ideal=0, pnl=-20
    # Aggregate: captured=60, ideal=100 → ratio 0.6
    winner = _trade(pnl=80.0, mfe_pct=2.0)
    loser = _trade(pnl=-20.0, mfe_pct=0.0)
    result = compute_trade_efficiency(_bt_with_trades([winner, loser]))
    assert result is not None
    assert abs(result - 0.60) < 0.001
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd C:/TradingScripts/tradelab && pytest tests/robustness/test_diagnostics.py -v`

Expected: 7 wf_decay tests still PASS, 6 new trade_efficiency tests FAIL with `ImportError` (function doesn't exist yet).

- [ ] **Step 3: Add `compute_trade_efficiency` to diagnostics.py**

Edit `src/tradelab/robustness/diagnostics.py`. Append to the bottom of the file:

```python
def compute_trade_efficiency(bt: BacktestResult) -> Optional[float]:
    """
    Portfolio-level captured / ideal $ ratio across all trades.

    Ideal $ per trade = mfe_pct/100 × shares × entry_price (the dollar
    profit if we'd exited at the most favorable point). Captured $ = pnl
    (realized dollar profit/loss).

    Aggregating by sum (not mean of per-trade ratios) is intentional: it
    naturally weights by trade size, avoids the division-by-tiny-MFE blowup
    that destroys mean-of-ratios, and gives a single robust number.

    Returns None when:
      - No trades at all
      - Total ideal $ is zero (all trades had mfe_pct=0; pre-MFE backtest data)

    Range typically [-0.2, 1.0]:
      >0.85: tight exits
       0.5–0.85: normal
      <0.4: real exit work to do
    """
    if not bt.trades:
        return None
    ideal = sum((t.mfe_pct / 100.0) * t.shares * t.entry_price for t in bt.trades)
    captured = sum(t.pnl for t in bt.trades)
    if ideal == 0:
        return None
    return captured / ideal
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `cd C:/TradingScripts/tradelab && pytest tests/robustness/test_diagnostics.py -v`

Expected: All 13 tests in the file PASS.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/robustness/diagnostics.py tests/robustness/test_diagnostics.py
git commit -m "feat(robustness): add compute_trade_efficiency helper

Portfolio-level sum(captured) / sum(ideal) in dollars, where ideal per
trade = mfe_pct * shares * entry_price / 100. Aggregation-by-sum avoids
per-trade ratio blowups when individual MFE values are small.

Pure function; consumed by verdict.py in the next task."
```

---

## Task 5: Integrate `wf_decay` signal into `compute_verdict()`

Per spec §3.3(a): new signal block slotted between existing `wfe` block and `hold_out_oos` block.

**Files:**
- Modify: `src/tradelab/robustness/verdict.py`
- Test: `tests/robustness/test_verdict.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/robustness/test_verdict.py`:

```python
def _wf_with_decay(decay_ratio: float) -> "WalkForwardResult":
    """Build a 6-window WF where late-half PF / early-half PF ≈ decay_ratio."""
    from tradelab.results import (
        BacktestMetrics, WalkForwardResult, WalkForwardWindow,
    )

    def w(idx: int, gp: float, gl: float) -> WalkForwardWindow:
        pf = (gp / gl) if gl > 0 else 0.0
        m = BacktestMetrics(
            total_trades=20, wins=12, losses=8, win_rate=60.0,
            profit_factor=pf, gross_profit=gp, gross_loss=gl,
        )
        return WalkForwardWindow(
            index=idx,
            train_start="2022-01-01", train_end="2022-06-30",
            test_start="2022-07-01", test_end="2022-12-31",
            train_metrics=None, test_metrics=m, best_params={},
        )

    # Early half: aggregate PF = 3.0 (300 / 100)
    early = [w(0, 100, 33), w(1, 100, 33), w(2, 100, 34)]
    # Late half: aggregate PF = decay_ratio * 3.0
    late_total_gp = decay_ratio * 3.0 * 100  # late_pf * gl_late
    late = [
        w(3, late_total_gp / 3, 33),
        w(4, late_total_gp / 3, 33),
        w(5, late_total_gp / 3, 34),
    ]
    return WalkForwardResult(
        strategy="x", n_windows=6, windows=early + late,
        wfe_ratio=0.8,
    )


def test_wf_decay_signal_emits_fragile_when_decaying():
    wf = _wf_with_decay(decay_ratio=0.5)  # 50% of early → < 0.70
    v = compute_verdict(_bt(pf=1.6), wf=wf)
    decay_signals = [s for s in v.signals if s.name == "wf_decay"]
    assert len(decay_signals) == 1
    assert decay_signals[0].outcome == "fragile"


def test_wf_decay_signal_emits_robust_when_stable():
    wf = _wf_with_decay(decay_ratio=1.0)  # equal halves → > 0.90
    v = compute_verdict(_bt(pf=1.6), wf=wf)
    decay_signals = [s for s in v.signals if s.name == "wf_decay"]
    assert len(decay_signals) == 1
    assert decay_signals[0].outcome == "robust"


def test_wf_decay_signal_emits_inconclusive_in_middle_band():
    wf = _wf_with_decay(decay_ratio=0.80)  # between 0.70 and 0.90
    v = compute_verdict(_bt(pf=1.6), wf=wf)
    decay_signals = [s for s in v.signals if s.name == "wf_decay"]
    assert len(decay_signals) == 1
    assert decay_signals[0].outcome == "inconclusive"


def test_wf_decay_signal_absent_when_wf_is_none():
    v = compute_verdict(_bt(pf=1.6), wf=None)
    assert not any(s.name == "wf_decay" for s in v.signals)


def test_wf_decay_signal_absent_when_fewer_than_4_windows():
    from tradelab.results import (
        BacktestMetrics, WalkForwardResult, WalkForwardWindow,
    )
    m = BacktestMetrics(
        total_trades=20, wins=12, losses=8, win_rate=60.0,
        profit_factor=1.5, gross_profit=100, gross_loss=66,
    )
    windows = [
        WalkForwardWindow(
            index=i,
            train_start="2022-01-01", train_end="2022-06-30",
            test_start="2022-07-01", test_end="2022-12-31",
            train_metrics=None, test_metrics=m, best_params={},
        )
        for i in range(3)
    ]
    wf = WalkForwardResult(strategy="x", n_windows=3, windows=windows, wfe_ratio=0.8)
    v = compute_verdict(_bt(pf=1.6), wf=wf)
    assert not any(s.name == "wf_decay" for s in v.signals)
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd C:/TradingScripts/tradelab && pytest tests/robustness/test_verdict.py -v -k "wf_decay"`

Expected: 5 new tests FAIL — `len(decay_signals) == 1` will fail because no signal is emitted yet.

- [ ] **Step 3: Add the wf_decay signal block in compute_verdict**

Edit `src/tradelab/robustness/verdict.py`. First, add an import at the top of the file (alongside the existing `from .entry_delay import ...` etc., around line 25–29):

```python
from .diagnostics import compute_wf_decay, compute_trade_efficiency
```

Then find the existing `# --- WFE ---` block (lines ~218–229). Immediately after that block (before the `# --- S4: Hold-out OOS gate` block at line ~231), insert:

```python
    # --- wf_decay: rolling OOS PF, half-vs-half ratio ---
    # Catches temporal decay that aggregate WFE collapses into one ratio.
    # Requires >= 4 valid windows; emits no signal otherwise.
    if wf and wf.n_windows >= 4:
        decay = compute_wf_decay(wf)
        if decay is not None:
            if decay >= THRESHOLDS["wf_decay_robust"]:
                signals.append(VerdictSignal(
                    name="wf_decay", outcome="robust",
                    reason=f"Late-half OOS PF is {decay:.0%} of early-half (stable)",
                ))
            elif decay < THRESHOLDS["wf_decay_fragile"]:
                signals.append(VerdictSignal(
                    name="wf_decay", outcome="fragile",
                    reason=f"Late-half OOS PF only {decay:.0%} of early-half (decaying)",
                ))
            else:
                signals.append(VerdictSignal(
                    name="wf_decay", outcome="inconclusive",
                    reason=f"Late-half OOS PF {decay:.0%} of early-half",
                ))
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `cd C:/TradingScripts/tradelab && pytest tests/robustness/test_verdict.py -v`

Expected: all tests in the file PASS, including the 5 new wf_decay ones. No regressions in existing tests.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/robustness/verdict.py tests/robustness/test_verdict.py
git commit -m "feat(robustness): emit wf_decay signal in compute_verdict

Slotted between wfe and hold_out_oos blocks. Fragile when late-half OOS
PF ratio < 0.70 of early-half (strategy decaying). Robust when ratio
>= 0.90. Requires n_windows >= 4 for the signal to emit."
```

---

## Task 6: Integrate `trade_efficiency` diagnostic into `compute_verdict()`

Per spec §3.3(b): diagnostics dict computed at end, no aggregation impact.

**Files:**
- Modify: `src/tradelab/robustness/verdict.py`
- Test: `tests/robustness/test_verdict.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/robustness/test_verdict.py`:

```python
def test_verdict_diagnostics_populated_when_trades_have_mfe():
    """diagnostics['trade_efficiency'] should be a float when MFE data present."""
    from tradelab.results import Trade

    bt = BacktestResult(
        strategy="x", start_date="2024-01-01", end_date="2024-12-31",
        params={}, metrics=BacktestMetrics(profit_factor=1.6),
        trades=[
            Trade(
                ticker="TEST",
                entry_date="2024-01-01", exit_date="2024-01-05",
                entry_price=50.0, exit_price=50.8,
                shares=100, pnl=80.0, pnl_pct=1.6, bars_held=4,
                exit_reason="signal", mae_pct=0.0, mfe_pct=2.0,
            ),
        ],
        equity_curve=[],
    )
    v = compute_verdict(bt)
    assert "trade_efficiency" in v.diagnostics
    assert v.diagnostics["trade_efficiency"] is not None
    # ideal $ = 0.02*100*50 = 100; captured = 80 → ratio 0.8
    assert abs(v.diagnostics["trade_efficiency"] - 0.8) < 0.001


def test_verdict_diagnostics_trade_efficiency_none_when_no_mfe():
    """diagnostics['trade_efficiency'] should be None for trades without MFE."""
    from tradelab.results import Trade
    bt = BacktestResult(
        strategy="x", start_date="2024-01-01", end_date="2024-12-31",
        params={}, metrics=BacktestMetrics(profit_factor=1.6),
        trades=[
            Trade(
                ticker="TEST",
                entry_date="2024-01-01", exit_date="2024-01-05",
                entry_price=50.0, exit_price=50.8, shares=100,
                pnl=80.0, pnl_pct=1.6, bars_held=4,
                exit_reason="signal", mae_pct=0.0, mfe_pct=0.0,
            ),
        ],
        equity_curve=[],
    )
    v = compute_verdict(bt)
    assert "trade_efficiency" in v.diagnostics
    assert v.diagnostics["trade_efficiency"] is None


def test_verdict_diagnostics_trade_efficiency_none_when_no_trades():
    """diagnostics['trade_efficiency'] should be None when bt.trades is empty."""
    v = compute_verdict(_bt(pf=1.6))  # _bt() helper builds empty trades
    assert v.diagnostics.get("trade_efficiency") is None
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd C:/TradingScripts/tradelab && pytest tests/robustness/test_verdict.py -v -k "diagnostics"`

Expected: 3 new tests FAIL — `'trade_efficiency' in v.diagnostics` will be False because compute_verdict doesn't populate diagnostics yet.

- [ ] **Step 3: Add diagnostics computation at the end of compute_verdict**

Edit `src/tradelab/robustness/verdict.py`. Find the final aggregation block (lines ~337–358) ending with:

```python
    if any(s.name == "regime_spread_hard" and s.outcome == "fragile" for s in signals):
        verdict = "FRAGILE"

    return VerdictResult(verdict=verdict, signals=signals)
```

Replace the final two lines with:

```python
    if any(s.name == "regime_spread_hard" and s.outcome == "fragile" for s in signals):
        verdict = "FRAGILE"

    # --- Diagnostics (no aggregation impact, surface for dashboards) ---
    diagnostics: dict[str, Optional[float]] = {
        "trade_efficiency": compute_trade_efficiency(bt),
    }

    return VerdictResult(verdict=verdict, signals=signals, diagnostics=diagnostics)
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `cd C:/TradingScripts/tradelab && pytest tests/robustness/test_verdict.py -v`

Expected: all tests in the file PASS, including the 3 new diagnostics tests. No regressions.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/robustness/verdict.py tests/robustness/test_verdict.py
git commit -m "feat(robustness): pack trade_efficiency into VerdictResult.diagnostics

Diagnostic-only — no aggregation impact, no thresholds. Returns None when
no trades or no MFE data populated. Open shape allows future diagnostics
to drop in without schema changes."
```

---

## Task 7: Reclassification regression test + schema round-trip

Per spec §7 (reclassification table) and §8.2 (schema round-trip): explicit tests for the case that motivated the change.

**Files:**
- Test: `tests/robustness/test_verdict.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `tests/robustness/test_verdict.py`:

```python
def test_reclassification_robust_with_decay_drops_to_inconclusive():
    """A previously-ROBUST signal mix becomes INCONCLUSIVE when wf_decay flags fragile.

    Builds a strategy that satisfies the original ROBUST aggregation rule
    (n_robust >= max(3, len/2), n_fragile == 0) and then adds a decaying
    walk-forward. Expected: verdict drops to INCONCLUSIVE (not FRAGILE,
    because n_fragile=1 with n_robust>0 doesn't trigger the FRAGILE override).
    """
    from tradelab.robustness.param_landscape import ParamLandscapeResult
    from tradelab.robustness.entry_delay import EntryDelayResult, EntryDelayPoint
    from tradelab.robustness.loso import LOSOResult, LOSOFold

    bt = _bt(pf=1.6)
    landscape = ParamLandscapeResult(
        top_params=["a", "b"], grid_values=[[1, 2], [3, 4]],
        fitness_grid=[[1.0, 1.0], [1.0, 1.0]],
        best_fitness=1.0, mean_fitness=1.0, std_fitness=0.01,
        smoothness_ratio=0.01, cliff_flag=False,
    )
    ed = EntryDelayResult(delays=[0, 1], points=[
        EntryDelayPoint(delay=0, metrics=bt.metrics),
        EntryDelayPoint(delay=1, metrics=BacktestMetrics(
            total_trades=100, wins=60, losses=40, win_rate=60.0,
            profit_factor=1.55,
        )),
    ])
    m_fold = BacktestMetrics(total_trades=50, wins=30, losses=20,
                              win_rate=60.0, profit_factor=1.55)
    lo = LOSOResult(
        folds=[
            LOSOFold(held_out_symbol="A", metrics=m_fold),
            LOSOFold(held_out_symbol="B", metrics=m_fold),
        ],
        pf_mean=1.55, pf_min=1.5, pf_max=1.6, pf_spread=0.1,
    )
    decaying_wf = _wf_with_decay(decay_ratio=0.5)  # fragile

    v = compute_verdict(bt, dsr=0.97, mc=None, landscape=landscape,
                        entry_delay=ed, loso=lo, wf=decaying_wf)
    assert v.verdict == "INCONCLUSIVE", (
        f"expected INCONCLUSIVE (decay drops a previously-ROBUST strategy), "
        f"got {v.verdict}: {[(s.name, s.outcome) for s in v.signals]}"
    )
    # Verify wf_decay is the fragile signal
    assert any(s.name == "wf_decay" and s.outcome == "fragile" for s in v.signals)


def test_reclassification_robust_with_stable_wf_stays_robust():
    """Same ROBUST mix with stable wf_decay should remain ROBUST."""
    from tradelab.robustness.param_landscape import ParamLandscapeResult
    from tradelab.robustness.entry_delay import EntryDelayResult, EntryDelayPoint
    from tradelab.robustness.loso import LOSOResult, LOSOFold

    bt = _bt(pf=1.6)
    landscape = ParamLandscapeResult(
        top_params=["a", "b"], grid_values=[[1, 2], [3, 4]],
        fitness_grid=[[1.0, 1.0], [1.0, 1.0]],
        best_fitness=1.0, mean_fitness=1.0, std_fitness=0.01,
        smoothness_ratio=0.01, cliff_flag=False,
    )
    ed = EntryDelayResult(delays=[0, 1], points=[
        EntryDelayPoint(delay=0, metrics=bt.metrics),
        EntryDelayPoint(delay=1, metrics=BacktestMetrics(
            total_trades=100, wins=60, losses=40, win_rate=60.0,
            profit_factor=1.55,
        )),
    ])
    m_fold = BacktestMetrics(total_trades=50, wins=30, losses=20,
                              win_rate=60.0, profit_factor=1.55)
    lo = LOSOResult(
        folds=[
            LOSOFold(held_out_symbol="A", metrics=m_fold),
            LOSOFold(held_out_symbol="B", metrics=m_fold),
        ],
        pf_mean=1.55, pf_min=1.5, pf_max=1.6, pf_spread=0.1,
    )
    stable_wf = _wf_with_decay(decay_ratio=1.0)  # robust

    v = compute_verdict(bt, dsr=0.97, mc=None, landscape=landscape,
                        entry_delay=ed, loso=lo, wf=stable_wf)
    assert v.verdict == "ROBUST", (
        f"expected ROBUST, got {v.verdict}: "
        f"{[(s.name, s.outcome) for s in v.signals]}"
    )


def test_full_verdict_json_round_trip_preserves_diagnostics():
    """Verify a full VerdictResult survives JSON serialization with all new
    fields including diagnostics dict."""
    import json
    from tradelab.results import Trade
    from tradelab.robustness.verdict import VerdictResult

    bt = BacktestResult(
        strategy="x", start_date="2024-01-01", end_date="2024-12-31",
        params={}, metrics=BacktestMetrics(profit_factor=1.6),
        trades=[Trade(
            ticker="TEST",
            entry_date="2024-01-01", exit_date="2024-01-05",
            entry_price=50.0, exit_price=50.8, shares=100,
            pnl=80.0, pnl_pct=1.6, bars_held=4,
            exit_reason="signal", mae_pct=0.0, mfe_pct=2.0,
        )],
        equity_curve=[],
    )
    wf = _wf_with_decay(decay_ratio=0.5)
    v = compute_verdict(bt, wf=wf)

    payload = v.model_dump_json()
    parsed_dict = json.loads(payload)
    assert "verdict" in parsed_dict
    assert "signals" in parsed_dict
    assert "diagnostics" in parsed_dict
    assert "trade_efficiency" in parsed_dict["diagnostics"]

    parsed = VerdictResult.model_validate_json(payload)
    assert parsed.verdict == v.verdict
    assert parsed.diagnostics == v.diagnostics
    assert len(parsed.signals) == len(v.signals)
```

- [ ] **Step 2: Run tests, verify they fail or pass**

Run: `cd C:/TradingScripts/tradelab && pytest tests/robustness/test_verdict.py -v -k "reclassification or round_trip"`

Expected: All 3 PASS (the implementation is already complete; these are regression tests proving the spec's reclassification claim and JSON round-trip work end-to-end). If any fails, debug before continuing — do not commit a failing reclassification test.

- [ ] **Step 3: Commit**

```bash
cd C:/TradingScripts/tradelab && git add tests/robustness/test_verdict.py
git commit -m "test(robustness): regression tests for wf_decay reclassification

Locks in the spec's §7 claim: previously-ROBUST signal mix + decaying WF
drops to INCONCLUSIVE (not FRAGILE). Stable WF preserves ROBUST. Adds full
JSON round-trip including diagnostics dict to catch schema regressions."
```

---

## Task 8: Full suite verification + summary commit

**Files:** None modified. Smoke + verification only.

- [ ] **Step 1: Run full robustness test suite**

Run: `cd C:/TradingScripts/tradelab && pytest tests/robustness/ -v`

Expected: all tests PASS. No skips, no errors. If anything fails, fix before continuing.

- [ ] **Step 2: Run the full project test suite**

Run: `cd C:/TradingScripts/tradelab && pytest tests/ -q 2>&1 | tail -30`

Expected: all tests PASS, no regressions in unrelated modules. If anything fails, identify whether it's caused by this work or pre-existing — only fix work caused by this change.

- [ ] **Step 3: Verify the new module is importable and round-trips a real WF**

Run:
```bash
cd C:/TradingScripts/tradelab && python -c "
from tradelab.robustness.diagnostics import compute_wf_decay, compute_trade_efficiency
from tradelab.robustness.verdict import compute_verdict, VerdictResult
print('imports OK')
print('VerdictResult fields:', list(VerdictResult.model_fields.keys()))
"
```

Expected output:
```
imports OK
VerdictResult fields: ['verdict', 'signals', 'diagnostics']
```

- [ ] **Step 4: Verify yaml threshold loads through config**

Run:
```bash
cd C:/TradingScripts/tradelab && python -c "
from tradelab.config import get_config
cfg = get_config()
print('wf_decay_robust:', cfg.robustness.thresholds.wf_decay_robust)
print('wf_decay_fragile:', cfg.robustness.thresholds.wf_decay_fragile)
"
```

Expected output:
```
wf_decay_robust: 0.9
wf_decay_fragile: 0.7
```

- [ ] **Step 5: No final commit needed**

Tasks 1–7 each committed independently. The branch contains 7 commits implementing the spec end-to-end. Use `git log --oneline -8` to confirm the commit chain.

```bash
cd C:/TradingScripts/tradelab && git log --oneline -8
```

Expected: 7 new commits matching the per-task messages, atop the prior `cbbb47e docs(robustness): spec for ...` commit.

---

## Verification summary

| Spec section | Implemented in | Verified by |
|---|---|---|
| §3.1 `diagnostics` field on VerdictResult | Task 1 | `test_verdict_result_*` (3 tests) |
| §3.2 `compute_wf_decay` and `compute_trade_efficiency` pure functions | Tasks 3, 4 | `test_diagnostics.py` (13 tests) |
| §3.3(a) wf_decay signal block in compute_verdict | Task 5 | `test_wf_decay_signal_*` (5 tests) |
| §3.3(b) trade_efficiency diagnostic in compute_verdict return | Task 6 | `test_verdict_diagnostics_*` (3 tests) |
| §4.1 wf_decay math (half-vs-half aggregate PF, min 4 windows) | Task 3 | 7 unit tests |
| §4.2 trade_efficiency math (sum captured / sum ideal, edge cases) | Task 4 | 6 unit tests |
| §4.3 pre-implementation grep verifications | Task 0 | findings note in plan |
| §5 threshold config (3 locations synced) | Task 2 | `test_*_wf_decay*` config tests |
| §6 out-of-scope rationale | (no code) | spec docs |
| §7 reclassification table | Task 7 | reclassification regression tests |
| §8 testing surface | Tasks 3, 4, 5, 6, 7 | all combined |
| §9 file-touch summary | Tasks 1–6 | 7 commits |
