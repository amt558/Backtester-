# Research Tab Validation Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the FULL validation redesign across 6 phases: hold-out as gate, relative context, multi-dim correlation, regime conditioning, live divergence (K-S + decay), calibration banner. Spec at `docs/superpowers/specs/2026-04-28-research-tab-validation-redesign-design.md`.

**Architecture:** Six independently-executable phases, dependency-ordered. Each phase produces working software (tests green + dashboard hand-smoke). Backend is plain Python (numpy + scipy already vendored, no new deps). Frontend extends `command_center.html` (single-file dashboard at `C:\TradingScripts\command_center.html`, port 8877). New per-card persistence at `pine_archive/<card_id>/`. New notify channel for K-S auto-disable uses existing `tradelab.live.notify` infrastructure.

**Tech Stack:** Python 3.11 · pydantic · numpy · scipy.stats (K-S) · vanilla JS in command_center.html · pytest · `tradelab` library imports.

**Mandatory pre-task ritual** (per memory `feedback_plan_grep_verification`): before pasting any selector/signature/enum from this plan into actual code, **grep it against current code**. The plan was authored 2026-04-28 against a snapshot; drift is possible.

**Mandatory between-slice ritual** (per memory `feedback_live_smoke_before_next_slice`): after every phase's tests pass, hand-smoke through dashboard at `http://localhost:8877` BEFORE starting next phase. Fix any bugs found mid-smoke, do not defer.

---

## File Structure

### New files

```
tradelab/src/tradelab/
├── regime.py                           # Phase 3: market regime classifier
├── robustness/
│   ├── correlation.py                  # Phase 2: return + DD + entry-time corr
│   └── holdout.py                      # Phase 1a: hold-out OOS gate logic
├── live/
│   ├── divergence.py                   # Phase 4: K-S + decay slope per card
│   ├── calibration.py                  # Phase 5: accepted-card outcome stats
│   └── tracking_persistence.py         # Phase 2: pine_archive writer
└── web/
    └── (extends handlers.py — no new files)

tradelab/tests/
├── unit/
│   ├── test_regime.py                  # Phase 3
│   └── test_holdout.py                 # Phase 1a
├── robustness/
│   └── test_correlation.py             # Phase 2
├── live/
│   ├── test_divergence.py              # Phase 4
│   ├── test_calibration.py             # Phase 5
│   └── test_tracking_persistence.py    # Phase 2
└── web/
    └── test_handlers_validation.py     # endpoint tests for all phases
```

### Modified files

```
tradelab/
├── tradelab.yaml                       # +hold_out, +k_s, +decay, +calibration thresholds
├── src/tradelab/
│   ├── config.py                       # +RobustnessThresholds new fields
│   ├── results.py                      # +HoldoutResult, +regime_breakdown field on BacktestResult
│   ├── engines/walkforward.py          # +hold-out window backtest
│   ├── robustness/
│   │   ├── verdict.py                  # hold-out becomes gate, not signal
│   │   └── suite.py                    # invoke correlation + holdout
│   ├── live/receiver.py                # hook to log fills + compute divergence
│   ├── live/cards.py                   # capture returns/dd/entry_times at Accept
│   └── web/
│       ├── handlers.py                 # +6 endpoints
│       └── audit_reader.py             # +last_verdict_at, +relative-context fields
├── tests/web/conftest.py               # tmpdir fixture for pine_archive isolation
└── tests/live/conftest.py              # extend autouse fixture for divergence_log isolation

C:\TradingScripts\command_center.html   # major Research tab additions (all 6 phases)
```

---

## Pre-flight

- [ ] **Step P1: Verify clean working tree**

```bash
cd /c/TradingScripts/tradelab && git status
```

Expected: working tree clean, or only known-uncommitted files (memory: `cli.py`, `cli_doctor.py`, `cli_run.py`, `config.py` may be uncommitted mid-work). If unexpected files present, ask user before proceeding.

- [ ] **Step P2: Verify baseline tests green**

```bash
cd /c/TradingScripts/tradelab && python -m pytest tests/web tests/live tests/robustness tests/engines -q
```

Expected: all green (per memory `project_tradelab_slice_7a_complete`, baseline was 816/816 as of 2026-04-27). If failures exist, document them — they are pre-existing and not introduced by this plan.

- [ ] **Step P3: Verify dashboard launches**

```powershell
Stop-Process -Id (Get-NetTCPConnection -LocalPort 8877 -State Listen -ErrorAction SilentlyContinue).OwningProcess -Force -ErrorAction SilentlyContinue
$env:PYTHONIOENCODING = "utf-8"
cd C:\TradingScripts
python launch_dashboard.py
```

Then in browser: `http://localhost:8877#tab=research`. Confirm Research tab loads with current Live Strategies + Pipeline + Sig modal. Stop launcher when verified.

- [ ] **Step P4: Confirm `pine_archive` directory exists or create**

```bash
mkdir -p /c/TradingScripts/tradelab/pine_archive
ls /c/TradingScripts/tradelab/pine_archive
```

Expected: directory exists. May contain card subdirectories from existing live cards (do not modify).

---

## Phase 1a — Hold-out OOS as Gate

**Goal:** Promote hold-out OOS from "signal #10" to a separate gate. Backend computes hold-out PF on a locked trailing window. Pipeline gets a Hold-out column. Score modal gets a dedicated PASS/FAIL section at the top.

**Files:**
- Create: `tradelab/src/tradelab/robustness/holdout.py`
- Create: `tradelab/tests/unit/test_holdout.py`
- Modify: `tradelab/tradelab.yaml` (add `hold_out_*` thresholds)
- Modify: `tradelab/src/tradelab/config.py` (extend `RobustnessThresholds`)
- Modify: `tradelab/src/tradelab/engines/walkforward.py` (carve hold-out window)
- Modify: `tradelab/src/tradelab/robustness/verdict.py` (gate, not signal)
- Modify: `tradelab/src/tradelab/web/handlers.py` (extend robustness endpoint)
- Modify: `C:\TradingScripts\command_center.html` (Pipeline column + Score modal section)

### Tasks

- [ ] **Step 1a.1: Add hold-out thresholds to yaml**

Edit `tradelab/tradelab.yaml`. Inside `robustness.thresholds:` block, append:

```yaml
    hold_out_robust_pf: 1.5
    hold_out_fragile_pf: 1.0
    hold_out_window_months: 6
    hold_out_min_trades: 10
```

- [ ] **Step 1a.2: Extend `RobustnessThresholds` pydantic model**

Edit `tradelab/src/tradelab/config.py`. Find `class RobustnessThresholds` (grep first: `grep -n "class RobustnessThresholds" src/tradelab/config.py`). Add four fields with same defaults as yaml:

```python
    hold_out_robust_pf: float = 1.5
    hold_out_fragile_pf: float = 1.0
    hold_out_window_months: int = 6
    hold_out_min_trades: int = 10
```

- [ ] **Step 1a.3: Write failing test for HoldoutResult**

Create `tradelab/tests/unit/test_holdout.py`:

```python
from tradelab.robustness.holdout import HoldoutResult, evaluate_holdout


def test_holdout_pass_above_threshold():
    result = evaluate_holdout(
        holdout_pf=1.78,
        holdout_trades=23,
        robust_threshold=1.5,
        fragile_threshold=1.0,
        min_trades=10,
    )
    assert result.gate == "pass"
    assert result.pf == 1.78
    assert result.trades == 23
    assert "1.78" in result.reason


def test_holdout_fail_below_fragile_threshold():
    result = evaluate_holdout(
        holdout_pf=0.91,
        holdout_trades=18,
        robust_threshold=1.5,
        fragile_threshold=1.0,
        min_trades=10,
    )
    assert result.gate == "fail"
    assert "0.91" in result.reason


def test_holdout_inconclusive_between_thresholds():
    result = evaluate_holdout(
        holdout_pf=1.20,
        holdout_trades=15,
        robust_threshold=1.5,
        fragile_threshold=1.0,
        min_trades=10,
    )
    assert result.gate == "inconclusive"


def test_holdout_inconclusive_when_too_few_trades():
    result = evaluate_holdout(
        holdout_pf=2.0,
        holdout_trades=4,
        robust_threshold=1.5,
        fragile_threshold=1.0,
        min_trades=10,
    )
    assert result.gate == "inconclusive"
    assert "trades" in result.reason.lower()
```

- [ ] **Step 1a.4: Run test, verify it fails**

```bash
cd /c/TradingScripts/tradelab && python -m pytest tests/unit/test_holdout.py -v
```

Expected: ImportError on `tradelab.robustness.holdout`.

- [ ] **Step 1a.5: Implement `holdout.py`**

Create `tradelab/src/tradelab/robustness/holdout.py`:

```python
"""Hold-out OOS gate. Distinct from the 9 robustness signals.

Hold-out is computed on an untouched trailing window. Unlike the other
signals (which run on data that touched optimization), hold-out is the
only test that proves no leakage. Treated as a gate, not a vote.
"""
from __future__ import annotations

from pydantic import BaseModel


class HoldoutResult(BaseModel):
    """Hold-out gate outcome."""
    gate: str   # "pass" | "fail" | "inconclusive"
    pf: float
    trades: int
    reason: str


def evaluate_holdout(
    holdout_pf: float,
    holdout_trades: int,
    robust_threshold: float,
    fragile_threshold: float,
    min_trades: int,
) -> HoldoutResult:
    """Evaluate hold-out gate using robust/fragile thresholds.

    pf >= robust_threshold AND trades >= min_trades  -> pass
    pf <  fragile_threshold                          -> fail
    otherwise                                        -> inconclusive
    """
    if holdout_trades < min_trades:
        return HoldoutResult(
            gate="inconclusive",
            pf=holdout_pf,
            trades=holdout_trades,
            reason=f"insufficient trades ({holdout_trades} < {min_trades})",
        )
    if holdout_pf >= robust_threshold:
        return HoldoutResult(
            gate="pass",
            pf=holdout_pf,
            trades=holdout_trades,
            reason=f"hold-out PF {holdout_pf:.2f} >= {robust_threshold:.2f}",
        )
    if holdout_pf < fragile_threshold:
        return HoldoutResult(
            gate="fail",
            pf=holdout_pf,
            trades=holdout_trades,
            reason=f"hold-out PF {holdout_pf:.2f} < {fragile_threshold:.2f}",
        )
    return HoldoutResult(
        gate="inconclusive",
        pf=holdout_pf,
        trades=holdout_trades,
        reason=f"hold-out PF {holdout_pf:.2f} between {fragile_threshold:.2f} and {robust_threshold:.2f}",
    )
```

- [ ] **Step 1a.6: Run test, verify it passes**

```bash
cd /c/TradingScripts/tradelab && python -m pytest tests/unit/test_holdout.py -v
```

Expected: 4 passed.

- [ ] **Step 1a.7: Extend walkforward to compute hold-out window**

Read `tradelab/src/tradelab/engines/walkforward.py` end-to-end first. Find where the WF result is assembled (look for `WalkForwardResult(...)`). The hold-out window must be carved from the end of `data_end` minus `hold_out_window_months` months and never used in any optimization fold.

Add to `walkforward.py` after existing imports:

```python
from datetime import datetime
from dateutil.relativedelta import relativedelta
from ..robustness.holdout import HoldoutResult, evaluate_holdout
```

Add helper:

```python
def _carve_holdout_window(data_end: str, months: int) -> tuple[str, str]:
    """Return (holdout_start, holdout_end) ISO date strings."""
    end = datetime.fromisoformat(data_end)
    start = end - relativedelta(months=months)
    return start.date().isoformat(), end.date().isoformat()
```

Find where the WF runs each fold (search for `for window in windows`). After all folds complete, before returning the result, run a backtest on the carved hold-out window using the **best params from the final fold** (no re-optimization), and store it on the result.

Show the engineer the exact insertion: locate the line that constructs `WalkForwardResult(...)` and prepend the hold-out backtest. Conceptually:

```python
holdout_start, holdout_end = _carve_holdout_window(
    bt_config.data_end,
    cfg.robustness.thresholds.hold_out_window_months,
)
holdout_bt = run_backtest(
    strategy=strategy,
    data_start=holdout_start,
    data_end=holdout_end,
    params=best_params_from_last_fold,
)
holdout_result = evaluate_holdout(
    holdout_pf=holdout_bt.metrics.profit_factor,
    holdout_trades=len(holdout_bt.trades),
    robust_threshold=cfg.robustness.thresholds.hold_out_robust_pf,
    fragile_threshold=cfg.robustness.thresholds.hold_out_fragile_pf,
    min_trades=cfg.robustness.thresholds.hold_out_min_trades,
)
```

Then attach `holdout_result` and `holdout_bt` to the WF result (extend `WalkForwardResult` in `tradelab/src/tradelab/results.py` to add `holdout: Optional[HoldoutResult] = None` field first).

- [ ] **Step 1a.8: Test the walkforward integration**

Add to `tests/engines/` (search for existing test file or create `test_walkforward_holdout.py`):

```python
def test_walkforward_emits_holdout_result(tmp_path, monkeypatch):
    # Use canary or smoke_5 universe to keep test fast
    from tradelab.cli_run import run_pipeline
    result = run_pipeline(
        strategy="rand_canary",
        universe="smoke_5",
        flags=["wf"],
        output_dir=tmp_path,
    )
    wf = result.walkforward
    assert wf.holdout is not None
    assert wf.holdout.gate in {"pass", "fail", "inconclusive"}
    assert wf.holdout.pf > 0
```

Verify it exercises the new path:

```bash
cd /c/TradingScripts/tradelab && python -m pytest tests/engines/test_walkforward_holdout.py -v
```

- [ ] **Step 1a.9: Wire hold-out as gate in verdict.py**

Read `tradelab/src/tradelab/robustness/verdict.py` end-to-end. Find `compute_verdict(...)`. Add a parameter:

```python
def compute_verdict(
    bt: BacktestResult,
    dsr: Optional[float] = None,
    mc: Optional[MonteCarloResult] = None,
    landscape: Optional[ParamLandscapeResult] = None,
    entry_delay: Optional[EntryDelayResult] = None,
    loso: Optional[LOSOResult] = None,
    wf: Optional[WalkForwardResult] = None,
    noise: Optional[NoiseInjectionResult] = None,
    holdout: Optional[HoldoutResult] = None,    # NEW
) -> VerdictResult:
```

After signal aggregation but before final verdict computation, apply gate logic:

```python
# Hold-out is a gate, not a vote. If hold-out fails, verdict cannot be ROBUST.
if holdout is not None and holdout.gate == "fail":
    final_verdict = "FRAGILE"
    signals.insert(0, VerdictSignal(
        name="hold_out_gate",
        outcome="fragile",
        reason=f"GATE FAIL: {holdout.reason}",
    ))
    return VerdictResult(verdict=final_verdict, signals=signals)
```

Place this BEFORE the existing FRAGILE/INCONCLUSIVE/ROBUST aggregation logic. Hold-out fail short-circuits.

Add the `from .holdout import HoldoutResult` import.

- [ ] **Step 1a.10: Test verdict gate behavior**

Add to existing `tests/robustness/test_verdict.py` (or create) — grep first to find the existing test file:

```bash
grep -rln "test_compute_verdict\|test_verdict" /c/TradingScripts/tradelab/tests/
```

Add test:

```python
from tradelab.robustness.verdict import compute_verdict
from tradelab.robustness.holdout import HoldoutResult

def test_verdict_holdout_fail_forces_fragile(make_robust_inputs):
    """A run where 9 signals all PASS but hold-out fails must be FRAGILE."""
    inputs = make_robust_inputs()  # fixture returning all-pass signal results
    holdout = HoldoutResult(gate="fail", pf=0.85, trades=15,
                            reason="hold-out PF 0.85 < 1.00")
    result = compute_verdict(**inputs, holdout=holdout)
    assert result.verdict == "FRAGILE"
    assert any(s.name == "hold_out_gate" for s in result.signals)
```

Run: `python -m pytest tests/robustness/ -v -k holdout`

- [ ] **Step 1a.11: Update suite.py to pass hold-out to verdict**

Find `tradelab/src/tradelab/robustness/suite.py`. Locate where `compute_verdict(...)` is called. Pass `holdout=wf.holdout if wf else None`:

```python
verdict = compute_verdict(
    bt=bt,
    dsr=dsr,
    mc=mc,
    landscape=landscape,
    entry_delay=entry_delay,
    loso=loso,
    wf=wf,
    noise=noise,
    holdout=wf.holdout if wf else None,   # NEW
)
```

Run full test suite: `python -m pytest tests/ -q` — expected all green.

- [ ] **Step 1a.12: Extend `/tradelab/runs/<run_id>/robustness` endpoint to include holdout**

Read `tradelab/src/tradelab/web/handlers.py` and find the existing robustness handler (grep `def.*robustness` or the route registration). It currently reads `robustness_result.json`. Extend it to also include `holdout` field if present in the run folder's `walkforward_result.json` or wherever WalkForwardResult is persisted (verify by checking what `<reports>/<run_id>/` contains for an existing run).

Pseudocode:

```python
def handle_robustness(run_id: str) -> dict:
    folder = report_folder_for(run_id)
    rob = json.loads((folder / "robustness_result.json").read_text())
    wf_path = folder / "walkforward_result.json"
    if wf_path.exists():
        wf_data = json.loads(wf_path.read_text())
        if wf_data.get("holdout"):
            rob["holdout"] = wf_data["holdout"]
    return rob
```

Add handler test in `tests/web/test_handlers_validation.py` (new file):

```python
def test_robustness_endpoint_includes_holdout(tmp_run_with_holdout):
    response = client.get(f"/tradelab/runs/{tmp_run_with_holdout}/robustness")
    body = response.json()
    assert "holdout" in body
    assert body["holdout"]["gate"] in {"pass", "fail", "inconclusive"}
```

Use existing test client fixtures from `tests/web/conftest.py`.

- [ ] **Step 1a.13: Frontend — add Hold-out column to Pipeline table**

Edit `C:\TradingScripts\command_center.html`. Search for the Pipeline table — likely `id="pipelineTable"` or `<table class="pipeline">` (grep first):

```bash
grep -n "pipelineTable\|<thead>" /c/TradingScripts/command_center.html | head -20
```

Find the Pipeline table's `<thead>` row in the Research tab. Insert a new `<th>` between Verdict and PF columns:

```html
<th>Hold-out</th>
```

Find the row template (a JS function like `renderPipelineRow(...)` or template literal). Add a `<td>` cell:

```javascript
const holdoutCell = run.holdout
  ? `<td class="${run.holdout.gate === 'pass' ? 'gate-pass' : 'gate-fail'}">${
      run.holdout.gate === 'pass' ? '✓' : '✗'} PF ${run.holdout.pf.toFixed(2)}</td>`
  : '<td class="gate-na">—</td>';
```

Add CSS (find existing palette section):

```css
.gate-pass { color: #22c55e; font-weight: 600; }
.gate-fail { color: #ef4444; font-weight: 600; }
.gate-na   { color: #6b7280; }
```

The row template must request hold-out data — extend the fetch URL in the table loader to include `?include=holdout` or update audit_reader to include hold-out in the standard runs response. Simpler: add to the existing run-fetch path so hold-out is always present (extend `audit_reader.py` if needed).

- [ ] **Step 1a.14: Frontend — add Hold-out gate section to Score modal**

Find the Score modal in `command_center.html` (grep `scoreModal\|Score modal`). Locate where the Robustness signals are rendered (likely a function `renderScoreModal(run)`).

At the TOP of the modal body, before the diagnostics/signals section, insert:

```html
<div id="holdoutGate" class="holdout-gate"></div>
```

Add render logic:

```javascript
function renderHoldoutGate(holdout) {
  const el = document.getElementById('holdoutGate');
  if (!holdout) {
    el.innerHTML = '<div class="muted">No hold-out data — run with --robustness or --full</div>';
    return;
  }
  const passClass = holdout.gate === 'pass' ? 'pass' : 'fail';
  const icon = holdout.gate === 'pass' ? '●' : '●';
  el.className = `holdout-gate ${passClass}`;
  el.innerHTML = `
    <div class="left">
      <div class="icon ${passClass}">${icon}</div>
      <div>
        <div class="label">Hold-out OOS Gate</div>
        <div class="verdict-text ${passClass}">${holdout.gate.toUpperCase()}</div>
      </div>
    </div>
    <div class="detail">
      PF <strong>${holdout.pf.toFixed(2)}</strong> on ${holdout.trades} trades<br/>
      ${holdout.reason}
    </div>`;
}
```

Use the same CSS patterns shown in `docs/superpowers/mockups/research_tab_redesign_proposal.html` (`.holdout-gate.pass`, `.holdout-gate.fail`).

- [ ] **Step 1a.15: Hand-smoke Phase 1a**

```powershell
Stop-Process -Id (Get-NetTCPConnection -LocalPort 8877 -State Listen -ErrorAction SilentlyContinue).OwningProcess -Force -ErrorAction SilentlyContinue
$env:PYTHONIOENCODING = "utf-8"
cd C:\TradingScripts
python launch_dashboard.py
```

Browser: `http://localhost:8877#tab=research`. Verify:
- Pipeline table has a Hold-out column with `✓ PF X.XX` or `✗ PF X.XX` for each row
- Click a Robustness or Full run → Score modal opens with Hold-out gate banner at top
- A run that ran without `--robustness`/`--full` shows "No hold-out data — run with..."
- Old runs (created before this slice) show `—` in Hold-out column without crashing

- [ ] **Step 1a.16: Commit Phase 1a**

```bash
cd /c/TradingScripts/tradelab
git add -A   # review with git status first
git status   # verify nothing unintended
git commit -m "$(cat <<'EOF'
feat(robustness): hold-out OOS as a gate, not a signal

- New tradelab.robustness.holdout module
- Walk-forward emits hold-out backtest on locked trailing window
- Hold-out fail short-circuits verdict to FRAGILE (gate, not vote)
- Pipeline table gets Hold-out column
- Score modal gets dedicated hold-out gate section at top

Closes Phase 1a of validation redesign (spec 2026-04-28).
EOF
)"
```

Also commit `command_center.html` from `C:\TradingScripts\` separately if it's in a different git repo (per memory: dashboard html is at top-level `C:\TradingScripts\`).

---

## Phase 1b — Relative Context in Score Modal

**Goal:** Each diagnostic in the Score modal gets anchored to the user's live-card track record (median + worst + rank). Pure frontend + small audit_reader extension.

**Files:**
- Modify: `tradelab/src/tradelab/web/audit_reader.py` (compute live-card medians)
- Modify: `tradelab/src/tradelab/web/handlers.py` (`/tradelab/strategies` returns aggregates)
- Modify: `C:\TradingScripts\command_center.html` (Relative context section render)
- Test: `tradelab/tests/web/test_handlers_validation.py`

### Tasks

- [ ] **Step 1b.1: Write failing test for live-card aggregates endpoint**

Add to `tests/web/test_handlers_validation.py`:

```python
def test_strategies_endpoint_includes_relative_aggregates(client_with_live_cards):
    response = client_with_live_cards.get("/tradelab/strategies")
    body = response.json()
    assert "aggregates" in body
    agg = body["aggregates"]
    assert "pf_median" in agg
    assert "pf_worst" in agg
    assert "dsr_median" in agg
    assert "dsr_worst" in agg
    assert "dd_median" in agg
    assert "dd_worst" in agg
    assert "n_cards" in agg
```

Use existing `client_with_live_cards` fixture (grep tests/web/conftest.py to confirm name; create if missing).

- [ ] **Step 1b.2: Run test, verify it fails**

```bash
cd /c/TradingScripts/tradelab && python -m pytest tests/web/test_handlers_validation.py::test_strategies_endpoint_includes_relative_aggregates -v
```

Expected: KeyError on "aggregates".

- [ ] **Step 1b.3: Extend audit_reader to compute aggregates**

Read `tradelab/src/tradelab/web/audit_reader.py`. Find the function that produces the strategies-list response. Add helper:

```python
import statistics

def compute_live_aggregates(live_cards: list[dict]) -> dict:
    if not live_cards:
        return {"n_cards": 0}
    pfs = [c.get("pf", 0) for c in live_cards if c.get("pf") is not None]
    dsrs = [c.get("dsr", 0) for c in live_cards if c.get("dsr") is not None]
    dds = [c.get("dd_pct", 0) for c in live_cards if c.get("dd_pct") is not None]
    return {
        "n_cards": len(live_cards),
        "pf_median": statistics.median(pfs) if pfs else None,
        "pf_worst": min(pfs) if pfs else None,
        "dsr_median": statistics.median(dsrs) if dsrs else None,
        "dsr_worst": min(dsrs) if dsrs else None,
        "dd_median": statistics.median(dds) if dds else None,
        "dd_worst": min(dds) if dds else None,  # most negative
    }
```

Call it from the strategies handler and add to response under `"aggregates"` key.

- [ ] **Step 1b.4: Verify test passes**

```bash
cd /c/TradingScripts/tradelab && python -m pytest tests/web/test_handlers_validation.py -v
```

Expected: pass.

- [ ] **Step 1b.5: Frontend — render Relative Context section in Score modal**

Edit `command_center.html`. Locate Score modal render function. After Diagnostics section, insert:

```html
<div id="relativeContext" class="relative-context"></div>
```

Add render logic:

```javascript
async function renderRelativeContext(run) {
  const stratResponse = await fetch('/tradelab/strategies');
  const strat = await stratResponse.json();
  const agg = strat.aggregates || {};
  if (!agg.n_cards) {
    document.getElementById('relativeContext').innerHTML = '';
    return;
  }
  const m = run.metrics;
  const pfRank = computeRank(m.pf, strat.cards.map(c => c.pf));
  const html = `
    <h3>Relative context</h3>
    <div class="row"><span>Hold-out PF <strong>${(run.holdout?.pf ?? m.pf).toFixed(2)}</strong></span>
      <span class="rank">#${pfRank} of ${agg.n_cards} · live median ${agg.pf_median.toFixed(2)} · worst ${agg.pf_worst.toFixed(2)}</span></div>
    <div class="row"><span>DSR <strong>${m.dsr.toFixed(2)}</strong></span>
      <span class="rank">live median ${agg.dsr_median.toFixed(2)} · worst ${agg.dsr_worst.toFixed(2)}</span></div>
    <div class="row"><span>DD <strong>${m.dd_pct.toFixed(1)}%</strong></span>
      <span class="rank">live median ${agg.dd_median.toFixed(1)}% · worst ${agg.dd_worst.toFixed(1)}%</span></div>
  `;
  document.getElementById('relativeContext').innerHTML = html;
}

function computeRank(value, peers) {
  const sorted = [...peers, value].sort((a, b) => b - a);
  return sorted.indexOf(value) + 1;
}
```

Hook `renderRelativeContext(run)` into the existing Score modal open path.

- [ ] **Step 1b.6: Hand-smoke Phase 1b**

Restart dashboard. Open any pipeline row's Score modal. Verify Relative Context section appears below diagnostics with three rows (PF, DSR, DD). Empty-state when no live cards exist.

- [ ] **Step 1b.7: Commit Phase 1b**

```bash
cd /c/TradingScripts/tradelab
git add -A
git status
git commit -m "feat(web): relative context in Score modal — anchor candidate metrics to live-card median + worst"
```

---

## Phase 2 — Multi-Dimensional Correlation

**Goal:** Three pairwise statistics (return ρ + drawdown ρ + entry-time overlap) computed at Score time, persisted at Accept time. Score modal Portfolio Fit panel + Pipeline Corr column. Override flow at Accept.

**Files:**
- Create: `tradelab/src/tradelab/robustness/correlation.py`
- Create: `tradelab/src/tradelab/live/tracking_persistence.py`
- Create: `tradelab/tests/robustness/test_correlation.py`
- Create: `tradelab/tests/live/test_tracking_persistence.py`
- Modify: `tradelab/src/tradelab/live/cards.py` (call persistence at Accept)
- Modify: `tradelab/src/tradelab/web/handlers.py` (+ correlation endpoint)
- Modify: `tradelab/tradelab.yaml` (+ correlation thresholds)
- Modify: `tradelab/src/tradelab/config.py` (+ correlation thresholds in pydantic model)
- Modify: `C:\TradingScripts\command_center.html` (Pipeline column + Score modal panel)

### Tasks

- [ ] **Step 2.1: Add correlation thresholds to yaml + config**

Edit `tradelab/tradelab.yaml` `robustness.thresholds` block:

```yaml
    correlation_return_max: 0.70
    correlation_dd_max: 0.70
    correlation_entry_overlap_max: 0.30
    correlation_min_overlap_days: 60
```

Mirror in `RobustnessThresholds` pydantic model in `config.py`.

- [ ] **Step 2.2: Write failing test for return correlation**

Create `tradelab/tests/robustness/test_correlation.py`:

```python
import pandas as pd
from tradelab.robustness.correlation import (
    return_correlation,
    dd_correlation,
    entry_time_overlap,
    evaluate_portfolio_fit,
    PortfolioFitResult,
)


def test_return_correlation_perfect():
    a = pd.Series([0.01, -0.02, 0.03, 0.01], index=pd.date_range("2026-01-01", periods=4))
    b = pd.Series([0.02, -0.04, 0.06, 0.02], index=pd.date_range("2026-01-01", periods=4))
    rho = return_correlation(a, b, min_overlap_days=2)
    assert rho > 0.99


def test_return_correlation_insufficient_overlap_returns_none():
    a = pd.Series([0.01, -0.02], index=pd.date_range("2026-01-01", periods=2))
    b = pd.Series([0.02, -0.04], index=pd.date_range("2026-06-01", periods=2))
    rho = return_correlation(a, b, min_overlap_days=10)
    assert rho is None


def test_dd_correlation_independent():
    """DD correlation distinct from return correlation: same returns, different DD paths."""
    import numpy as np
    np.random.seed(42)
    a = pd.Series(np.random.randn(100) * 0.01, index=pd.date_range("2026-01-01", periods=100))
    b = pd.Series(np.random.randn(100) * 0.01, index=pd.date_range("2026-01-01", periods=100))
    return_rho = return_correlation(a, b, min_overlap_days=10)
    dd_rho = dd_correlation(a, b, min_overlap_days=10)
    assert dd_rho is not None
    # Different statistic — not necessarily equal to return rho
    assert isinstance(dd_rho, float)


def test_entry_time_overlap_high():
    candidate = pd.Series(pd.to_datetime([
        "2026-01-15 09:30", "2026-01-16 09:30", "2026-01-17 09:30"
    ]))
    existing = pd.Series(pd.to_datetime([
        "2026-01-15 09:33", "2026-01-16 09:35", "2026-01-17 09:31"
    ]))
    overlap = entry_time_overlap(candidate, existing, window_minutes=30)
    assert overlap == 1.0  # all 3 candidates within 30min of an existing entry


def test_entry_time_overlap_zero():
    candidate = pd.Series(pd.to_datetime(["2026-01-15 14:00", "2026-01-16 15:00"]))
    existing = pd.Series(pd.to_datetime(["2026-01-15 09:30", "2026-01-16 10:00"]))
    overlap = entry_time_overlap(candidate, existing, window_minutes=30)
    assert overlap == 0.0


def test_portfolio_fit_pass():
    cand_returns = pd.Series([0.01, -0.01, 0.02], index=pd.date_range("2026-01-01", periods=3))
    cand_entries = pd.Series(pd.to_datetime(["2026-01-15 14:00"]))
    live_cards = [
        {
            "card_id": "viprasol-amzn",
            "returns": pd.Series([0.005, 0.0, 0.001], index=pd.date_range("2026-01-01", periods=3)),
            "entries": pd.Series(pd.to_datetime(["2026-01-15 09:30"])),
        }
    ]
    result = evaluate_portfolio_fit(
        cand_returns=cand_returns,
        cand_entries=cand_entries,
        live_cards=live_cards,
        return_max=0.70,
        dd_max=0.70,
        entry_max=0.30,
        min_overlap_days=2,
    )
    assert result.gate == "pass"
    assert len(result.pairwise) == 1


def test_portfolio_fit_fail_on_high_return_corr():
    cand_returns = pd.Series([0.01, -0.02, 0.03], index=pd.date_range("2026-01-01", periods=3))
    cand_entries = pd.Series(pd.to_datetime(["2026-01-15 14:00"]))
    live_cards = [
        {
            "card_id": "near-clone",
            "returns": pd.Series([0.011, -0.021, 0.029], index=pd.date_range("2026-01-01", periods=3)),
            "entries": pd.Series(pd.to_datetime(["2026-01-15 09:30"])),
        }
    ]
    result = evaluate_portfolio_fit(
        cand_returns=cand_returns,
        cand_entries=cand_entries,
        live_cards=live_cards,
        return_max=0.70,
        dd_max=0.70,
        entry_max=0.30,
        min_overlap_days=2,
    )
    assert result.gate == "fail"
    assert result.return_max > 0.70
```

- [ ] **Step 2.3: Run test, verify it fails**

```bash
cd /c/TradingScripts/tradelab && python -m pytest tests/robustness/test_correlation.py -v
```

Expected: ImportError.

- [ ] **Step 2.4: Implement `correlation.py`**

Create `tradelab/src/tradelab/robustness/correlation.py`:

```python
"""Multi-dimensional pairwise correlation between a candidate strategy
and existing live cards.

Three statistics:
- return correlation: Pearson on aligned daily returns
- drawdown correlation: Pearson on rolling 30d max-drawdown series
- entry-time overlap: % of candidate entries within N minutes of an existing entry
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
from pydantic import BaseModel


class PairwiseCorrelation(BaseModel):
    card_id: str
    return_rho: Optional[float]
    dd_rho: Optional[float]
    entry_overlap: float


class PortfolioFitResult(BaseModel):
    gate: str             # "pass" | "fail"
    return_max: float
    dd_max: float
    entry_max: float
    pairwise: list[PairwiseCorrelation]


def _rolling_max_dd(returns: pd.Series, window: int = 30) -> pd.Series:
    """Rolling max-drawdown: cumulative return curve, peak-to-current dip."""
    cum = (1 + returns).cumprod()
    rolling_peak = cum.rolling(window=window, min_periods=1).max()
    return (cum - rolling_peak) / rolling_peak


def return_correlation(
    a: pd.Series,
    b: pd.Series,
    min_overlap_days: int,
) -> Optional[float]:
    """Pearson correlation on overlapping calendar days."""
    aligned = pd.concat([a, b], axis=1, join="inner").dropna()
    if len(aligned) < min_overlap_days:
        return None
    return float(aligned.iloc[:, 0].corr(aligned.iloc[:, 1]))


def dd_correlation(
    a: pd.Series,
    b: pd.Series,
    min_overlap_days: int,
    window: int = 30,
) -> Optional[float]:
    """Correlation of rolling drawdown depth between two return series."""
    dd_a = _rolling_max_dd(a, window=window)
    dd_b = _rolling_max_dd(b, window=window)
    aligned = pd.concat([dd_a, dd_b], axis=1, join="inner").dropna()
    if len(aligned) < min_overlap_days:
        return None
    return float(aligned.iloc[:, 0].corr(aligned.iloc[:, 1]))


def entry_time_overlap(
    candidate_entries: pd.Series,
    existing_entries: pd.Series,
    window_minutes: int = 30,
) -> float:
    """% of candidate entries within `window_minutes` of any existing entry."""
    if len(candidate_entries) == 0:
        return 0.0
    cand = pd.to_datetime(candidate_entries).sort_values().reset_index(drop=True)
    exist = pd.to_datetime(existing_entries).sort_values().reset_index(drop=True)
    if len(exist) == 0:
        return 0.0
    window_ns = pd.Timedelta(minutes=window_minutes).value
    overlapping = 0
    for ts in cand:
        # nearest existing entry by absolute time delta
        deltas = (exist - ts).abs()
        if deltas.min().value <= window_ns:
            overlapping += 1
    return overlapping / len(cand)


def evaluate_portfolio_fit(
    cand_returns: pd.Series,
    cand_entries: pd.Series,
    live_cards: list[dict],
    *,
    return_max: float,
    dd_max: float,
    entry_max: float,
    min_overlap_days: int,
    entry_window_minutes: int = 30,
) -> PortfolioFitResult:
    """Compute pairwise stats vs each live card; aggregate gate decision."""
    pairwise = []
    for card in live_cards:
        rc = return_correlation(cand_returns, card["returns"], min_overlap_days)
        dc = dd_correlation(cand_returns, card["returns"], min_overlap_days)
        eo = entry_time_overlap(cand_entries, card["entries"], window_minutes=entry_window_minutes)
        pairwise.append(PairwiseCorrelation(
            card_id=card["card_id"],
            return_rho=rc,
            dd_rho=dc,
            entry_overlap=eo,
        ))

    # Aggregate maxes (treat None as 0 for max computation)
    rmax = max([p.return_rho or 0 for p in pairwise], default=0.0)
    dmax = max([p.dd_rho or 0 for p in pairwise], default=0.0)
    emax = max([p.entry_overlap for p in pairwise], default=0.0)

    gate = "fail" if (rmax > return_max or dmax > dd_max or emax > entry_max) else "pass"

    return PortfolioFitResult(
        gate=gate,
        return_max=rmax,
        dd_max=dmax,
        entry_max=emax,
        pairwise=pairwise,
    )
```

- [ ] **Step 2.5: Verify all tests pass**

```bash
cd /c/TradingScripts/tradelab && python -m pytest tests/robustness/test_correlation.py -v
```

Expected: 7 passed.

- [ ] **Step 2.6: Write failing test for tracking_persistence**

Create `tradelab/tests/live/test_tracking_persistence.py`:

```python
from pathlib import Path

import pandas as pd
import pytest

from tradelab.live.tracking_persistence import persist_card_baseline, load_card_baseline


def test_persist_and_load_returns_drawdowns_entries(tmp_path):
    archive_dir = tmp_path / "pine_archive"
    returns = pd.Series([0.01, -0.02, 0.03], index=pd.date_range("2026-01-01", periods=3))
    drawdowns = pd.Series([0.0, -0.02, -0.01], index=pd.date_range("2026-01-01", periods=3))
    entries = pd.DatetimeIndex(["2026-01-15 09:30", "2026-01-16 14:00"])
    backtest_trades = pd.DataFrame({
        "entry_ts": pd.to_datetime(["2026-01-15 09:30", "2026-01-16 14:00"]),
        "exit_ts":  pd.to_datetime(["2026-01-15 15:30", "2026-01-16 15:30"]),
        "return_pct": [0.012, -0.008],
        "regime_label": ["LOW_VOL_TRENDING", "LOW_VOL_TRENDING"],
    })

    persist_card_baseline(
        archive_root=archive_dir,
        card_id="test-card-v1",
        returns=returns,
        drawdowns=drawdowns,
        entries=entries,
        backtest_trades=backtest_trades,
    )

    card_dir = archive_dir / "test-card-v1"
    assert (card_dir / "returns.csv").exists()
    assert (card_dir / "drawdowns.csv").exists()
    assert (card_dir / "entry_times.csv").exists()
    assert (card_dir / "backtest_trades.csv").exists()

    loaded = load_card_baseline(archive_root=archive_dir, card_id="test-card-v1")
    assert len(loaded["returns"]) == 3
    assert len(loaded["drawdowns"]) == 3
    assert len(loaded["entries"]) == 2
    assert len(loaded["backtest_trades"]) == 2


def test_load_missing_card_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_card_baseline(archive_root=tmp_path, card_id="does-not-exist")
```

- [ ] **Step 2.7: Implement `tracking_persistence.py`**

Create `tradelab/src/tradelab/live/tracking_persistence.py`:

```python
"""Persist per-card baseline data at Accept time.

Schema under pine_archive/<card_id>/:
  returns.csv          — daily returns
  drawdowns.csv        — daily rolling drawdown
  entry_times.csv      — every backtest entry timestamp + symbol
  backtest_trades.csv  — full trade ledger (used by Phase 4 K-S baseline)
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd


def persist_card_baseline(
    *,
    archive_root: Path,
    card_id: str,
    returns: pd.Series,
    drawdowns: pd.Series,
    entries: pd.DatetimeIndex,
    backtest_trades: pd.DataFrame,
) -> Path:
    """Write the four baseline CSVs. Returns the card directory path."""
    card_dir = Path(archive_root) / card_id
    card_dir.mkdir(parents=True, exist_ok=True)

    returns.to_csv(card_dir / "returns.csv", header=["return"], index_label="ts")
    drawdowns.to_csv(card_dir / "drawdowns.csv", header=["dd_pct"], index_label="ts")
    pd.DataFrame({"ts": entries}).to_csv(card_dir / "entry_times.csv", index=False)
    backtest_trades.to_csv(card_dir / "backtest_trades.csv", index=False)

    return card_dir


def load_card_baseline(
    *,
    archive_root: Path,
    card_id: str,
) -> dict:
    """Load the four baseline files. Raises FileNotFoundError if missing."""
    card_dir = Path(archive_root) / card_id
    if not card_dir.exists():
        raise FileNotFoundError(f"No baseline at {card_dir}")

    returns = pd.read_csv(card_dir / "returns.csv", index_col="ts", parse_dates=True).iloc[:, 0]
    drawdowns = pd.read_csv(card_dir / "drawdowns.csv", index_col="ts", parse_dates=True).iloc[:, 0]
    entries = pd.read_csv(card_dir / "entry_times.csv", parse_dates=["ts"])["ts"]
    bt_trades = pd.read_csv(card_dir / "backtest_trades.csv",
                            parse_dates=["entry_ts", "exit_ts"])

    return {
        "returns": returns,
        "drawdowns": drawdowns,
        "entries": entries,
        "backtest_trades": bt_trades,
    }
```

Verify: `python -m pytest tests/live/test_tracking_persistence.py -v` — expect 2 passed.

- [ ] **Step 2.8: Wire persistence into Accept flow**

Read `tradelab/src/tradelab/live/cards.py` end-to-end. Find the function that creates a card on Accept (search for `create_card\|accept_card\|cards.json`). After the card is written, call `persist_card_baseline(...)` with data drawn from the run's report folder.

Conceptually, the Accept handler in handlers.py looks up the Score run's report folder, reads the backtest_result.json, extracts the daily-returns + drawdowns + entries + trades, then calls `persist_card_baseline`. Alternative: do it in `cards.create_card(...)` taking those four pandas objects as args.

Write a test:

```python
def test_accept_persists_baseline(tmp_path, monkeypatch):
    # Wire pine_archive root to tmp_path
    monkeypatch.setattr("tradelab.live.tracking_persistence.DEFAULT_ARCHIVE",
                        tmp_path / "pine_archive")
    # Use a mock run with synthetic backtest output
    from tradelab.live.cards import create_card_from_run
    create_card_from_run(card_id="test-v1", run_id="...", ...)
    # Assert the four CSVs exist
    assert (tmp_path / "pine_archive" / "test-v1" / "returns.csv").exists()
```

Adjust per the actual `cards.py` API discovered by reading.

- [ ] **Step 2.9: Build `/tradelab/correlation/<run_id>` endpoint**

Add to `handlers.py`:

```python
def handle_correlation(run_id: str) -> dict:
    """Compute candidate's portfolio fit vs all enabled live cards."""
    cfg = get_config()
    folder = report_folder_for(run_id)
    bt = load_backtest_result(folder)

    cand_returns = bt.daily_returns()  # implement this on BacktestResult if missing
    cand_entries = pd.to_datetime([t.entry_ts for t in bt.trades])

    live_cards = []
    for card in load_live_cards():
        try:
            baseline = load_card_baseline(
                archive_root=Path(cfg.paths.pine_archive_dir),
                card_id=card.card_id,
            )
            live_cards.append({
                "card_id": card.card_id,
                "returns": baseline["returns"],
                "entries": pd.to_datetime(baseline["entries"]),
            })
        except FileNotFoundError:
            continue   # legacy card without baseline; skip

    result = evaluate_portfolio_fit(
        cand_returns=cand_returns,
        cand_entries=cand_entries,
        live_cards=live_cards,
        return_max=cfg.robustness.thresholds.correlation_return_max,
        dd_max=cfg.robustness.thresholds.correlation_dd_max,
        entry_max=cfg.robustness.thresholds.correlation_entry_overlap_max,
        min_overlap_days=cfg.robustness.thresholds.correlation_min_overlap_days,
    )
    return result.model_dump()
```

Wire into the route dispatcher. Add `paths.pine_archive_dir` to config (default to `<tradelab>/pine_archive`).

Add handler test in `test_handlers_validation.py`:

```python
def test_correlation_endpoint_returns_pairwise(client_with_baseline_cards):
    response = client_with_baseline_cards.get("/tradelab/correlation/some_run_id")
    body = response.json()
    assert "gate" in body
    assert body["gate"] in {"pass", "fail"}
    assert "pairwise" in body
    for p in body["pairwise"]:
        assert "card_id" in p
        assert "return_rho" in p
        assert "dd_rho" in p
        assert "entry_overlap" in p
```

- [ ] **Step 2.10: Frontend — Pipeline Corr column**

Edit `command_center.html`. After the Hold-out column, add `<th>Corr</th>`. In row template:

```javascript
const corrCell = run.correlation
  ? `<td class="corr-cell ${corrClass(run.correlation.return_max)}">${run.correlation.return_max.toFixed(2)}</td>`
  : '<td class="corr-cell na">—</td>';

function corrClass(r) {
  if (r > 0.70) return 'fail';
  if (r > 0.50) return 'warn';
  return 'ok';
}
```

The pipeline-row data needs `correlation` populated — extend the runs endpoint to inline-call `handle_correlation` for the latest run, OR fetch lazily on row hover. Simpler: ship without inline correlation in v1 of this column, render `—` until score-time. (If you want the column live always, fetch in batch in the runs handler.)

- [ ] **Step 2.11: Frontend — Score modal Portfolio Fit panel**

In Score modal, after Relative Context, insert:

```html
<div id="portfolioFit" class="portfolio-fit"></div>
```

Render:

```javascript
async function renderPortfolioFit(runId) {
  const r = await fetch(`/tradelab/correlation/${runId}`);
  if (!r.ok) {
    document.getElementById('portfolioFit').innerHTML = '';
    return;
  }
  const fit = await r.json();
  const rows = fit.pairwise.map(p => `
    <div class="fit-row">
      <span class="name">${p.card_id}</span>
      <span class="val">${p.return_rho?.toFixed(2) ?? '—'}</span>
      <span class="val">${p.dd_rho?.toFixed(2) ?? '—'}</span>
      <span class="val">${(p.entry_overlap * 100).toFixed(0)}%</span>
    </div>`).join('');
  document.getElementById('portfolioFit').innerHTML = `
    <h3>Portfolio fit ${fit.gate === 'fail' ? '⚠ FAIL' : '✓'}</h3>
    <div class="legend-row">
      <span>Live card</span><span>Return ρ</span><span>DD ρ</span><span>Entry overlap</span>
    </div>
    ${rows}
    <div class="summary">
      Max return ρ: ${fit.return_max.toFixed(2)} ·
      Max DD ρ: ${fit.dd_max.toFixed(2)} ·
      Max entry overlap: ${(fit.entry_max * 100).toFixed(0)}%
    </div>`;
  // Disable Accept button if gate failed
  const accept = document.getElementById('acceptBtn');
  if (accept) accept.disabled = fit.gate === 'fail';
}
```

- [ ] **Step 2.12: Override flow on Accept**

Add an "Override" link near the disabled Accept button. Clicking opens a confirm prompt requiring typed reason:

```javascript
async function tryAccept(runId, candidateId, fit) {
  if (fit.gate === 'pass') {
    return doAccept(runId, candidateId);
  }
  const reason = prompt(
    `Portfolio Fit failed (return ${fit.return_max.toFixed(2)}, DD ${fit.dd_max.toFixed(2)}, entry ${(fit.entry_max*100).toFixed(0)}%).\n\nType OVERRIDE plus a reason to proceed:`
  );
  if (!reason || !reason.startsWith('OVERRIDE ')) return;
  const justification = reason.slice('OVERRIDE '.length);
  await fetch(`/tradelab/cards/${candidateId}/accept-override`, {
    method: 'POST',
    body: JSON.stringify({ run_id: runId, reason: justification, gate: 'portfolio_fit', values: fit }),
  });
  return doAccept(runId, candidateId);
}
```

Backend: append override entry to `pine_archive/<card_id>/overrides.jsonl` and proceed with normal accept.

- [ ] **Step 2.13: Hand-smoke Phase 2**

Restart dashboard. For at least one Score run, open Score modal → verify Portfolio Fit panel renders with rows for each live card. Test override prompt by manually editing a card's returns to be near-clone of the candidate, observe Accept button disabled, then test override path. Pipeline Corr column shows or `—` for each row.

- [ ] **Step 2.14: Commit Phase 2**

```bash
git add -A; git status
git commit -m "feat(robustness): multi-dim portfolio-fit gate (return + DD + entry-time correlation)"
```

---

## Phase 3 — Regime Conditioning

**Goal:** Classify market regime (vol/trend/breadth), bucket strategy performance per regime, expose regime banner + per-strategy regime-fit. Existing regime thresholds in yaml are reused.

**Files:**
- Create: `tradelab/src/tradelab/regime.py`
- Create: `tradelab/tests/unit/test_regime.py`
- Modify: `tradelab/src/tradelab/results.py` (add `regime_breakdown` field)
- Modify: `tradelab/src/tradelab/engines/backtest.py` (tag bars + compute breakdown)
- Modify: `tradelab/src/tradelab/web/handlers.py` (+ /tradelab/regime endpoint)
- Modify: `C:\TradingScripts\command_center.html` (banner + Pipeline col + Score modal table + Live card tag)
- Modify: `tradelab/tradelab.yaml` (regime cutoffs already partially present; add `regime_classifier:` block)
- Modify: `tradelab/src/tradelab/config.py` (add classifier config)

### Tasks

- [ ] **Step 3.1: Add regime classifier config to yaml**

Edit `tradelab.yaml`. Add new top-level block:

```yaml
regime_classifier:
  vix_low_max: 15.0
  vix_high_min: 25.0
  adx_trend_min: 20.0
  ma50_ma200_required: true
  breadth_broad_min: 60.0
  breadth_narrow_max: 40.0
  cache_ttl_seconds: 3600
```

Mirror in `config.py` with new pydantic model `RegimeClassifierConfig`.

- [ ] **Step 3.2: Write failing test for regime classifier**

Create `tradelab/tests/unit/test_regime.py`:

```python
import pandas as pd

from tradelab.regime import (
    RegimeLabel,
    classify_volatility,
    classify_trend,
    classify_breadth,
    classify,
)


def test_classify_volatility_low():
    bars = pd.DataFrame({"vix": [10, 11, 12, 13]},
                         index=pd.date_range("2026-01-01", periods=4))
    assert classify_volatility(bars, low_max=15, high_min=25) == "LOW"


def test_classify_volatility_high():
    bars = pd.DataFrame({"vix": [28, 30, 27, 26]},
                         index=pd.date_range("2026-01-01", periods=4))
    assert classify_volatility(bars, low_max=15, high_min=25) == "HIGH"


def test_classify_trend_trending():
    # SPX above 50d AND 200d; ADX >= 20
    bars = pd.DataFrame({
        "close": [400, 405, 410, 415],
        "sma50": [380, 382, 385, 388],
        "sma200": [350, 351, 352, 353],
        "adx": [25, 26, 27, 28],
    }, index=pd.date_range("2026-01-01", periods=4))
    assert classify_trend(bars, adx_min=20, ma50_ma200_required=True) == "TRENDING"


def test_classify_trend_ranging_when_below_ma():
    bars = pd.DataFrame({
        "close": [400, 395, 390, 385],
        "sma50": [410, 408, 405, 402],
        "sma200": [380, 381, 382, 383],
        "adx": [12, 13, 11, 14],
    }, index=pd.date_range("2026-01-01", periods=4))
    assert classify_trend(bars, adx_min=20, ma50_ma200_required=True) == "RANGING"


def test_classify_breadth():
    bars = pd.DataFrame({"breadth_pct_above_50d": [65, 70, 68, 72]},
                         index=pd.date_range("2026-01-01", periods=4))
    assert classify_breadth(bars, broad_min=60, narrow_max=40) == "BROAD"


def test_combined_label():
    bars = pd.DataFrame({
        "vix": [12, 13, 14, 12],
        "close": [400, 405, 410, 415],
        "sma50": [380, 382, 385, 388],
        "sma200": [350, 351, 352, 353],
        "adx": [25, 26, 27, 28],
        "breadth_pct_above_50d": [65, 70, 68, 72],
    }, index=pd.date_range("2026-01-01", periods=4))
    label = classify(bars, vix_low_max=15, vix_high_min=25,
                     adx_min=20, ma50_ma200_required=True,
                     breadth_broad_min=60, breadth_narrow_max=40)
    assert isinstance(label, RegimeLabel)
    assert label.volatility == "LOW"
    assert label.trend == "TRENDING"
    assert label.breadth == "BROAD"
    assert label.combined == "LOW_TRENDING_BROAD"
```

- [ ] **Step 3.3: Implement `regime.py`**

Create `tradelab/src/tradelab/regime.py`:

```python
"""Market regime classifier.

Three independent classifiers combined into a single label:
- volatility: VIX-based (LOW / MID / HIGH)
- trend: SPX vs 50/200 MA + ADX (TRENDING / RANGING)
- breadth: % of S&P 500 above 50d MA (BROAD / MIXED / NARROW)

Combined label e.g. "LOW_TRENDING_BROAD".
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
from pydantic import BaseModel


class RegimeLabel(BaseModel):
    volatility: str   # "LOW" | "MID" | "HIGH" | "UNKNOWN"
    trend: str        # "TRENDING" | "RANGING" | "UNKNOWN"
    breadth: str      # "BROAD" | "MIXED" | "NARROW" | "UNKNOWN"

    @property
    def combined(self) -> str:
        return f"{self.volatility}_{self.trend}_{self.breadth}"


def classify_volatility(bars: pd.DataFrame, *, low_max: float, high_min: float) -> str:
    if "vix" not in bars.columns or bars["vix"].isna().all():
        return "UNKNOWN"
    latest = bars["vix"].iloc[-1]
    if latest <= low_max:
        return "LOW"
    if latest >= high_min:
        return "HIGH"
    return "MID"


def classify_trend(bars: pd.DataFrame, *, adx_min: float, ma50_ma200_required: bool) -> str:
    needed = {"close", "sma50", "sma200", "adx"}
    if not needed.issubset(bars.columns):
        return "UNKNOWN"
    last = bars.iloc[-1]
    if pd.isna(last["adx"]):
        return "UNKNOWN"
    above_ma = (last["close"] > last["sma50"]) and (last["close"] > last["sma200"])
    is_trending = last["adx"] >= adx_min and (above_ma or not ma50_ma200_required)
    return "TRENDING" if is_trending else "RANGING"


def classify_breadth(bars: pd.DataFrame, *, broad_min: float, narrow_max: float) -> str:
    if "breadth_pct_above_50d" not in bars.columns:
        return "UNKNOWN"
    latest = bars["breadth_pct_above_50d"].iloc[-1]
    if pd.isna(latest):
        return "UNKNOWN"
    if latest >= broad_min:
        return "BROAD"
    if latest <= narrow_max:
        return "NARROW"
    return "MIXED"


def classify(
    bars: pd.DataFrame,
    *,
    vix_low_max: float,
    vix_high_min: float,
    adx_min: float,
    ma50_ma200_required: bool,
    breadth_broad_min: float,
    breadth_narrow_max: float,
) -> RegimeLabel:
    return RegimeLabel(
        volatility=classify_volatility(bars, low_max=vix_low_max, high_min=vix_high_min),
        trend=classify_trend(bars, adx_min=adx_min, ma50_ma200_required=ma50_ma200_required),
        breadth=classify_breadth(bars, broad_min=breadth_broad_min, narrow_max=breadth_narrow_max),
    )


def classify_each_bar(
    bars: pd.DataFrame,
    *,
    vix_low_max: float,
    vix_high_min: float,
    adx_min: float,
    ma50_ma200_required: bool,
    breadth_broad_min: float,
    breadth_narrow_max: float,
) -> pd.Series:
    """Return per-bar regime label as a string Series."""
    labels = []
    for i in range(len(bars)):
        sub = bars.iloc[: i + 1]
        label = classify(sub,
            vix_low_max=vix_low_max, vix_high_min=vix_high_min,
            adx_min=adx_min, ma50_ma200_required=ma50_ma200_required,
            breadth_broad_min=breadth_broad_min, breadth_narrow_max=breadth_narrow_max,
        )
        labels.append(label.combined)
    return pd.Series(labels, index=bars.index, name="regime")
```

Run: `python -m pytest tests/unit/test_regime.py -v` — expect 6 passed.

- [ ] **Step 3.4: Persist regime breakdown in BacktestResult**

Read `tradelab/src/tradelab/results.py`. Add to `BacktestResult`:

```python
class RegimeBreakdown(BaseModel):
    label: str
    n_trades: int
    profit_factor: Optional[float]
    sharpe: Optional[float]
    avg_dd_pct: Optional[float]


# On BacktestResult:
regime_breakdown: list[RegimeBreakdown] = Field(default_factory=list)
```

In `tradelab/src/tradelab/engines/backtest.py` (search for where `BacktestResult` is constructed), after trades are computed, attach regime to each trade by classifying the bar at its entry timestamp:

```python
from ..regime import classify_each_bar
from ..config import get_config

cfg = get_config()
rc = cfg.regime_classifier
regime_series = classify_each_bar(
    bars, vix_low_max=rc.vix_low_max, vix_high_min=rc.vix_high_min,
    adx_min=rc.adx_trend_min, ma50_ma200_required=rc.ma50_ma200_required,
    breadth_broad_min=rc.breadth_broad_min, breadth_narrow_max=rc.breadth_narrow_max,
)
for t in trades:
    t.regime = regime_series.loc[t.entry_ts] if t.entry_ts in regime_series.index else "UNKNOWN"

# Compute breakdown
breakdown = []
for label, group in groupby_regime(trades):
    pf = compute_pf(group)
    breakdown.append(RegimeBreakdown(
        label=label, n_trades=len(group), profit_factor=pf, ...
    ))
result.regime_breakdown = breakdown
```

Trade dataclass needs a `regime: str = "UNKNOWN"` field. Verify the existing trade dataclass and add that.

Test: `tests/engines/test_backtest_regime.py`:

```python
def test_backtest_emits_regime_breakdown():
    result = run_backtest(strategy="rand_canary", universe="smoke_5", ...)
    assert hasattr(result, 'regime_breakdown')
    assert len(result.regime_breakdown) > 0
    for b in result.regime_breakdown:
        assert b.label
        assert b.n_trades > 0
```

- [ ] **Step 3.5: Cache current regime + endpoint**

Add `tradelab/src/tradelab/web/handlers.py` route `GET /tradelab/regime`:

```python
def handle_regime() -> dict:
    cache_path = Path(get_config().paths.cache_dir) / "current_regime.json"
    cfg = get_config().regime_classifier

    if cache_path.exists():
        age = time.time() - cache_path.stat().st_mtime
        if age < cfg.cache_ttl_seconds:
            return json.loads(cache_path.read_text(encoding="utf-8-sig"))

    # Compute fresh
    bars = fetch_benchmark_bars()  # SPY + VIX + breadth
    label = classify(bars, **_classifier_kwargs(cfg))
    response = {
        "label": label.model_dump(),
        "combined": label.combined,
        "vix": float(bars["vix"].iloc[-1]) if "vix" in bars.columns else None,
        "adx": float(bars["adx"].iloc[-1]) if "adx" in bars.columns else None,
        "breadth": float(bars["breadth_pct_above_50d"].iloc[-1]) if "breadth_pct_above_50d" in bars.columns else None,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(response), encoding="utf-8")
    return response
```

(Per memory `reference_powershell_utf8_bom`: read with utf-8-sig in case of BOM-tainted writes.)

Test in `test_handlers_validation.py`:

```python
def test_regime_endpoint_returns_label(client_with_benchmark_data):
    r = client_with_benchmark_data.get("/tradelab/regime")
    body = r.json()
    assert "combined" in body
    assert body["combined"].count("_") == 2
```

- [ ] **Step 3.6: Frontend — Regime banner**

In `command_center.html` Research tab, ABOVE the Calibration banner, insert:

```html
<section class="panel regime-banner" id="regimeBanner"></section>
```

Render:

```javascript
async function loadRegimeBanner() {
  const r = await fetch('/tradelab/regime');
  if (!r.ok) return;
  const reg = await r.json();
  document.getElementById('regimeBanner').innerHTML = `
    <div class="panel-header"><h2>Market Regime</h2></div>
    <div class="regime-grid">
      <div class="regime-cell"><div class="label">Volatility</div>
        <div class="value">${reg.label.volatility}</div>
        <div class="meta">VIX ${reg.vix?.toFixed(1) ?? '—'}</div></div>
      <div class="regime-cell"><div class="label">Trend</div>
        <div class="value">${reg.label.trend}</div>
        <div class="meta">ADX ${reg.adx?.toFixed(0) ?? '—'}</div></div>
      <div class="regime-cell"><div class="label">Breadth</div>
        <div class="value">${reg.label.breadth}</div>
        <div class="meta">${reg.breadth?.toFixed(0) ?? '—'}% above 50d</div></div>
      <div class="regime-cell"><div class="label">Strategies favored now</div>
        <div class="value" id="regimeFavoredCount">…</div></div>
    </div>`;
}
```

The favored-count needs Live cards' regime fit; populate after Step 3.7.

- [ ] **Step 3.7: Frontend — regime-fit on Live cards**

Each Live card's metadata gets a `regime_fit` field computed from `regime_breakdown` + current regime: STRONG (current is best bucket), WEAK (current is mid bucket), POOR (current is worst bucket).

Backend: extend `audit_reader.py` get-strategies handler to inline this. For each card, fetch its latest run's `regime_breakdown` + the current regime, and compute the fit class.

Frontend: render fit tag next to verdict pill.

- [ ] **Step 3.8: Frontend — regime-fit column on Pipeline + per-regime table in Score modal**

Pipeline: add `<th>Regime fit</th>`. Cell renders STRONG/WEAK/POOR pill based on per-run regime_breakdown.

Score modal: insert per-regime table after Diagnostics, before Portfolio Fit:

```html
<div class="regime-perf">
  <h3>Regime performance</h3>
  <table id="regimeTable"></table>
</div>
```

Render bars per regime with current-regime tag and PF + trade count. Use mockup CSS.

- [ ] **Step 3.9: Hand-smoke Phase 3**

Verify regime banner shows current regime. Open Score modal → per-regime table populated. Pipeline regime-fit column tags STRONG/WEAK/POOR. Live cards show regime-fit subtitle. Banner's "Strategies favored now" count matches.

- [ ] **Step 3.10: Commit Phase 3**

```bash
git add -A; git status
git commit -m "feat(regime): regime conditioning across Research tab — banner, per-strategy fit, per-regime PF"
```

---

## Phase 4 — Live Divergence (K-S + Decay)

**Goal:** Replace planned rolling-PF tracking-error with two statistically-grounded signals: K-S test of live vs backtest distribution, and rolling-Sharpe decay slope. Auto-disable on K-S fail.

**Files:**
- Create: `tradelab/src/tradelab/live/divergence.py`
- Create: `tradelab/tests/live/test_divergence.py`
- Modify: `tradelab/src/tradelab/live/receiver.py` (hook on order_submitted)
- Modify: `tradelab/src/tradelab/web/handlers.py` (+ `/tradelab/cards/<id>/divergence`)
- Modify: `tradelab/tradelab.yaml` (+ k_s + decay thresholds)
- Modify: `C:\TradingScripts\command_center.html` (Live card sparkline + K-S badge)

### Tasks

- [ ] **Step 4.1: Add divergence thresholds**

Yaml:

```yaml
robustness:
  thresholds:
    # ... existing ...
    ks_p_warn: 0.10
    ks_p_fail: 0.01
    decay_slope_threshold: -0.005
    decay_t_stat_threshold: -2.0
    divergence_min_trades: 30
```

Mirror in `config.py`.

- [ ] **Step 4.2: Write failing test for divergence**

Create `tradelab/tests/live/test_divergence.py`:

```python
import numpy as np
import pandas as pd
import pytest

from tradelab.live.divergence import (
    ks_divergence,
    decay_slope,
    DivergenceResult,
    evaluate_divergence,
)


def test_ks_no_divergence_same_distribution():
    np.random.seed(42)
    backtest = np.random.normal(0.001, 0.02, 1000)
    live = np.random.normal(0.001, 0.02, 50)
    result = ks_divergence(live=live, backtest=backtest)
    assert result.p_value > 0.10
    assert result.statistic < 0.3


def test_ks_clear_divergence_different_means():
    np.random.seed(42)
    backtest = np.random.normal(0.01, 0.02, 1000)
    live = np.random.normal(-0.01, 0.02, 50)
    result = ks_divergence(live=live, backtest=backtest)
    assert result.p_value < 0.01


def test_decay_slope_flat():
    sharpes = np.array([0.5, 0.51, 0.49, 0.50, 0.51, 0.50])
    result = decay_slope(sharpes)
    assert abs(result.slope) < 0.005


def test_decay_slope_declining():
    sharpes = np.linspace(0.6, 0.0, 30)  # clear decline
    result = decay_slope(sharpes)
    assert result.slope < -0.01
    assert result.t_statistic < -2.0


def test_evaluate_divergence_pass():
    np.random.seed(42)
    backtest = pd.Series(np.random.normal(0.001, 0.02, 1000))
    live_returns = pd.Series(np.random.normal(0.001, 0.02, 35))
    result = evaluate_divergence(
        live_returns=live_returns,
        backtest_returns=backtest,
        ks_p_warn=0.10, ks_p_fail=0.01,
        decay_slope_threshold=-0.005,
        decay_t_stat_threshold=-2.0,
        min_trades=30,
        window=30,
    )
    assert result.status == "ok"


def test_evaluate_divergence_fail_on_ks():
    np.random.seed(42)
    backtest = pd.Series(np.random.normal(0.01, 0.02, 1000))
    live_returns = pd.Series(np.random.normal(-0.01, 0.02, 35))
    result = evaluate_divergence(
        live_returns=live_returns,
        backtest_returns=backtest,
        ks_p_warn=0.10, ks_p_fail=0.01,
        decay_slope_threshold=-0.005,
        decay_t_stat_threshold=-2.0,
        min_trades=30,
        window=30,
    )
    assert result.status == "fail"
    assert result.ks.p_value < 0.01


def test_evaluate_divergence_warming_up_under_min_trades():
    backtest = pd.Series(np.random.normal(0.001, 0.02, 1000))
    live_returns = pd.Series(np.random.normal(0.001, 0.02, 5))
    result = evaluate_divergence(
        live_returns=live_returns,
        backtest_returns=backtest,
        ks_p_warn=0.10, ks_p_fail=0.01,
        decay_slope_threshold=-0.005,
        decay_t_stat_threshold=-2.0,
        min_trades=30,
        window=30,
    )
    assert result.status == "warming_up"
```

- [ ] **Step 4.3: Implement `divergence.py`**

Create `tradelab/src/tradelab/live/divergence.py`:

```python
"""Live trade vs backtest divergence detection.

Two independent statistics over a rolling window:
- K-S test: is the live return distribution drawn from the backtest distribution?
- Decay slope: linear regression of rolling Sharpe vs window index

Both grounded in scipy.stats. Auto-disable on K-S fail (severity=critical).
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
from pydantic import BaseModel
from scipy import stats


class KSResult(BaseModel):
    statistic: float
    p_value: float


class DecayResult(BaseModel):
    slope: float
    std_error: float
    t_statistic: float


class DivergenceResult(BaseModel):
    status: str    # "ok" | "warn" | "fail" | "warming_up"
    ks: Optional[KSResult] = None
    decay: Optional[DecayResult] = None
    n_trades: int
    reason: str


def ks_divergence(*, live: np.ndarray, backtest: np.ndarray) -> KSResult:
    stat, p = stats.ks_2samp(live, backtest)
    return KSResult(statistic=float(stat), p_value=float(p))


def decay_slope(sharpes: np.ndarray) -> DecayResult:
    """Linear regression of rolling-Sharpe series vs index."""
    if len(sharpes) < 3:
        return DecayResult(slope=0.0, std_error=0.0, t_statistic=0.0)
    x = np.arange(len(sharpes))
    res = stats.linregress(x, sharpes)
    se = res.stderr if res.stderr else 1e-9
    return DecayResult(
        slope=float(res.slope),
        std_error=float(se),
        t_statistic=float(res.slope / se),
    )


def _rolling_sharpe(returns: pd.Series, window: int) -> np.ndarray:
    """Per-window Sharpe = mean / std on a rolling window of `window` trades."""
    if len(returns) < window:
        return np.array([])
    out = []
    for i in range(window, len(returns) + 1):
        sub = returns.iloc[i - window: i]
        std = sub.std()
        if std == 0:
            out.append(0.0)
        else:
            out.append(sub.mean() / std)
    return np.array(out)


def evaluate_divergence(
    *,
    live_returns: pd.Series,
    backtest_returns: pd.Series,
    ks_p_warn: float,
    ks_p_fail: float,
    decay_slope_threshold: float,
    decay_t_stat_threshold: float,
    min_trades: int,
    window: int,
) -> DivergenceResult:
    n = len(live_returns)
    if n < min_trades:
        return DivergenceResult(
            status="warming_up",
            n_trades=n,
            reason=f"need {min_trades} trades, have {n}",
        )

    ks = ks_divergence(live=live_returns.values, backtest=backtest_returns.values)
    sharpes = _rolling_sharpe(live_returns, window=min(window, n))
    decay = decay_slope(sharpes) if len(sharpes) >= 3 else None

    if ks.p_value < ks_p_fail:
        status = "fail"
        reason = f"K-S p={ks.p_value:.4f} < {ks_p_fail}"
    elif ks.p_value < ks_p_warn:
        status = "warn"
        reason = f"K-S p={ks.p_value:.4f} < {ks_p_warn}"
    elif decay and decay.slope < decay_slope_threshold and decay.t_statistic < decay_t_stat_threshold:
        status = "warn"
        reason = f"decay slope {decay.slope:.4f} (t={decay.t_statistic:.2f})"
    else:
        status = "ok"
        reason = "no divergence detected"

    return DivergenceResult(
        status=status,
        ks=ks,
        decay=decay,
        n_trades=n,
        reason=reason,
    )
```

Run: `python -m pytest tests/live/test_divergence.py -v` — expect 7 passed.

- [ ] **Step 4.4: Receiver hook to log fills + compute divergence**

Read `tradelab/src/tradelab/live/receiver.py`. Find `_log_alert` or `on_order_submitted`. Add:

```python
def _on_fill(self, event: dict):
    card_id = event["card_id"]
    fill = {
        "ts": event["ts"],
        "symbol": event["symbol"],
        "qty": event["qty"],
        "price": event["price"],
        "return_pct": event.get("return_pct"),  # if available
    }
    fills_path = self._archive_dir(card_id) / "fills.jsonl"
    with open(fills_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(fill) + "\n")

    # Compute divergence after every fill (cheap)
    self._update_divergence(card_id)


def _update_divergence(self, card_id: str):
    fills = self._load_fills(card_id)
    if len(fills) < self.cfg.robustness.thresholds.divergence_min_trades:
        return
    baseline = load_card_baseline(self.archive_root, card_id)
    bt_returns = baseline["backtest_trades"]["return_pct"]
    live_returns = pd.Series([f["return_pct"] for f in fills if f.get("return_pct") is not None])

    result = evaluate_divergence(
        live_returns=live_returns,
        backtest_returns=bt_returns,
        ks_p_warn=self.cfg.robustness.thresholds.ks_p_warn,
        ks_p_fail=self.cfg.robustness.thresholds.ks_p_fail,
        decay_slope_threshold=self.cfg.robustness.thresholds.decay_slope_threshold,
        decay_t_stat_threshold=self.cfg.robustness.thresholds.decay_t_stat_threshold,
        min_trades=self.cfg.robustness.thresholds.divergence_min_trades,
        window=30,
    )

    log_path = self._archive_dir(card_id) / "divergence_log.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        entry = {"ts": datetime.now(timezone.utc).isoformat(), **result.model_dump()}
        f.write(json.dumps(entry) + "\n")

    if result.status == "fail":
        self._auto_disable(card_id, reason=result.reason)


def _auto_disable(self, card_id: str, reason: str):
    self._cards_writer.set_status(card_id, "disabled")
    notify(
        Severity.CRITICAL,
        title=f"Card auto-disabled: {card_id}",
        body=f"K-S divergence detected — {reason}. Manual review required.",
    )
```

Test in `tests/live/test_receiver_notify_integration.py`:

```python
def test_ks_fail_triggers_auto_disable_and_critical_notify(synthetic_diverging_fills):
    # Submit fills that produce K-S p<0.01
    receiver.process_event(synthetic_diverging_fills[0])
    # ... loop through fills ...
    assert receiver.get_card_status("test-card-v1") == "disabled"
    assert "auto-disabled" in last_notify_event()["title"].lower()
    assert last_notify_event()["severity"] == "critical"
```

- [ ] **Step 4.5: Endpoint `/tradelab/cards/<id>/divergence`**

Add handler. Returns latest divergence + last 30-window of stats for sparkline rendering:

```python
def handle_card_divergence(card_id: str) -> dict:
    log_path = pine_archive_root() / card_id / "divergence_log.jsonl"
    if not log_path.exists():
        return {"status": "no_data", "card_id": card_id}
    entries = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    return {
        "card_id": card_id,
        "latest": entries[-1] if entries else None,
        "history": entries[-100:],  # for sparkline
    }
```

- [ ] **Step 4.6: Frontend — Live card decay sparkline + K-S badge**

In `command_center.html`, locate Live card render. Append rows for DECAY and K-S:

```javascript
async function renderCardDivergence(cardEl, cardId) {
  const r = await fetch(`/tradelab/cards/${cardId}/divergence`);
  if (!r.ok) return;
  const data = await r.json();
  if (data.status === 'no_data' || !data.latest) return;

  const d = data.latest;
  const decayPath = sparklinePath(data.history.map(h => h.decay?.slope ?? 0));
  const ksClass = d.status === 'ok' ? 'ok' : d.status === 'warn' ? 'warn' : 'fail';

  cardEl.querySelector('.divergence-rows').innerHTML = `
    <div class="health-row">
      <span class="lbl">DECAY</span>
      <svg class="sparkline" viewBox="0 0 100 18"><path d="${decayPath}" class="${
        d.decay?.slope > 0 ? 'stable' : d.decay?.slope < -0.005 ? 'declining' : 'stable'
      }"/></svg>
      <span>${d.decay ? d.decay.slope.toFixed(4) : '—'}</span>
    </div>
    <div class="health-row">
      <span class="lbl">K-S</span>
      <span class="ks-tag ${ksClass}">p=${d.ks?.p_value?.toFixed(3) ?? '—'}</span>
    </div>`;
}
```

- [ ] **Step 4.7: Hand-smoke Phase 4**

Inject synthetic divergence into a test card. Restart receiver. Verify auto-disable triggers, notify event appears with severity=critical, and Live card shows red K-S badge + dying sparkline.

- [ ] **Step 4.8: Commit Phase 4**

```bash
git add -A; git status
git commit -m "feat(live): K-S divergence + decay slope per card with auto-disable on K-S fail"
```

---

## Phase 5 — Calibration Banner

**Goal:** Aggregate stats across last N accepted cards: TE-tripped %, auto-disabled %, PF gap median. Recommend threshold tightenings.

**Files:**
- Create: `tradelab/src/tradelab/live/calibration.py`
- Create: `tradelab/tests/live/test_calibration.py`
- Modify: `tradelab/src/tradelab/web/handlers.py` (+ `/tradelab/calibration`)
- Modify: `C:\TradingScripts\command_center.html` (banner)

### Tasks

- [ ] **Step 5.1: Write failing test**

Create `tradelab/tests/live/test_calibration.py`:

```python
import json
from datetime import datetime, timedelta, timezone
import pandas as pd
import pytest

from tradelab.live.calibration import compute_calibration_stats, CalibrationStats


def test_empty_state_under_min_cards(tmp_path):
    stats = compute_calibration_stats(archive_root=tmp_path, min_cards=5, min_days=30)
    assert stats.available is False
    assert stats.n_cards == 0


def test_calibration_stats_computed(tmp_path):
    # Create 5 fake card archives with mock divergence_log.jsonl
    for i in range(5):
        card_dir = tmp_path / f"card-{i}"
        card_dir.mkdir()
        accepted_at = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
        meta = {"accepted_at": accepted_at, "verdict_pf": 1.6}
        (card_dir / "accept_meta.json").write_text(json.dumps(meta))
        # Some cards trip TE within 30d
        events = []
        if i < 2:
            events.append({"ts": (datetime.now(timezone.utc) - timedelta(days=15)).isoformat(),
                           "status": "fail"})
        (card_dir / "divergence_log.jsonl").write_text(
            "\n".join(json.dumps(e) for e in events) + ("\n" if events else "")
        )
    stats = compute_calibration_stats(archive_root=tmp_path, min_cards=5, min_days=30)
    assert stats.available is True
    assert stats.n_cards == 5
    assert stats.te_tripped_within_30d == 2
    assert stats.te_tripped_pct == pytest.approx(0.4, abs=0.01)
```

- [ ] **Step 5.2: Implement `calibration.py`**

```python
"""Aggregate stats across accepted cards: TE-trip rate, auto-disable rate, PF gap.

Reads each card's pine_archive/<id>/accept_meta.json + divergence_log.jsonl.
Returns recommendations when thresholds tripped.
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel


class CalibrationStats(BaseModel):
    available: bool
    n_cards: int
    te_tripped_within_30d: int = 0
    te_tripped_pct: float = 0.0
    auto_disabled_within_60d: int = 0
    auto_disabled_pct: float = 0.0
    pf_gap_median: float = 0.0
    recommendations: list[str] = []


def compute_calibration_stats(
    *,
    archive_root: Path,
    min_cards: int = 5,
    min_days: int = 30,
) -> CalibrationStats:
    """Walk pine_archive/, summarize accepted-card outcomes."""
    accepted = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=min_days)

    for card_dir in Path(archive_root).iterdir():
        meta_path = card_dir / "accept_meta.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text())
        accepted_at = datetime.fromisoformat(meta["accepted_at"].replace("Z", "+00:00"))
        if accepted_at > cutoff:
            continue   # too new, skip
        accepted.append((card_dir, meta, accepted_at))

    if len(accepted) < min_cards:
        return CalibrationStats(available=False, n_cards=len(accepted))

    te_tripped_30d = 0
    auto_disabled_60d = 0
    pf_gaps = []

    for card_dir, meta, accepted_at in accepted:
        log_path = card_dir / "divergence_log.jsonl"
        events = []
        if log_path.exists():
            for line in log_path.read_text().splitlines():
                if line.strip():
                    events.append(json.loads(line))
        # TE tripped within 30d
        for e in events:
            ts = datetime.fromisoformat(e["ts"].replace("Z", "+00:00"))
            if (ts - accepted_at).days <= 30 and e.get("status") in {"warn", "fail"}:
                te_tripped_30d += 1
                break
        # auto_disabled within 60d
        for e in events:
            ts = datetime.fromisoformat(e["ts"].replace("Z", "+00:00"))
            if (ts - accepted_at).days <= 60 and e.get("status") == "fail":
                auto_disabled_60d += 1
                break
        # PF gap
        bt_pf = meta.get("verdict_pf")
        live_pf = meta.get("live_pf_30d")
        if bt_pf and live_pf:
            pf_gaps.append(live_pf - bt_pf)

    n = len(accepted)
    te_pct = te_tripped_30d / n
    ad_pct = auto_disabled_60d / n
    pf_median = statistics.median(pf_gaps) if pf_gaps else 0.0

    recs = []
    if te_pct > 0.25:
        recs.append("Tighten hold_out_robust_pf — TE trips on >25% of cards within 30d")
    if pf_median < -0.30:
        recs.append("Tighten dsr_robust — live PF deficit median < -0.30")

    return CalibrationStats(
        available=True,
        n_cards=n,
        te_tripped_within_30d=te_tripped_30d,
        te_tripped_pct=te_pct,
        auto_disabled_within_60d=auto_disabled_60d,
        auto_disabled_pct=ad_pct,
        pf_gap_median=pf_median,
        recommendations=recs,
    )
```

Run: `python -m pytest tests/live/test_calibration.py -v` — expect 2 passed.

- [ ] **Step 5.3: Endpoint + frontend banner**

Handler:

```python
def handle_calibration() -> dict:
    return compute_calibration_stats(
        archive_root=Path(get_config().paths.pine_archive_dir),
        min_cards=5,
        min_days=30,
    ).model_dump()
```

Frontend:

```html
<section class="panel calibration" id="calibrationBanner"></section>
```

```javascript
async function loadCalibrationBanner() {
  const r = await fetch('/tradelab/calibration');
  const stats = await r.json();
  const el = document.getElementById('calibrationBanner');
  if (!stats.available) {
    el.style.display = 'none';
    return;
  }
  el.innerHTML = `
    <div class="panel-header"><h2>Verdict Calibration</h2></div>
    <div class="stat-row">
      <div class="stat"><div class="num">${stats.te_tripped_within_30d} / ${stats.n_cards}</div>
        <div class="label">TE tripped within 30d</div></div>
      <div class="stat"><div class="num">${stats.auto_disabled_within_60d} / ${stats.n_cards}</div>
        <div class="label">Auto-disabled within 60d</div></div>
      <div class="stat"><div class="num">${stats.pf_gap_median.toFixed(2)}</div>
        <div class="label">Median PF gap (live − bt)</div></div>
      ${stats.recommendations.length ?
        '<div class="recommend">' + stats.recommendations.join(' · ') + '</div>' : ''}
    </div>`;
}
```

- [ ] **Step 5.4: Hand-smoke Phase 5**

If you have ≥5 accepted cards with ≥30d data, banner renders with stats. Otherwise hidden. Verify recommendations text appears when synthetic data trips a threshold.

- [ ] **Step 5.5: Commit Phase 5**

```bash
git add -A; git status
git commit -m "feat(calibration): meta-stat banner closing the verdict feedback loop"
```

---

## Verdict Freshness (cross-cutting, ~0.25d)

- [ ] **Step VF.1:** Extend `audit_reader.py` to compute `last_verdict_at` per card (max of card's robustness/full run timestamps). Add `regime_at_verdict` from cached regime at that time.
- [ ] **Step VF.2:** Frontend Live card header: render "verdict Nd old" with color (green <30d, amber 30-60d, red >60d).
- [ ] **Step VF.3:** Tooltip on red staleness: "regime has shifted since last verdict — re-run robustness."
- [ ] **Step VF.4:** Smoke + commit.

---

## Self-review checklist (run after each phase)

- [ ] All new tests pass
- [ ] No existing tests broken
- [ ] Hand-smoke through dashboard succeeds
- [ ] No new files created outside the listed paths
- [ ] No new dependencies added (numpy/scipy/pandas/pydantic only)
- [ ] Old `GAMEPLAN_validation_gaps.md` SUPERSEDED note still accurate
- [ ] Commit message references phase number

## Definition of Done (whole plan)

- All 6 phases shipped
- 816+ baseline tests still pass + ~30 new tests added
- Dashboard hand-smoke shows: regime banner, calibration banner, hold-out gate column on Pipeline + section in Score modal, 3-column Portfolio Fit panel, decay sparkline + K-S badge on every Live card
- Memory updated with completion entry
- `GAMEPLAN_validation_gaps.md` already marked SUPERSEDED

---

## Notes for the implementer

- **Dashboard html lives outside tradelab/** — it's at `C:\TradingScripts\command_center.html` (not in the tradelab repo). Commits to `command_center.html` go to whatever repo `C:\TradingScripts\` is in.
- **PowerShell BOM gotcha** (per memory): when reading any JSON file written by PowerShell, use `encoding="utf-8-sig"`, not `"utf-8"`.
- **Notify api**: `notify(Severity.CRITICAL, title="...", body="...")`. Severity values: `Severity.CRITICAL/WARNING/INFO`.
- **Receiver hot-reload** (per memory): cards.json edits hot-reload via watchdog; auto-disable should write through `cards.write_status(card_id, "disabled")` and NOT require restart.
- **`tests/live/conftest.py` autouse fixture** (per memory): keeps notify-path redirected. Extend it to also redirect `pine_archive` for divergence/calibration tests, otherwise tests will pollute production archives.
- **The 9 robustness signals already include regime work partially** — `regime_spread_*` thresholds exist in `tradelab.yaml`. Confirm during Phase 3 implementation whether existing per-regime PF computation overlaps with what this plan adds; reuse rather than duplicate.
