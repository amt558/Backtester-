# Python Strategy Test + QuantStats — Implementation Plan (Phase 2 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Let a freshly-imported Python strategy be Tested from the Command Center (one click → a `run --full` job that produces backtest + robustness verdict + validation + QuantStats), and add a regression guard so the QuantStats tearsheet keeps working.

**Architecture:** No new engine or job plumbing. The `/tradelab/jobs` POST already launches `tradelab.cli run <strategy> --full` (allowlisted) with an auto-injected `--universe`, and `run --full` already writes `quantstats_tearsheet.html` + `robustness_result.json` + `validation.json`. Phase 2 adds (1) a pytest regression for `render_backtest_tearsheet`, and (2) a post-import "Test" button in the Import modal that fires that existing job.

**Tech Stack:** pytest, `tradelab.reporting.tearsheet`, vanilla JS in `command_center.html`, the existing `/tradelab/jobs` trigger.

**Verified context (do not re-investigate):** `render_backtest_tearsheet(result, output_path=None, benchmark_returns=None, title=None)` renders fine today (probed: 610 KB HTML on a real run); it needs `result.daily_returns()` non-empty (a populated `equity_curve`) and raises `ValueError` otherwise. `_ALLOWED_COMMANDS` already contains `"run --full"`. The FE `triggerRunByStrategy(strategy, flag)` (command_center.html ~5497-5515) POSTs to `/tradelab/jobs` — mirror its exact body shape.

**Phase 2 of 3.** Phase 3 = Qualify/Accept toggle + Overview card + Alpaca enrollment.

---

### Task 1: QuantStats regression guard

**Files:**
- Test: `tradelab/tests/reporting/test_tearsheet_regression.py` (create; create `tests/reporting/__init__.py` if missing)

- [ ] **Step 1: Write the test**

```python
# tradelab/tests/reporting/test_tearsheet_regression.py
"""Guard: the QuantStats tearsheet must render for a normal Python backtest,
and must raise a clear error (not crash) when there is no equity curve."""
from __future__ import annotations

import math

import pytest

from tradelab.results import BacktestResult, Trade
from tradelab.reporting.tearsheet import render_backtest_tearsheet


def _synthetic_bt(n: int = 260) -> BacktestResult:
    # smooth-ish rising equity curve, business-day dated
    import datetime as dt
    start = dt.date(2023, 1, 2)
    curve = []
    eq = 100_000.0
    d = start
    for i in range(n):
        eq *= (1.0 + 0.0006 * math.sin(i / 9.0) + 0.0004)
        curve.append({"date": d.isoformat(), "equity": round(eq, 2)})
        d += dt.timedelta(days=1)
    return BacktestResult(
        strategy="qs_probe", start_date=curve[0]["date"], end_date=curve[-1]["date"],
        trades=[Trade(ticker="AAA", entry_date=curve[0]["date"], exit_date=curve[10]["date"],
                      entry_price=100, exit_price=110, shares=1, pnl=10, pnl_pct=10,
                      bars_held=10, exit_reason="test")],
        equity_curve=curve,
    )


def test_tearsheet_renders_nonempty_html(tmp_path):
    out = tmp_path / "ts.html"
    p = render_backtest_tearsheet(_synthetic_bt(), output_path=out, title="probe")
    assert p == out and out.exists()
    text = out.read_text(encoding="utf-8", errors="ignore")
    assert len(text) > 50_000           # a real QuantStats report is large
    assert "<html" in text.lower()


def test_tearsheet_empty_curve_raises_valueerror(tmp_path):
    bt = BacktestResult(strategy="empty", start_date="2024-01-01", end_date="2024-02-01")
    with pytest.raises(ValueError):
        render_backtest_tearsheet(bt, output_path=tmp_path / "x.html")
```

- [ ] **Step 2: Run to verify it passes** (the feature already works — this is a guard, so it should PASS immediately; if it FAILS, QuantStats is actually broken — report that):

Run: `cd tradelab && python -m pytest tests/reporting/test_tearsheet_regression.py -q`
Expected: `2 passed`. (First run may be slow — QuantStats imports matplotlib.)

- [ ] **Step 3: Commit**

```bash
cd tradelab && git add tests/reporting/test_tearsheet_regression.py tests/reporting/__init__.py
git commit -m "test(quantstats): regression guard for tearsheet render + empty-curve error"
```

---

### Task 2: Post-import "Test" button in the Import modal

**Files:**
- Modify: `command_center.html` (root repo) — the Import modal (added in Phase 1 at ~line 1575) + the import JS (`onImportStrategy` ~5085, wiring ~5106).
- Test: `tradelab/tests/web/test_command_center_html.py` (add assertion)

- [ ] **Step 1: Write the failing test**

```python
def test_import_modal_has_test_button_firing_full_run(html: str) -> None:
    assert 'id="importTestBtn"' in html
    # the Test button fires a full run via the existing jobs endpoint
    assert "run --full" in html
    assert "/tradelab/jobs" in html
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd tradelab && python -m pytest tests/web/test_command_center_html.py -q -k test_button`
Expected: FAIL (`importTestBtn` absent).

- [ ] **Step 3: Implement**

In the Import modal HTML, add a hidden Test button after `importStrategyStatus`:
```html
        <button id="importTestBtn" class="btn" type="button" hidden
                title="Run a full test (backtest + robustness + validation + QuantStats)">Test (full run)</button>
```

In the JS: keep the last-imported name and reveal the Test button on success. In `onImportStrategy`, after the success line `status.innerHTML = ...Imported...`, add:
```javascript
        _lastImportedStrategy = o.value;
        const tb = document.getElementById('importTestBtn');
        if (tb) tb.hidden = false;
```
Add a module-scope `let _lastImportedStrategy = null;` near the other import handlers, and a handler that mirrors the EXISTING `triggerRunByStrategy` POST body shape (read it at ~command_center.html:5497-5515 and copy the exact `fetch('/tradelab/jobs', {...})` body — it sends the strategy + the `run --full` command):
```javascript
    async function onImportTest() {
      if (!_lastImportedStrategy) return;
      const status = document.getElementById('importStrategyStatus');
      status.textContent = `Starting full test for ${_lastImportedStrategy}…`;
      try {
        // mirror triggerRunByStrategy's POST body shape exactly
        const r = await fetch('/tradelab/jobs', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({strategy: _lastImportedStrategy, command: 'run --full'}),
        });
        const env = await r.json();
        if (!r.ok || env.error) throw new Error(env.error || ('HTTP ' + r.status));
        status.innerHTML = `<span style="color:var(--green)">Test queued — watch the Job Tracker. `
          + `Results (incl. QuantStats) will appear on the run when it finishes.</span>`;
      } catch (e) {
        status.innerHTML = `<span style="color:var(--red)">${_esc(e.message || e)}</span>`;
      }
    }
```
Wire it next to the other import wiring (~5108):
```javascript
    document.getElementById('importTestBtn').addEventListener('click', onImportTest);
```
Also hide `importTestBtn` again whenever `loadDiscoverableStrategies()` runs (a fresh scan), to avoid a stale Test target: add at the top of `loadDiscoverableStrategies`:
```javascript
      const tb = document.getElementById('importTestBtn'); if (tb) tb.hidden = true;
```

**IMPORTANT:** before writing `onImportTest`, READ the real `triggerRunByStrategy` (command_center.html ~5497-5515) and confirm the POST body shape. If it differs (e.g. it sends `{command}` only, or a different field name), match it exactly — the backend `handle_post_with_status` for `/tradelab/jobs` must accept your body. If unsure, report NEEDS_CONTEXT rather than guessing.

- [ ] **Step 4: Run tests**

Run: `cd tradelab && python -m pytest tests/web/test_command_center_html.py -q -k test_button` → PASS.
Then `python -m pytest tests/web/test_command_center_html.py -q` → failure count must be the pre-existing baseline (71 failed) with NO new failures (passed count rises by 1).

- [ ] **Step 5: Commit (both repos)**

```bash
cd C:/TradingScripts && git add command_center.html && git commit -m "feat(test): post-import Test button fires run --full job"
cd C:/TradingScripts/tradelab && git add tests/web/test_command_center_html.py && git commit -m "test(test): assert post-import Test button present"
```

---

## Self-review
- **Spec coverage:** Component 2 (Test) → Task 2 (one-click full run on the imported strategy, reusing the existing job trigger). Component 5 (QuantStats works) → Task 1 (regression guard; verified already-working). ✓
- **Placeholder scan:** one explicit READ step (confirm `triggerRunByStrategy` body shape) — a verification, not a placeholder. All code blocks complete.
- **Type/shape consistency:** the Test button POST body `{strategy, command:'run --full'}` must match the existing `/tradelab/jobs` POST contract — the implement step requires confirming it against `triggerRunByStrategy`.

## Note for Phase 3
Phase 3 reads each tested strategy's verdict + validation outcomes to drive the advisory qualification badge + Accept toggle + Overview card + Alpaca enrollment — and MUST first read `alpaca_trading_bot.py` + `tradelab/live/` + the `/tradelab/cards` renderer to ground the live-roster contract.
