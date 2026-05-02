# Robustness — Rolling WFE Decay Signal + Trade Efficiency Diagnostic — Design

**Date:** 2026-05-01
**Status:** Approved for plan-writing
**Scope:** Two additions to `src/tradelab/robustness/` to close gaps identified between current verdict coverage and the 7-signal mockup panel.

---

## 1. Context

A gap audit comparing the mockup's 7 robustness signals against tradelab's current verdict module found that only the OOS hold-out gate fully overlaps. Five mockup signals are missing entirely or partially:

1. Walk-forward rolling OOS PF (only aggregate WFE exists)
2. Bootstrap resampled PF σ (Monte Carlo only resamples drawdown)
3. ±10% parameter sensitivity (smoothness ratio overlaps)
4. K–S test IS vs OOS distribution
5. Trade efficiency (captured / ideal MFE)

Of the five, only signals 1 and 5 add genuinely new analytical axes that the existing 8-signal verdict module cannot derive from current data:

- **Rolling OOS PF** is the only signal that catches *temporal decay* across walk-forward windows. Aggregate WFE collapses windows into one ratio, hiding patterns where OOS PF holds early but degrades late — the textbook "strategy is dying" signature.
- **Trade efficiency** is the only signal that diagnoses *exit quality*. It identifies strategies leaving paper PnL on the table (low capture / ideal ratio), which drives strategy iteration rather than verdicting.

Signals 2, 3, and 4 were considered and rejected — see §6 Out of Scope.

## 2. Scope

### In scope

| Addition | Type | Surface |
|---|---|---|
| `wf_decay` signal | Verdict signal (FRAGILE/ROBUST/INCONCLUSIVE), counts toward aggregation | `VerdictResult.signals[]` |
| `trade_efficiency` diagnostic | Diagnostic-only float, no aggregation impact | `VerdictResult.diagnostics["trade_efficiency"]` |
| New helpers module | Pure functions for both computations | `src/tradelab/robustness/diagnostics.py` |
| Threshold config | YAML-overridable thresholds | `_FALLBACK_THRESHOLDS` + `RobustnessThresholds` + `tradelab.yaml` |
| `diagnostics` field on `VerdictResult` | Open-ended dict for future diagnostics | `src/tradelab/results.py` |
| Unit tests | Pure-function math + verdict integration | `tests/robustness/test_diagnostics.py`, extensions to `tests/robustness/test_verdict.py` |

### Out of scope (deferred or rejected)

- Dashboard panel for surfacing `wf_decay` and `trade_efficiency` in `command_center.html`. JSON shape is forward-compatible; UI is a separate piece of work and that file is locked at the golden base.
- KS test, ±10% sensitivity, trade autocorrelation. Recommended against (see §6).
- Threshold tuning against historical strategy reclassification. Defaults ship; tune via YAML if reclassification surprises arise.
- New WalkForward fields. Per-window data already exists on `WalkForwardWindow.test_metrics`.

## 3. Architecture

### 3.1 Data model changes

**`src/tradelab/results.py`** — add one field to `VerdictResult`:

```python
class VerdictResult(BaseModel):
    verdict: str
    signals: list[VerdictSignal] = Field(default_factory=list)
    diagnostics: dict[str, Optional[float]] = Field(default_factory=dict)  # NEW
```

Backwards-compatible: defaults to `{}` for old serialized data; existing consumers reading `verdict` and `signals` are unaffected.

**No other model changes.** `WalkForwardWindow.test_metrics` already exposes per-window `gross_profit` / `gross_loss`. `Trade.mfe_pct`, `Trade.shares`, `Trade.entry_price`, `Trade.pnl` are all populated by existing engines.

### 3.2 New module: `src/tradelab/robustness/diagnostics.py`

Two pure functions, both return `Optional[float]`:

```python
def compute_wf_decay(wf: WalkForwardResult) -> Optional[float]:
    """
    Half-vs-half ratio of aggregate OOS profit factor across walk-forward windows.
    Returns late_pf / early_pf (lower = strategy decaying), or None if insufficient
    data (<4 valid windows or zero gross_loss in either half).
    """

def compute_trade_efficiency(bt: BacktestResult) -> Optional[float]:
    """
    Portfolio-level captured / ideal $ ratio. Ideal $ per trade = mfe_pct/100 *
    shares * entry_price. Returns None when no trades or all MFE is zero.
    """
```

### 3.3 Verdict integration

`compute_verdict()` in `src/tradelab/robustness/verdict.py` is extended in two places:

**(a) New signal block** — slotted between the existing `wfe` block and the `hold_out_oos` block:

```python
if wf and wf.n_windows >= 4:
    decay = compute_wf_decay(wf)
    if decay is not None:
        if decay >= THRESHOLDS["wf_decay_robust"]:
            signals.append(VerdictSignal(name="wf_decay", outcome="robust",
                reason=f"Late-half OOS PF is {decay:.0%} of early-half (stable)"))
        elif decay < THRESHOLDS["wf_decay_fragile"]:
            signals.append(VerdictSignal(name="wf_decay", outcome="fragile",
                reason=f"Late-half OOS PF only {decay:.0%} of early-half (decaying)"))
        else:
            signals.append(VerdictSignal(name="wf_decay", outcome="inconclusive",
                reason=f"Late-half OOS PF {decay:.0%} of early-half"))
```

**(b) Diagnostics computation** — at the end, before `return`:

```python
diagnostics = {"trade_efficiency": compute_trade_efficiency(bt)}
return VerdictResult(verdict=verdict, signals=signals, diagnostics=diagnostics)
```

`compute_verdict()`'s signature does not change; both new computations consume `wf` and `bt` arguments that already exist.

## 4. Math specification

### 4.1 `compute_wf_decay`

```
Input: WalkForwardResult wf

1. valid = [w for w in wf.windows if w.test_metrics is not None]
2. if len(valid) < 4: return None
3. valid.sort(key=lambda w: w.index)
4. n = len(valid); first = valid[:n//2]; second = valid[n//2:]
   (with odd N, second half gets the extra window)
5. for each half:
     gp = sum(w.test_metrics.gross_profit for w in half)
     gl = sum(w.test_metrics.gross_loss   for w in half)
     pf = gp / gl  if gl > 0 else None
6. if early_pf is None or late_pf is None or early_pf == 0: return None
7. return late_pf / early_pf
```

Why aggregate PF (not mean of per-window PFs): PF is a ratio. Averaging ratios is mathematically wrong and biased by windows with very few trades. Re-computing PF from summed gross_profit / gross_loss treats each half as a single backtest weighted naturally by trade count.

Why min 4 windows: needs ≥2 per half for the aggregate to be meaningful. With 3 windows the signal is 1-vs-2 — too noisy.

### 4.2 `compute_trade_efficiency`

```
Input: BacktestResult bt

1. if not bt.trades: return None
2. ideal    = sum((t.mfe_pct / 100) * t.shares * t.entry_price for t in bt.trades)
3. captured = sum(t.pnl for t in bt.trades)
4. if ideal == 0: return None
5. return captured / ideal
```

Notes:
- For trades with `mfe_pct == 0` (price never went favorable), the trade contributes its `pnl` (typically negative) to the numerator and 0 to the denominator. Correct: it's a real loss with no captured opportunity.
- For winners that captured exactly their MFE, the per-trade contribution to the ratio is 1.0.
- For losers that briefly went positive then reversed, contribution is negative captured / positive ideal — drags ratio down. Correct: real exit-quality leak.
- Range typically [-0.2, 1.0]. >0.85 = tight exits; 0.5–0.85 = normal; <0.4 = real exit work to do.

### 4.3 Pre-implementation verification (plan-time grep tasks)

Three things must be confirmed against current engine code before any of the above is written:

1. **`mfe_pct` sign convention for shorts.** Grep `mfe_pct` in `src/tradelab/engines/`. If shorts store `mfe_pct` as positive-when-favorable (most likely convention), formula in §4.2 is correct. If shorts store directional price change (negative for favorable short moves), formula needs sign-aware logic.
2. **`gross_profit` and `gross_loss` populated on `WalkForwardWindow.test_metrics`.** These fields exist on `BacktestMetrics` but the walk-forward engine must actually fill them per window. Verify before relying on them in §4.1.
3. **At least one test fixture has non-zero `mfe_pct`.** Check `tests/fixtures/`. Without this, happy-path tests must use synthetic Trade objects.

## 5. Configuration

Two new threshold keys must exist in **all three** locations (existing pattern):

| Location | Entry |
|---|---|
| `src/tradelab/robustness/verdict.py` `_FALLBACK_THRESHOLDS` | `"wf_decay_robust": 0.90, "wf_decay_fragile": 0.70` |
| `src/tradelab/config.py` `RobustnessThresholds` | `wf_decay_robust: float = 0.90`<br>`wf_decay_fragile: float = 0.70` |
| `tradelab.yaml` `robustness.thresholds` | `wf_decay_robust: 0.90`<br>`wf_decay_fragile: 0.70` |

Threshold rationale: 0.70 fragile (30% temporal decay) is consistent with the existing strict-leaning bar (`wfe_fragile = 0.50`, `entry_delay_fragile = 0.50`, `noise_pf_drop_p5_fragile = 0.40`). 0.90 robust (≤10% drift) is tight enough to be meaningful and loose enough that healthy strategies pass.

## 6. Out of scope — rationale for rejecting the other 3 mockup signals

These were considered and rejected; capturing the reasoning here so the choices are auditable later.

### KS test (IS vs OOS distribution) — rejected
- Weak statistical power on typical strategy sample sizes (100–500 trades). Subtle distribution shifts won't trigger; large shifts are already caught by `regime_spread`, `wfe`, `hold_out_oos`, or `wf_decay`.
- Distribution *shape* is the only IS-vs-OOS axis not already covered. It's also the lowest signal-to-noise of the available axes.

### ±10% parameter sensitivity — rejected
- Largely duplicative of `param_landscape.smoothness_ratio`, which already measures parameter robustness via the 5×5 grid.
- Adding it inflates the `n_fragile` count without adding new information, biasing aggregation toward FRAGILE for redundant reasons.
- Useful only as a config-drift detector for ops (production running slightly different params than backtest), which is not a strategy-quality concern.

### Trade clustering / temporal autocorrelation — rejected for now
- Genuinely orthogonal to existing signals (autocorr within a single regime is not caught by `regime_spread`).
- Threshold setting is hard. Momentum strategies *should* show some autocorr; mean-reversion strategies sometimes do too. There's no clean cutoff without empirical grounding.
- Conditional rule: revisit if a strategy passes current verdict and fails in live trading specifically because of trade clustering. Without that real-world failure pattern, threshold calibration is in a vacuum.

### General reasoning — signal saturation
With this spec, the verdict module goes to 11 signals + 1 diagnostic. Adding 3 more would push to 14. Under the existing aggregation rule (any single fragile signal is taken seriously), more signals = more chances for *something* to fire fragile on healthy strategies, diluting the meaning of the FRAGILE verdict. The right next move when verdict misses real fragility is to identify the specific failure pattern from live trading and design a targeted signal — reactive, not preemptive.

## 7. Aggregation impact (reclassification risk)

The `wf_decay` signal joins the existing aggregation rule:
```
n_fragile >= 2 OR (n_fragile >= 1 AND n_robust == 0)        → FRAGILE
n_fragile == 0 AND n_robust >= max(3, len(signals) // 2)    → ROBUST
otherwise                                                    → INCONCLUSIVE
```

Reclassification table:

| Prior verdict | wf_decay outcome | New verdict | Notes |
|---|---|---|---|
| ROBUST (4–5 robust signals) | robust | ROBUST | strengthened |
| ROBUST (4–5 robust signals) | inconclusive | ROBUST | unchanged (denominator math holds) |
| ROBUST (4–5 robust signals) | **fragile** | **INCONCLUSIVE** | **expected reclassification** — strategy was decaying and existing signals didn't catch it |
| INCONCLUSIVE | fragile | FRAGILE if any other fragile present, else INCONCLUSIVE | as designed |
| FRAGILE | any | FRAGILE | already gated |
| WF disabled or <4 windows | (signal not emitted) | unchanged | safe default |

**Rollout decision:** straight rollout, no feature flag. Re-verdicting a strategy that's actually decaying is the system working as designed. The new `wf_decay` signal in the JSON output explains *why* a verdict moved, so the change is debuggable from the data.

## 8. Testing

### 8.1 New file — `tests/robustness/test_diagnostics.py`

`test_compute_wf_decay`:
- Happy path — 6 windows where late-half aggregate PF is 60% of early-half → returns ≈ 0.60
- Stable case — equal PFs across windows → returns ≈ 1.0
- Improving case — late-half PF higher → returns > 1.0
- Insufficient windows — N=3 → returns `None`
- Window with `test_metrics is None` (no trades) — skipped without crash
- Zero gross_loss in either half — returns `None`
- All-zero metrics — returns `None`

`test_compute_trade_efficiency`:
- Happy path — mix of winners and losers with realistic `mfe_pct` and `pnl` → ratio in expected range
- Empty trades list → `None`
- All `mfe_pct == 0` (old fixture) → `None`
- Single winner that captured exactly its MFE → returns 1.0
- Single winner that captured half its MFE → returns 0.5
- **Shorts test** — fixture or synthetic Trade where the short has favorable MFE; if `mfe_pct` is stored with the wrong sign for shorts, this test fails loudly

### 8.2 Extended file — `tests/robustness/test_verdict.py`

- `wf_decay` signal appears with outcome "fragile" when WF has decay pattern
- `wf_decay` signal appears with outcome "robust" when WF is stable
- `wf_decay` signal absent when `wf.n_windows < 4`
- `wf_decay` signal absent when `wf is None`
- `diagnostics["trade_efficiency"]` populated when `bt.trades` has MFE data
- `diagnostics["trade_efficiency"]` is `None` when trades have no MFE data
- **Reclassification test** — fixture with previously-ROBUST signal mix + decaying WF → expect verdict drops to INCONCLUSIVE
- **Schema round-trip test** — serialize `VerdictResult` to JSON, parse back, confirm `diagnostics` field round-trips and old data without `diagnostics` still parses

## 9. File-touch summary

| File | Change |
|---|---|
| `src/tradelab/robustness/diagnostics.py` | NEW — two pure functions |
| `src/tradelab/robustness/verdict.py` | Add `wf_decay` signal block; add `diagnostics` dict to return; add 2 keys to `_FALLBACK_THRESHOLDS` |
| `src/tradelab/results.py` | Add `diagnostics` field to `VerdictResult` |
| `src/tradelab/config.py` | Add 2 fields to `RobustnessThresholds` |
| `tradelab.yaml` | Add 2 entries under `robustness.thresholds` |
| `tests/robustness/test_diagnostics.py` | NEW — unit tests for both functions |
| `tests/robustness/test_verdict.py` | Extended — wf_decay signal cases, diagnostics field cases, reclassification, schema round-trip |
