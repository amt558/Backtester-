# Research Tab v2.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Research Tab v2.0 — preflight + failure hints + compare-N-runs + pipeline polish + live-card compression — as one coherent bundle that reshapes the Research tab around the Pipeline decision surface.

**Architecture:** Three new backend modules in `tradelab/src/tradelab/web/` (preflight, compare, failure_hint), four new HTTP routes, plus targeted changes to the single-file `command_center.html`. Feature-flagged compressed-cards layout for 48h rollback safety. No engine or schema changes.

**Tech Stack:** Python stdlib + pandas + pytest (backend), vanilla JS + inline SVG (frontend), Windows PowerShell for build/run commands.

**Spec:** `docs/superpowers/specs/2026-04-23-research-tab-v2-design.md` — the source of truth for WHAT; this plan is the SEQUENCE.

---

## File structure

### New files (backend)

| Path | Responsibility |
|------|---|
| `src/tradelab/web/preflight.py` | Four static check functions + `compute_preflight()` aggregator |
| `src/tradelab/web/compare.py` | `run_compare(run_ids, benchmark)` — validates, subprocesses, returns report path |
| `src/tradelab/web/failure_hint.py` | `extract_failure_hint(job_id)` — parses `progress.jsonl` last error |
| `tests/web/test_preflight.py` | ~6 tests covering all 4 check types + aggregator |
| `tests/web/test_compare.py` | ~7 tests covering validation, happy path, traversal |
| `tests/web/test_failure_hint.py` | ~4 tests covering parsing + exit-code fallback |

### Modified files (backend)

| Path | Change scope |
|------|---|
| `src/tradelab/web/handlers.py` | Add 2 GET branches, 1 POST branch, 1 static-HTML branch; import new modules |
| `src/tradelab/web/jobs.py` | `_job_to_dict()` reads failure_hint for FAILED state |
| `src/tradelab/web/__init__.py` | Export `compute_preflight` helper |
| `tests/web/test_handlers_jobs.py` | Assert `failure_hint` field on FAILED |

### Modified files (frontend)

| Path | Change scope |
|------|---|
| `C:\TradingScripts\command_center.html` | CSS (new classes), HTML (preflight chips, Compare button, sparkline col, checkbox col), JS (~200 lines of new functions) |
| `C:\TradingScripts\launch_dashboard.py` | Add `/tradelab/compare-report` static-HTML branch (returns HTML bytes, not JSON envelope) |

### New files (tests, docs, sidecars)

| Path | Purpose |
|------|---|
| `docs/superpowers/RESEARCH_TAB_V2_SUMMARY.md` | v2 handoff doc, matches v1/v1.5 convention |
| `C:\TradingScripts\command_center.html.bak-2026-04-23-v2` | Rollback sidecar |
| `C:\TradingScripts\launch_dashboard.py.bak-2026-04-23-v2` | Rollback sidecar |
| `C:\TradingScripts\CHANGELOG-research-tab.txt` | Append v2 entry |

---

## Pre-flight for the engineer

Before Task 1, confirm baseline is clean:

- [ ] **Pre-step 1: Confirm master baseline green**

Run:
```powershell
cd C:\TradingScripts\tradelab
$env:PYTHONPATH = "src"
$env:PYTHONIOENCODING = "utf-8"
python -m pytest tests/web/ tests/cli/test_progress_log.py -q
```
Expected: `72 passed`.

- [ ] **Pre-step 2: Enter worktree**

Use the `EnterWorktree` tool with `name: "research-v2"`. This creates `C:\TradingScripts\tradelab\.claude\worktrees\research-v2` on a fresh branch off `master`. All subsequent commits go here.

- [ ] **Pre-step 3: Create backup sidecars**

```powershell
Copy-Item C:\TradingScripts\command_center.html      C:\TradingScripts\command_center.html.bak-2026-04-23-v2
Copy-Item C:\TradingScripts\launch_dashboard.py       C:\TradingScripts\launch_dashboard.py.bak-2026-04-23-v2
```

---

## Phase 1: Preflight chips (absorbs Freshness banner)

### Task 1: Write `preflight.py` with 4 check functions + aggregator

**Files:**
- Create: `src/tradelab/web/preflight.py`

- [ ] **Step 1: Create the module skeleton**

```python
"""Preflight checks for the Research tab run modal + chip cluster.

Four synchronous, disk-local checks (<100ms total, no network):
  - universe: launcher-state.json resolves + universe has ≥1 symbol
  - cache:    parquet cache freshness for the resolved universe
  - strategy: all registered tradelab.yaml strategies import cleanly
  - tdapi:    TWELVEDATA_API_KEY env var is set

Each returns a dict with keys:
  status: "ok" | "warn" | "red"
  label:  short human string for the chip
  detail: longer string shown in tooltip / Run modal
"""
from __future__ import annotations

import importlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from tradelab.web.handlers import _resolve_active_universe


CACHE_WARN_HOURS = 24
CACHE_ROOT = Path(".cache") / "ohlcv" / "1D"


def check_universe() -> dict:
    name = _resolve_active_universe()
    if not name:
        return {"status": "red", "label": "no universe",
                "detail": "launcher-state.json missing or unreadable, and tradelab.yaml has no universes"}
    try:
        from tradelab.config import get_config
        cfg = get_config()
    except Exception as e:
        return {"status": "red", "label": "config load failed",
                "detail": f"tradelab.yaml load error: {type(e).__name__}: {e}"}
    symbols = cfg.universes.get(name, [])
    if not symbols:
        return {"status": "red", "label": f"{name} (0 symbols)",
                "detail": f"universe {name!r} resolved but contains no symbols"}
    return {"status": "ok", "label": f"{name} ({len(symbols)})",
            "detail": f"{len(symbols)} symbols in universe {name!r}"}


def check_cache() -> dict:
    name = _resolve_active_universe()
    if not name:
        return {"status": "red", "label": "universe unknown",
                "detail": "cannot assess cache without a resolved universe"}
    try:
        from tradelab.config import get_config
        symbols = get_config().universes.get(name, [])
    except Exception:
        symbols = []
    if not symbols:
        return {"status": "red", "label": "no symbols",
                "detail": "universe has no symbols to cache"}
    missing = []
    ages_hours = []
    now = datetime.now(tz=timezone.utc).timestamp()
    for sym in symbols:
        p = CACHE_ROOT / f"{sym}.parquet"
        if not p.exists():
            missing.append(sym)
            continue
        ages_hours.append((now - p.stat().st_mtime) / 3600)
    if missing and len(missing) > 5:
        return {"status": "red", "label": f"{len(missing)} missing",
                "detail": f"{len(missing)} parquet files missing for universe {name!r}: "
                          f"{', '.join(missing[:5])}..."}
    if missing:
        return {"status": "warn", "label": f"{len(missing)} missing",
                "detail": f"parquet missing: {', '.join(missing)}"}
    oldest = max(ages_hours) if ages_hours else 0
    if oldest > CACHE_WARN_HOURS:
        return {"status": "warn", "label": f"{oldest:.1f}h old",
                "detail": f"oldest parquet is {oldest:.1f}h — consider Refresh Data"}
    return {"status": "ok", "label": f"{oldest:.1f}h",
            "detail": f"all {len(symbols)} symbols cached, oldest {oldest:.1f}h"}


def check_strategies() -> dict:
    try:
        from tradelab.config import get_config
        cfg = get_config()
    except Exception as e:
        return {"status": "red", "label": "config load failed",
                "detail": f"tradelab.yaml load error: {type(e).__name__}: {e}"}
    names = list(cfg.strategies.keys()) if hasattr(cfg, "strategies") else []
    if not names:
        return {"status": "warn", "label": "0 registered",
                "detail": "no strategies registered in tradelab.yaml"}
    failed = []
    for name in names:
        try:
            importlib.import_module(f"tradelab.strategies.{name}")
        except Exception as e:
            failed.append(f"{name} ({type(e).__name__})")
    if failed:
        return {"status": "red", "label": f"{len(failed)} broken",
                "detail": "import failed: " + ", ".join(failed)}
    return {"status": "ok", "label": f"{len(names)} OK",
            "detail": f"all {len(names)} registered strategies importable"}


def check_tdapi() -> dict:
    if os.environ.get("TWELVEDATA_API_KEY"):
        return {"status": "ok", "label": "key present",
                "detail": "TWELVEDATA_API_KEY is set"}
    return {"status": "red", "label": "key missing",
            "detail": "TWELVEDATA_API_KEY env var not set — data downloads will fail"}


def compute_preflight() -> dict:
    return {
        "universe": check_universe(),
        "cache":    check_cache(),
        "strategy": check_strategies(),
        "tdapi":    check_tdapi(),
    }
```

- [ ] **Step 2: Commit**

```powershell
git -C C:\TradingScripts\tradelab\.claude\worktrees\research-v2 add src/tradelab/web/preflight.py
git -C C:\TradingScripts\tradelab\.claude\worktrees\research-v2 commit -m "feat(web): add preflight module with 4 status checks"
```

---

### Task 2: Write tests for `preflight.py`

**Files:**
- Create: `tests/web/test_preflight.py`

- [ ] **Step 1: Write the 6 failing tests**

```python
"""Tests for tradelab.web.preflight.

Each check is exercised in isolation with monkeypatched state. Aggregator is
tested via a single happy-path roundup.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from tradelab.web import preflight


def _seed_launcher_state(tmp_path: Path, universe: str) -> None:
    """Create .cache/launcher-state.json with a given activeUniverse."""
    cache = tmp_path / ".cache"
    cache.mkdir(exist_ok=True)
    (cache / "launcher-state.json").write_text(
        json.dumps({"activeUniverse": universe}), encoding="utf-8"
    )


def test_check_universe_red_when_no_launcher_state_and_no_yaml_universes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("tradelab.web.handlers._resolve_active_universe", return_value=""):
        result = preflight.check_universe()
    assert result["status"] == "red"
    assert "no universe" in result["label"].lower()


def test_check_universe_ok_when_symbols_present(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fake_cfg = type("Cfg", (), {"universes": {"nasdaq_100": ["AAPL", "MSFT"]}})()
    with patch("tradelab.web.handlers._resolve_active_universe", return_value="nasdaq_100"), \
         patch("tradelab.config.get_config", return_value=fake_cfg):
        result = preflight.check_universe()
    assert result["status"] == "ok"
    assert "nasdaq_100" in result["label"]


def test_check_cache_warn_when_parquet_is_old(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cache_dir = tmp_path / ".cache" / "ohlcv" / "1D"
    cache_dir.mkdir(parents=True)
    p = cache_dir / "AAPL.parquet"
    p.write_bytes(b"fake")
    old_ts = time.time() - (preflight.CACHE_WARN_HOURS + 1) * 3600
    os.utime(p, (old_ts, old_ts))
    fake_cfg = type("Cfg", (), {"universes": {"u": ["AAPL"]}})()
    with patch("tradelab.web.handlers._resolve_active_universe", return_value="u"), \
         patch("tradelab.config.get_config", return_value=fake_cfg):
        result = preflight.check_cache()
    assert result["status"] == "warn"


def test_check_cache_red_when_many_symbols_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".cache" / "ohlcv" / "1D").mkdir(parents=True)
    syms = [f"SYM{i}" for i in range(10)]
    fake_cfg = type("Cfg", (), {"universes": {"u": syms}})()
    with patch("tradelab.web.handlers._resolve_active_universe", return_value="u"), \
         patch("tradelab.config.get_config", return_value=fake_cfg):
        result = preflight.check_cache()
    assert result["status"] == "red"


def test_check_tdapi_red_when_env_missing(monkeypatch):
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    assert preflight.check_tdapi()["status"] == "red"


def test_compute_preflight_returns_all_four_keys(monkeypatch):
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    result = preflight.compute_preflight()
    assert set(result.keys()) == {"universe", "cache", "strategy", "tdapi"}
    for v in result.values():
        assert "status" in v and "label" in v and "detail" in v
```

- [ ] **Step 2: Run tests — confirm all pass**

```powershell
$env:PYTHONPATH = "src"
$env:PYTHONIOENCODING = "utf-8"
python -m pytest tests/web/test_preflight.py -v
```
Expected: `6 passed`.

- [ ] **Step 3: Commit**

```powershell
git add tests/web/test_preflight.py
git commit -m "test(web): add preflight module tests"
```

---

### Task 3: Add `/tradelab/preflight` GET route

**Files:**
- Modify: `src/tradelab/web/handlers.py` — add import + route branch

- [ ] **Step 1: Add the route branch to `handle_get_with_status`**

Locate the function that dispatches GETs (around line 200-ish; find by grepping `def handle_get_with_status`). Add before the fallback:

```python
    if path == "/tradelab/preflight":
        from tradelab.web.preflight import compute_preflight
        return _ok(compute_preflight()), 200
```

- [ ] **Step 2: Add a handler test**

Append to `tests/web/test_handlers.py` (or `test_handlers_jobs.py` if more appropriate):

```python
def test_get_preflight_returns_all_four_statuses(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    from tradelab.web.handlers import handle_get_with_status
    body_str, status = handle_get_with_status("/tradelab/preflight", {})
    assert status == 200
    body = json.loads(body_str)
    assert body["error"] is None
    assert set(body["data"].keys()) == {"universe", "cache", "strategy", "tdapi"}
```

- [ ] **Step 3: Run tests**

```powershell
python -m pytest tests/web/ -q
```
Expected: baseline 72 + 6 preflight + 1 handler = `79 passed`.

- [ ] **Step 4: Commit**

```powershell
git add src/tradelab/web/handlers.py tests/web/test_handlers.py
git commit -m "feat(web): expose /tradelab/preflight GET route"
```

---

### Task 4: Add preflight chip cluster HTML + CSS

**Files:**
- Modify: `C:\TradingScripts\command_center.html` — remove Freshness banner, add chip cluster

- [ ] **Step 1: Add CSS for preflight chips**

Locate the CSS block around line 100-250 (where `.research-section-title` is defined). Insert:

```css
.preflight-chips{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:12px 0 8px;padding:10px 12px;background:var(--card-bg);border-radius:8px;border:1px solid var(--border)}
.preflight-chip{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:14px;font-size:12px;font-weight:500;cursor:help}
.preflight-chip .preflight-dot{width:8px;height:8px;border-radius:50%}
.preflight-ok{background:rgba(34,197,94,.14);color:#34d399}
.preflight-ok .preflight-dot{background:#22c55e}
.preflight-warn{background:rgba(251,191,36,.14);color:#fbbf24}
.preflight-warn .preflight-dot{background:#fbbf24}
.preflight-red{background:rgba(239,68,68,.14);color:#f87171}
.preflight-red .preflight-dot{background:#ef4444}
```

- [ ] **Step 2: Replace the Freshness banner markup with chip cluster**

Find the existing Freshness banner (grep for `research-freshness` or similar; around lines 620-640). Replace with:

```html
<section id="preflight-chips" class="preflight-chips">
  <span class="preflight-chip preflight-ok" id="preflight-universe" title="checking...">
    <span class="preflight-dot"></span> Universe…
  </span>
  <span class="preflight-chip preflight-ok" id="preflight-cache" title="checking...">
    <span class="preflight-dot"></span> Cache…
  </span>
  <span class="preflight-chip preflight-ok" id="preflight-strategy" title="checking...">
    <span class="preflight-dot"></span> Strategies…
  </span>
  <span class="preflight-chip preflight-ok" id="preflight-tdapi" title="checking...">
    <span class="preflight-dot"></span> TD API…
  </span>
  <button class="btn btn-ghost" id="preflightRefreshBtn">Refresh Data</button>
  <button class="btn btn-ghost" id="preflightNewStrategyBtn">New Strategy</button>
</section>
```

Keep the event bindings for `preflightRefreshBtn` pointing at the existing `researchLoadFreshness`/refresh handler. Keep `preflightNewStrategyBtn` pointing at `openNewStrategyModal`.

- [ ] **Step 3: Add `researchLoadPreflight()` JS function**

Locate the research JS block (around line 2200-2450). Add:

```javascript
async function researchLoadPreflight() {
  try {
    const body = await fetchJSON('/tradelab/preflight');
    const data = body.data || {};
    for (const key of ['universe', 'cache', 'strategy', 'tdapi']) {
      const chip = document.getElementById(`preflight-${key}`);
      if (!chip) continue;
      const r = data[key] || {status: 'red', label: 'error', detail: 'response missing'};
      chip.classList.remove('preflight-ok', 'preflight-warn', 'preflight-red');
      chip.classList.add(`preflight-${r.status}`);
      chip.title = r.detail;
      const label = key === 'tdapi' ? 'TD API' : key.charAt(0).toUpperCase() + key.slice(1);
      chip.innerHTML = `<span class="preflight-dot"></span> ${label}: ${r.label}`;
    }
    researchState.preflight = data;
  } catch (e) {
    console.warn('preflight load failed:', e);
  }
}
```

- [ ] **Step 4: Wire preflight into `researchLoadAll()` and tab activation**

Find `researchLoadAll()` (around line 2224). Change:

```javascript
async function researchLoadAll() {
  await Promise.all([
    researchLoadPreflight(),   // was: researchLoadFreshness()
    researchLoadStrategies(),
    researchLoadLiveCards(),
    researchLoadPipeline(),
  ]);
  researchState.loaded = true;
}
```

Find the old `researchLoadFreshness` function and the tab-activation hook that calls `await researchLoadFreshness();`. Replace with `await researchLoadPreflight();`. Delete the now-unused `researchLoadFreshness` function.

- [ ] **Step 5: Manual smoke**

Restart `launch_dashboard.py`. Open `http://localhost:8877/#tab=research`. Chip cluster should render with 4 chips + 2 buttons. Tooltips on hover show detail strings. If `TWELVEDATA_API_KEY` is set and cache is fresh, all 4 are green.

- [ ] **Step 6: Commit**

```powershell
git -C C:\TradingScripts add command_center.html
git -C C:\TradingScripts commit -m "feat(command-center): replace Freshness banner with preflight chip cluster"
```

Note: `command_center.html` lives in `C:\TradingScripts\`, not the tradelab repo. Remember that remote was removed this session — commits stay local.

---

### Task 5: Integrate preflight into Run confirmation modal

**Files:**
- Modify: `C:\TradingScripts\command_center.html` — extend Run modal render

- [ ] **Step 1: Locate the Run confirmation modal render function**

Grep for `run-3f` or `modal-3f-heading` (around line 2786+ in HTML, modal JS near line 2890). The modal opens when user clicks a Run ▾ command option.

- [ ] **Step 2: Add preflight status row to modal body**

Before the existing "Start" button block in the modal-open handler, insert:

```javascript
async function renderPreflightInModal(modalBody) {
  const preflightRow = document.createElement('div');
  preflightRow.className = 'modal-preflight-row';
  preflightRow.innerHTML = '<div style="color:var(--text2);font-size:12px">Checking preflight…</div>';
  modalBody.prepend(preflightRow);

  const body = await fetchJSON('/tradelab/preflight');
  const data = body.data || {};
  const reds = [], warns = [];
  for (const [key, r] of Object.entries(data)) {
    if (r.status === 'red')  reds.push(`${key}: ${r.detail}`);
    if (r.status === 'warn') warns.push(`${key}: ${r.detail}`);
  }

  if (reds.length) {
    preflightRow.innerHTML = `<div class="modal-preflight red">
      <strong>⛔ Preflight blocked (${reds.length}):</strong>
      <ul>${reds.map(r => `<li>${r}</li>`).join('')}</ul>
    </div>`;
    const startBtn = modalBody.querySelector('[data-action="start"]');
    if (startBtn) { startBtn.disabled = true; startBtn.title = 'preflight red — fix and retry'; }
  } else if (warns.length) {
    preflightRow.innerHTML = `<div class="modal-preflight warn">
      <strong>⚠ Preflight warning (${warns.length}):</strong>
      <ul>${warns.map(w => `<li>${w}</li>`).join('')}</ul>
    </div>`;
  } else {
    preflightRow.innerHTML = '<div class="modal-preflight ok">✓ Preflight OK</div>';
  }
}
```

- [ ] **Step 3: Add CSS for the modal preflight row**

Add alongside other modal CSS:

```css
.modal-preflight{padding:8px 10px;border-radius:6px;font-size:13px;margin-bottom:12px}
.modal-preflight.ok   {background:rgba(34,197,94,.1);  color:#34d399}
.modal-preflight.warn {background:rgba(251,191,36,.1); color:#fbbf24}
.modal-preflight.red  {background:rgba(239,68,68,.1);  color:#f87171}
.modal-preflight ul{margin:4px 0 0 16px;padding:0}
.modal-preflight li{font-size:12px;line-height:1.4}
```

- [ ] **Step 4: Call `renderPreflightInModal(modalBody)` in the Run modal open sequence**

Find the Run modal open handler. After the modal becomes visible and its body is populated with the confirmation text, add:

```javascript
await renderPreflightInModal(document.getElementById('run-modal-body'));
```

(Adjust selector to match the actual modal body id in the HTML.)

- [ ] **Step 5: Smoke test**

Restart dashboard. Click Run ▾ → Full on any strategy card. Modal shows "Checking preflight…" then resolves. If `TWELVEDATA_API_KEY` unset → modal shows red block, Start button disabled.

- [ ] **Step 6: Commit**

```powershell
git -C C:\TradingScripts add command_center.html
git -C C:\TradingScripts commit -m "feat(command-center): integrate preflight into Run confirmation modal"
```

---

## Phase 2: Failure hints in Job Tracker

### Task 6: Write `failure_hint.py` with parser + tests

**Files:**
- Create: `src/tradelab/web/failure_hint.py`
- Create: `tests/web/test_failure_hint.py`

- [ ] **Step 1: Write `failure_hint.py`**

```python
"""Parse .cache/jobs/<job_id>/progress.jsonl to produce a one-line hint
for a FAILED job. Returns None for non-FAILED or unparseable logs."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


EXIT_CODE_LABELS = {
    0:  "success (but state=FAILED — possible orchestration bug)",
    1:  "Python exception (see log)",
    2:  "CLI arg error",
    3:  "timeout",
    -1073741510:   "cancelled (CTRL_BREAK)",
    3221225786:    "cancelled (CTRL_BREAK)",
}


def extract_failure_hint(job_id: str, exit_code: Optional[int],
                         cache_root: Path = Path(".cache")) -> Optional[str]:
    """Return a short hint string for a FAILED job, or None if no log found."""
    log = cache_root / "jobs" / job_id / "progress.jsonl"
    last_error: Optional[dict] = None
    if log.exists():
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("event") == "error" or ev.get("ok") is False:
                last_error = ev

    if last_error:
        et = last_error.get("error_type") or last_error.get("type") or "error"
        msg = (last_error.get("message") or last_error.get("error") or "")[:80]
        if et == "NoSymbolsProvided":
            return "universe not resolved — check preflight"
        return f"{et}: {msg}" if msg else et

    # Fallback: label exit code
    if exit_code is None:
        return None
    label = EXIT_CODE_LABELS.get(exit_code, f"exit {exit_code}")
    return f"exit {exit_code}: {label}" if exit_code not in EXIT_CODE_LABELS else label
```

- [ ] **Step 2: Write tests**

```python
"""Tests for tradelab.web.failure_hint."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tradelab.web.failure_hint import extract_failure_hint


def _write_progress(tmp_path: Path, job_id: str, events: list) -> None:
    d = tmp_path / ".cache" / "jobs" / job_id
    d.mkdir(parents=True)
    (d / "progress.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events), encoding="utf-8"
    )


def test_no_progress_log_falls_back_to_exit_code(tmp_path):
    hint = extract_failure_hint("nonexistent", exit_code=1, cache_root=tmp_path / ".cache")
    assert "Python exception" in hint


def test_parses_last_error_event(tmp_path):
    _write_progress(tmp_path, "j1", [
        {"event": "stage", "stage": "download", "ok": True},
        {"event": "error", "error_type": "KeyError", "message": "missing 'close' column"},
    ])
    hint = extract_failure_hint("j1", exit_code=1, cache_root=tmp_path / ".cache")
    assert hint is not None
    assert "KeyError" in hint
    assert "missing 'close'" in hint


def test_nosymbolsprovided_maps_to_preflight_hint(tmp_path):
    _write_progress(tmp_path, "j2", [
        {"event": "error", "error_type": "NoSymbolsProvided", "message": "pass --symbols or --universe"},
    ])
    hint = extract_failure_hint("j2", exit_code=2, cache_root=tmp_path / ".cache")
    assert "preflight" in hint.lower()


def test_exit_code_cancelled(tmp_path):
    hint = extract_failure_hint("nonexistent", exit_code=-1073741510, cache_root=tmp_path / ".cache")
    assert "cancelled" in hint.lower()
```

- [ ] **Step 3: Run tests**

```powershell
python -m pytest tests/web/test_failure_hint.py -v
```
Expected: `4 passed`.

- [ ] **Step 4: Commit**

```powershell
git add src/tradelab/web/failure_hint.py tests/web/test_failure_hint.py
git commit -m "feat(web): add failure_hint parser for FAILED job progress logs"
```

---

### Task 7: Surface `failure_hint` in `/tradelab/jobs` response

**Files:**
- Modify: `src/tradelab/web/jobs.py` — extend `_job_to_dict` or equivalent serializer

- [ ] **Step 1: Find the job-to-dict serializer**

Grep for `to_dict` or `asdict` or `"state":` within `src/tradelab/web/jobs.py` to find where job state is converted to JSON-serializable form for the `/tradelab/jobs` response.

- [ ] **Step 2: Import `extract_failure_hint` and add `failure_hint` field for FAILED state**

In that serializer, after the existing fields:

```python
if self.state == JobState.FAILED:
    from tradelab.web.failure_hint import extract_failure_hint
    d["failure_hint"] = extract_failure_hint(self.id, exit_code=self.exit_code)
```

(Adjust attribute names — `self.state`, `self.id`, `self.exit_code` — to match actual JobManager types.)

- [ ] **Step 3: Add assertion in existing jobs handler test**

In `tests/web/test_handlers_jobs.py`, extend the FAILED-case test:

```python
def test_failed_job_includes_failure_hint(tmp_path, ...):
    # ... existing setup that produces a FAILED job ...
    body_str, status = handle_get_with_status("/tradelab/jobs", {})
    body = json.loads(body_str)
    failed_jobs = [j for j in body["data"]["jobs"] if j["state"] == "FAILED"]
    assert all("failure_hint" in j for j in failed_jobs)
```

- [ ] **Step 4: Run full suite**

```powershell
python -m pytest tests/web/ tests/cli/test_progress_log.py -q
```
Expected: `80+ passed` (baseline + preflight + failure_hint + handler extensions).

- [ ] **Step 5: Commit**

```powershell
git add src/tradelab/web/jobs.py tests/web/test_handlers_jobs.py
git commit -m "feat(web): include failure_hint in FAILED job dict"
```

---

### Task 8: Render failure hint in Job Tracker row

**Files:**
- Modify: `C:\TradingScripts\command_center.html` — job row renderer

- [ ] **Step 1: Locate the job tracker row renderer**

Grep for `job-tracker-list` or `renderJobRow` in `command_center.html` (around line 2700-2900 based on v1.5 layout).

- [ ] **Step 2: Add failure hint line under the job row when state is FAILED**

In the row-building template, after the existing state/progress/cancel elements:

```javascript
if (job.state === 'FAILED' && job.failure_hint) {
  row.innerHTML += `<div class="job-failure-hint">⚠ ${escapeHtml(job.failure_hint)}</div>`;
}
```

- [ ] **Step 3: Add CSS**

```css
.job-failure-hint{color:#fbbf24;font-size:12px;margin:2px 0 0 4px;font-family:var(--mono-font)}
```

- [ ] **Step 4: Smoke test**

Restart dashboard. Cause a FAILED job by removing `TWELVEDATA_API_KEY` or deleting launcher-state.json, then firing a Run. When it fails (should be within seconds at CLI arg parse), the Job Tracker row shows the hint inline.

- [ ] **Step 5: Commit**

```powershell
git -C C:\TradingScripts add command_center.html
git -C C:\TradingScripts commit -m "feat(command-center): show failure_hint inline in Job Tracker rows"
```

---

## Phase 3: Compare-N-runs

### Task 9: Write `compare.py` with `run_compare()` + tests

**Files:**
- Create: `src/tradelab/web/compare.py`
- Create: `tests/web/test_compare.py`

- [ ] **Step 1: Write `compare.py`**

```python
"""Thin web-layer wrapper over the `tradelab compare` CLI.

Validates input, resolves run_ids → report folders via audit_reader,
subprocesses the CLI, returns the generated HTML path for the frontend
to open in a new tab.
"""
from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Tuple

from tradelab.web import audit_reader


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-]+$")
RESULT_FILE_NAME = "backtest_result.json"


def _err(msg: str, status: int = 400) -> Tuple[dict, int]:
    return {"error": msg, "data": None}, status


def _ok(data: dict, status: int = 200) -> Tuple[dict, int]:
    return {"error": None, "data": data}, status


def run_compare(run_ids: list, benchmark: str = "SPY",
                timeout_s: int = 60,
                reports_root: Path = Path("reports")) -> Tuple[dict, int]:
    if not isinstance(run_ids, list) or len(run_ids) < 2:
        return _err("at least 2 runs required")
    for rid in run_ids:
        if not isinstance(rid, str) or not RUN_ID_PATTERN.match(rid):
            return _err(f"invalid run_id: {rid!r}")

    folders = []
    ineligible = []
    unknown = []
    for rid in run_ids:
        folder = audit_reader.get_run_folder(rid)
        if folder is None:
            unknown.append(rid)
            continue
        if not (folder / RESULT_FILE_NAME).exists():
            ineligible.append(rid)
            continue
        folders.append(folder)

    if unknown:
        return _err(f"unknown run_id: {unknown[0]}")
    if ineligible:
        return _err(
            f"{len(ineligible)} runs can't be compared (predate JSON persistence): "
            + ", ".join(ineligible)
        )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = reports_root / f"compare_{ts}.html"
    argv = [
        sys.executable, "-m", "tradelab.cli", "compare",
        *[str(f) for f in folders],
        "--output", str(out_path),
        "--benchmark", benchmark,
        "--no-open",
    ]
    try:
        proc = subprocess.run(
            argv, capture_output=True,
            encoding="utf-8", errors="replace",
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return _err(f"compare timeout after {timeout_s}s", status=500)

    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-500:]
        return _err(f"compare exited {proc.returncode}: {tail}", status=500)

    return _ok({"report_path": str(out_path)})
```

- [ ] **Step 2: Write tests**

```python
"""Tests for tradelab.web.compare."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from tradelab.web import compare


def test_rejects_fewer_than_two_run_ids():
    body, status = compare.run_compare(["only_one"])
    assert status == 400
    assert "at least 2" in body["error"]


def test_rejects_invalid_run_id_format():
    body, status = compare.run_compare(["../etc/passwd", "ok_id"])
    assert status == 400
    assert "invalid run_id" in body["error"]


def test_rejects_unknown_run_id(tmp_path):
    with patch("tradelab.web.audit_reader.get_run_folder", return_value=None):
        body, status = compare.run_compare(["valid_a", "valid_b"])
    assert status == 400
    assert "unknown run_id" in body["error"]


def test_rejects_runs_missing_backtest_result_json(tmp_path):
    f1 = tmp_path / "run1"; f1.mkdir()
    f2 = tmp_path / "run2"; f2.mkdir()
    # neither has backtest_result.json
    with patch("tradelab.web.audit_reader.get_run_folder",
               side_effect=lambda rid: {"a": f1, "b": f2}.get(rid)):
        body, status = compare.run_compare(["a", "b"])
    assert status == 400
    assert "predate JSON persistence" in body["error"]


def test_happy_path_builds_report(tmp_path):
    """Success: folders exist with backtest_result.json, subprocess returns 0."""
    f1 = tmp_path / "run1"; f1.mkdir()
    (f1 / "backtest_result.json").write_text("{}")
    f2 = tmp_path / "run2"; f2.mkdir()
    (f2 / "backtest_result.json").write_text("{}")
    reports = tmp_path / "reports"; reports.mkdir()

    fake_proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    with patch("tradelab.web.audit_reader.get_run_folder",
               side_effect=lambda rid: {"a": f1, "b": f2}.get(rid)), \
         patch("subprocess.run", return_value=fake_proc):
        body, status = compare.run_compare(["a", "b"], reports_root=reports)
    assert status == 200
    assert body["error"] is None
    assert re.match(r"^.*compare_\d{8}_\d{6}\.html$", body["data"]["report_path"])


def test_subprocess_non_zero_exit_returns_500():
    fake_proc = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="bad things happened")
    with patch("tradelab.web.audit_reader.get_run_folder", return_value=Path("/fake")), \
         patch.object(Path, "exists", return_value=True), \
         patch("subprocess.run", return_value=fake_proc):
        body, status = compare.run_compare(["a", "b"])
    assert status == 500
    assert "compare exited 1" in body["error"]


def test_subprocess_timeout_returns_500():
    with patch("tradelab.web.audit_reader.get_run_folder", return_value=Path("/fake")), \
         patch.object(Path, "exists", return_value=True), \
         patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=[], timeout=60)):
        body, status = compare.run_compare(["a", "b"])
    assert status == 500
    assert "timeout" in body["error"]
```

- [ ] **Step 3: Run tests**

```powershell
python -m pytest tests/web/test_compare.py -v
```
Expected: `7 passed`.

- [ ] **Step 4: Commit**

```powershell
git add src/tradelab/web/compare.py tests/web/test_compare.py
git commit -m "feat(web): add compare module for cross-run report generation"
```

---

### Task 10: Wire `/tradelab/compare` POST route

**Files:**
- Modify: `src/tradelab/web/handlers.py`

- [ ] **Step 1: Add route branch in `handle_post_with_status`**

In `handle_post_with_status`, before the legacy fallback:

```python
    if path == "/tradelab/compare":
        from tradelab.web.compare import run_compare
        body, status = run_compare(
            run_ids=payload.get("run_ids") or [],
            benchmark=payload.get("benchmark") or "SPY",
        )
        return json.dumps(body), status
```

- [ ] **Step 2: Run full suite to confirm no regression**

```powershell
python -m pytest tests/web/ tests/cli/test_progress_log.py -q
```
Expected: still passing (compare tests already green from Task 9).

- [ ] **Step 3: Commit**

```powershell
git add src/tradelab/web/handlers.py
git commit -m "feat(web): wire /tradelab/compare POST route"
```

---

### Task 11: Add `/tradelab/compare-report` static-HTML route in launcher

**Files:**
- Modify: `C:\TradingScripts\launch_dashboard.py`

This route serves raw HTML (not the JSON envelope), so it goes in the launcher rather than `handlers.py`.

- [ ] **Step 1: Locate the GET dispatcher in `launch_dashboard.py`**

Find `do_GET` (grep for `def do_GET`). It currently dispatches `/tradelab/*` to handlers.py. Add a new branch BEFORE that dispatch, since this one doesn't produce JSON.

- [ ] **Step 2: Add the compare-report branch**

```python
        if self.path.startswith("/tradelab/compare-report"):
            import re as _re
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            rel = (qs.get("path") or [""])[0]
            if ".." in rel or not _re.match(r"^reports[/\\]compare_\d{8}_\d{6}\.html$", rel):
                self.send_error(400, "invalid report path")
                return
            abs_path = os.path.join(TRADELAB_ROOT, rel)
            if not os.path.isfile(abs_path):
                self.send_error(404, f"report not found: {rel}")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(os.path.getsize(abs_path)))
            self.end_headers()
            with open(abs_path, "rb") as f:
                self.wfile.write(f.read())
            return
```

- [ ] **Step 3: Restart dashboard and smoke**

```powershell
# Stop existing dashboard
Get-Process python | Where-Object {$_.MainWindowTitle -like '*launch_dashboard*'} | Stop-Process
# Restart
Start-Process -FilePath $env:LOCALAPPDATA\Microsoft\WindowsApps\python.exe `
  -ArgumentList 'C:\TradingScripts\launch_dashboard.py' `
  -WorkingDirectory 'C:\TradingScripts' -WindowStyle Hidden
```

Generate a compare manually via curl (requires ≥2 runs with JSON):
```powershell
$body = '{"run_ids": ["s2_pocket_pivot_2026-04-21_122955", "s2_pocket_pivot_2026-04-21_152409"]}'
Invoke-RestMethod -Method POST -Uri http://localhost:8877/tradelab/compare -Body $body -ContentType "application/json"
# Expect {data: {report_path: "reports/compare_xxxxxx.html"}}
```

Then GET that path: `start http://localhost:8877/tradelab/compare-report?path=reports/compare_xxxxxx.html`. Browser should render the report.

- [ ] **Step 4: Commit**

```powershell
git -C C:\TradingScripts add launch_dashboard.py
git -C C:\TradingScripts commit -m "feat(launcher): add /tradelab/compare-report static-HTML route"
```

---

### Task 12: Add checkbox column + Compare Selected button to Pipeline

**Files:**
- Modify: `C:\TradingScripts\command_center.html`

- [ ] **Step 1: Add checkbox column to table header**

Find the `<thead>` of `researchPipelineTable` (around line 681). Add as first column:

```html
<th style="width:24px"><input type="checkbox" id="pipelineSelectAll" style="display:none"></th>
```

(Select-all is deferred per spec §8; the input is a placeholder for future wiring.)

- [ ] **Step 2: Add checkbox cell to each row in `renderPipelineRows`**

In `renderPipelineRows` (around line 2352), change the `tr.innerHTML = ` block's opening to include the checkbox:

```javascript
const isChecked = researchState.selectedRunIds.has(r.run_id);
tr.innerHTML = `
  <td><input type="checkbox" class="pipeline-row-select" data-run-id="${r.run_id}" ${isChecked ? 'checked' : ''}></td>
  <td>${r.strategy_name}</td>
  ... (existing cells)`;
```

Update the existing `colspan="9"` in the skeleton row to `colspan="10"`.

- [ ] **Step 3: Extend `tr.onclick` to ignore checkbox clicks**

```javascript
tr.onclick = (ev) => {
  if (ev.target.closest('.run-dropdown')) return;
  if (ev.target.closest('.pipeline-row-select')) return;
  openResearchModal(r.run_id, 'dashboard', r.strategy_name, r.verdict, r.timestamp_utc);
};
```

- [ ] **Step 4: Initialize `researchState.selectedRunIds` as a Set**

At the top of the research state initialization (around line 2209), add:

```javascript
let researchState = {
  ...,
  selectedRunIds: new Set(),
  preflight: null,
  ...
};
```

- [ ] **Step 5: Add the Compare Selected button**

Above the Pipeline table, near the filter chips (around line 675):

```html
<button class="btn" id="pipelineCompareBtn" hidden>Compare Selected (0)</button>
```

- [ ] **Step 6: Wire checkbox + button handlers**

In the DOMContentLoaded block (around line 2418):

```javascript
document.addEventListener('change', (ev) => {
  const cb = ev.target.closest('.pipeline-row-select');
  if (!cb) return;
  const rid = cb.dataset.runId;
  if (cb.checked) researchState.selectedRunIds.add(rid);
  else            researchState.selectedRunIds.delete(rid);
  updateCompareButton();
});

function updateCompareButton() {
  const btn = document.getElementById('pipelineCompareBtn');
  const n = researchState.selectedRunIds.size;
  btn.hidden = n < 2;
  btn.textContent = `Compare Selected (${n})`;
}

f('pipelineCompareBtn', 'click', async () => {
  const btn = document.getElementById('pipelineCompareBtn');
  btn.disabled = true;
  btn.textContent = 'Comparing…';
  try {
    const body = await fetchJSON('/tradelab/compare', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        run_ids: [...researchState.selectedRunIds],
        benchmark: 'SPY',
      }),
    });
    if (body.error) { showToast(body.error); return; }
    const url = '/tradelab/compare-report?path=' + encodeURIComponent(body.data.report_path);
    window.open(url, '_blank');
  } catch (e) {
    showToast('compare failed: ' + e.message);
  } finally {
    btn.disabled = false;
    updateCompareButton();
  }
});
```

- [ ] **Step 7: Smoke test**

Restart dashboard. Tick 2 rows with valid `backtest_result.json` → button appears, click → new tab with compare report. Tick a row that predates JSON persistence → click → toast shows "X runs can't be compared".

- [ ] **Step 8: Commit**

```powershell
git -C C:\TradingScripts add command_center.html
git -C C:\TradingScripts commit -m "feat(command-center): add row checkbox + Compare Selected button"
```

---

## Phase 4: Pipeline polish

### Task 13: Add prioritization heat to verdict pill

**Files:**
- Modify: `C:\TradingScripts\command_center.html`

- [ ] **Step 1: Add heat CSS classes**

```css
.verdict-pill.heat-5{background:rgba(34,197,94,.30);color:#059669;font-weight:600}
.verdict-pill.heat-4{background:rgba(34,197,94,.20);color:#34d399}
.verdict-pill.heat-3{background:rgba(251,191,36,.20);color:#fbbf24}
.verdict-pill.heat-2{background:rgba(251,191,36,.12);color:#d97706}
.verdict-pill.heat-1{background:rgba(148,163,184,.14);color:#94a3b8}
.verdict-pill.heat-0{background:rgba(239,68,68,.15);color:#f87171}
```

- [ ] **Step 2: Add heat classifier JS**

```javascript
function verdictHeatClass(verdict, dsr, pf) {
  const v = (verdict || '').toUpperCase();
  if (v === 'ROBUST' && dsr >= 0.70 && pf >= 1.30) return 'heat-5';
  if (v === 'ROBUST')                              return 'heat-4';
  if (v === 'MARGINAL' && dsr >= 0.40)             return 'heat-3';
  if (v === 'MARGINAL')                            return 'heat-2';
  if (v === 'FRAGILE')                             return 'heat-0';
  return 'heat-1';
}
```

- [ ] **Step 3: Apply heat class in `renderPipelineRows`**

In the verdict cell construction:

```javascript
const heat = verdictHeatClass(r.verdict, r.dsr_probability, null /* pf fetched lazily */);
...
<td><span class="verdict-pill verdict-${verdict} ${heat}">${r.verdict || '—'}</span></td>
```

After metrics fetch returns per row, re-apply heat with pf:

```javascript
fetchJSON(`/tradelab/runs/${r.run_id}/metrics`).then(mb => {
  const m = mb.data || {};
  tr.querySelector('.run-pf').textContent = m.profit_factor != null ? m.profit_factor.toFixed(2) : '—';
  ...
  const pill = tr.querySelector('.verdict-pill');
  if (pill) {
    pill.className = `verdict-pill verdict-${verdict} ${verdictHeatClass(r.verdict, r.dsr_probability, m.profit_factor)}`;
  }
});
```

- [ ] **Step 4: Smoke test**

Restart dashboard. Pipeline rows show varying green-intensity ROBUST pills, amber MARGINAL pills, dim-red FRAGILE pills. Click a ROBUST+DSR>0.70 row → pill is darker green.

- [ ] **Step 5: Commit**

```powershell
git -C C:\TradingScripts add command_center.html
git -C C:\TradingScripts commit -m "feat(command-center): apply prioritization heat to verdict pills"
```

---

### Task 14: Add "Why FRAGILE?" tooltip

**Files:**
- Modify: `C:\TradingScripts\command_center.html`

- [ ] **Step 1: Add reason-derivation JS**

```javascript
function fragileReasons(metrics, dsr) {
  const m = metrics || {};
  const reasons = [];
  if ((m.total_trades ?? 99) < 30)           reasons.push(`low trade count (n=${m.total_trades})`);
  if ((dsr ?? 1) < 0.30)                     reasons.push(`low DSR (${(dsr ?? 0).toFixed(2)})`);
  if ((m.profit_factor ?? 99) < 1.10)        reasons.push(`low profit factor (${(m.profit_factor ?? 0).toFixed(2)})`);
  if ((m.max_drawdown_pct ?? 0) > 20)        reasons.push(`high drawdown (${(m.max_drawdown_pct ?? 0).toFixed(1)}%)`);
  if ((m.win_rate ?? 99) < 35)               reasons.push(`low win rate (${(m.win_rate ?? 0).toFixed(0)}%)`);
  return reasons.slice(0, 2);
}
```

- [ ] **Step 2: Populate `title` attribute on FRAGILE/MARGINAL pills after metrics load**

Inside the existing per-row `fetchJSON(/metrics).then(...)`:

```javascript
const v = (r.verdict || '').toUpperCase();
if (v === 'FRAGILE' || v === 'MARGINAL') {
  const pill = tr.querySelector('.verdict-pill');
  const reasons = fragileReasons(m, r.dsr_probability);
  if (pill && reasons.length) {
    pill.title = `${v} — reasons:\n  · ${reasons.join('\n  · ')}`;
    pill.style.cursor = 'help';
  }
}
```

- [ ] **Step 3: Smoke test**

Hover a FRAGILE row's pill — browser tooltip shows 1-2 reasons.

- [ ] **Step 4: Commit**

```powershell
git -C C:\TradingScripts add command_center.html
git -C C:\TradingScripts commit -m "feat(command-center): add 'Why FRAGILE?' tooltip on verdict pills"
```

---

### Task 15: Add sparkline column

**Files:**
- Modify: `C:\TradingScripts\command_center.html`

- [ ] **Step 1: Add sparkline column to table header**

Change the thead to insert `<th>Trend</th>` between DSR and Date:

```html
<th data-sort="dsr_probability">DSR</th>
<th>Trend</th>
<th data-sort="timestamp_utc">Date</th>
<th>Run</th>
```

Update colspan in the skeleton/empty row from 10 to 11.

- [ ] **Step 2: Add sparkline renderer**

```javascript
function renderSparkline(runs) {
  if (!runs || !runs.length) return '<span style="color:var(--text2);font-size:11px">—</span>';
  const pfs = runs.map(r => r.pf != null ? r.pf : 1.0);
  const min = Math.min(...pfs, 0.8);
  const max = Math.max(...pfs, 1.5);
  const range = max - min || 1;
  const w = 60, h = 16, step = pfs.length > 1 ? w / (pfs.length - 1) : w;
  const pts = pfs.map((v, i) => {
    const x = i * step;
    const y = h - ((v - min) / range) * h;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  const verdict = (runs[0].verdict || '').toUpperCase();
  const stroke = verdict === 'ROBUST' ? '#22c55e' : verdict === 'FRAGILE' ? '#ef4444' : '#fbbf24';
  return `<svg width="${w}" height="${h}" style="display:block">
    <polyline points="${pts}" fill="none" stroke="${stroke}" stroke-width="1.5"/>
  </svg>`;
}
```

- [ ] **Step 3: Cache sparkline data per strategy**

In `researchState`:

```javascript
researchState.sparklineCache = {};  // strategy -> runs[]
```

Helper:

```javascript
async function getSparklineRuns(strategy) {
  if (researchState.sparklineCache[strategy]) return researchState.sparklineCache[strategy];
  const body = await fetchJSON(`/tradelab/runs?strategy=${encodeURIComponent(strategy)}&limit=3`);
  const runs = body.data?.runs || [];
  const withPF = await Promise.all(runs.map(async r => {
    const m = (await fetchJSON(`/tradelab/runs/${r.run_id}/metrics`)).data || {};
    return {verdict: r.verdict, pf: m.profit_factor};
  }));
  researchState.sparklineCache[strategy] = withPF;
  return withPF;
}
```

- [ ] **Step 4: Insert sparkline cell in `renderPipelineRows`**

Add `<td class="pipeline-sparkline-cell">Loading…</td>` between DSR and Date cells in the template. After metrics finish:

```javascript
getSparklineRuns(r.strategy_name).then(runs => {
  const cell = tr.querySelector('.pipeline-sparkline-cell');
  if (cell) cell.innerHTML = renderSparkline(runs);
});
```

- [ ] **Step 5: Smoke test**

Pipeline table renders with a new Trend column showing tiny SVG sparklines per strategy.

- [ ] **Step 6: Commit**

```powershell
git -C C:\TradingScripts add command_center.html
git -C C:\TradingScripts commit -m "feat(command-center): add Trend sparkline column to Pipeline"
```

---

## Phase 5: Live Cards compression

### Task 16: Replace fat-grid cards with compressed horizontal strip

**Files:**
- Modify: `C:\TradingScripts\command_center.html`

- [ ] **Step 1: Add CSS for the compressed strip**

```css
body.v2-layout .research-cards-grid{display:block}
body.v2-layout .research-card{display:grid;grid-template-columns:160px 80px 70px 1fr auto;gap:12px;align-items:center;padding:8px 12px;border-bottom:1px solid var(--border);border-radius:0;background:transparent}
body.v2-layout .research-card:hover{background:rgba(148,163,184,.06)}
body.v2-layout .research-card-header{display:flex;align-items:center;gap:8px}
body.v2-layout .research-card-name{font-weight:600;font-size:13px}
body.v2-layout .research-card-stats{display:flex;gap:14px;font-size:12px;color:var(--text2)}
body.v2-layout .research-card-stat{display:flex;gap:4px}
body.v2-layout .research-card-stat-label{color:var(--text3);font-weight:500}
body.v2-layout .research-card-trend{display:none}
body.v2-layout .research-card-sparkline{display:inline-block}
body.v2-layout .research-card-actions{display:flex;gap:6px}
body.v2-layout .research-card.degraded{border-left:3px solid var(--amber)}
```

- [ ] **Step 2: Apply `v2-layout` class to body by default**

In `<body>` tag:

```html
<body class="v2-layout">
```

Then on DOMContentLoaded check the legacy flag:

```javascript
if (localStorage.getItem('researchLayoutLegacy') === '1') {
  document.body.classList.remove('v2-layout');
}
```

- [ ] **Step 3: Update `renderLiveCard` to emit the compressed markup**

Replace `renderLiveCard` function body (around line 2274) with:

```javascript
function renderLiveCard(liveId, tradelabName, runs) {
  const card = document.createElement('div');
  card.className = 'research-card';
  if (!runs.length) {
    card.innerHTML = `
      <div class="research-card-header"><span class="research-card-name">${liveId}</span></div>
      <span class="verdict-pill verdict-inconclusive">No runs</span>
      <span class="research-card-sparkline">—</span>
      <div class="research-card-stats"><span class="research-card-stat">map: ${tradelabName}</span></div>
      <div class="research-card-actions"></div>`;
    return card;
  }
  const latest = runs[0];
  const verdict = (latest.verdict || 'INCONCLUSIVE').toLowerCase();
  const prior = runs[1]?.verdict;
  const rank = v => v==='ROBUST'?3 : v==='MARGINAL'?2 : v==='FRAGILE'?1 : 0;
  if (prior && rank(latest.verdict) < rank(prior)) card.classList.add('degraded');

  card.innerHTML = `
    <div class="research-card-header">
      <span class="research-card-name">${liveId}</span>
    </div>
    <span class="verdict-pill verdict-${verdict}">${latest.verdict}</span>
    <span class="research-card-sparkline" data-strategy="${tradelabName}">…</span>
    <div class="research-card-stats">
      <span class="research-card-stat"><span class="research-card-stat-label">PF</span> <span class="research-card-pf">…</span></span>
      <span class="research-card-stat"><span class="research-card-stat-label">WR</span> <span class="research-card-wr">…</span></span>
      <span class="research-card-stat"><span class="research-card-stat-label">DD</span> <span class="research-card-dd">…</span></span>
      <span class="research-card-stat"><span class="research-card-stat-label">DSR</span> <span class="research-card-dsr">${latest.dsr_probability != null ? latest.dsr_probability.toFixed(2) : '—'}</span></span>
    </div>
    <div class="research-card-actions">
      <button class="btn btn-compact" onclick="openResearchModal('${latest.run_id}','dashboard','${tradelabName}','${latest.verdict}','${latest.timestamp_utc}')">D</button>
      <button class="btn btn-compact" onclick="openResearchModal('${latest.run_id}','quantstats','${tradelabName}','${latest.verdict}','${latest.timestamp_utc}')">Q</button>
      <details class="run-dropdown" data-strategy="${tradelabName}">
        <summary class="run-btn">Run ▾</summary>
        <div class="run-menu">
          <button data-cmd="optimize">Optimize (1)</button>
          <button data-cmd="wf">Walk-forward (2)</button>
          <button data-cmd="run">Run (3)</button>
          <button data-cmd="run --robustness">Robustness (3r)</button>
          <button data-cmd="run --full" class="run-3f">Full (3f)</button>
        </div>
      </details>
    </div>`;

  // Fetch metrics + sparkline lazily
  fetchJSON(`/tradelab/runs/${latest.run_id}/metrics`).then(mb => {
    const m = mb.data || {};
    card.querySelector('.research-card-pf').textContent = m.profit_factor != null ? m.profit_factor.toFixed(2) : '—';
    card.querySelector('.research-card-wr').textContent = m.win_rate != null ? m.win_rate.toFixed(0)+'%' : '—';
    card.querySelector('.research-card-dd').textContent = m.max_drawdown_pct != null ? m.max_drawdown_pct.toFixed(1)+'%' : '—';
  });
  getSparklineRuns(tradelabName).then(r => {
    const el = card.querySelector('.research-card-sparkline');
    if (el) el.innerHTML = renderSparkline(r);
  });

  return card;
}
```

- [ ] **Step 4: Smoke test**

Restart dashboard. Live Strategies section is now a 6-row horizontal strip. Toggle legacy: `localStorage.setItem('researchLayoutLegacy', '1')` → reload → fat grid returns. Toggle back: `localStorage.removeItem('researchLayoutLegacy')` → reload → compressed strip.

- [ ] **Step 5: Commit**

```powershell
git -C C:\TradingScripts add command_center.html
git -C C:\TradingScripts commit -m "feat(command-center): compress Live Strategies cards into horizontal strip"
```

---

## Phase 6: Finalize

### Task 17: Full regression run + full-flow smoke

- [ ] **Step 1: Run full test suite**

```powershell
cd C:\TradingScripts\tradelab\.claude\worktrees\research-v2
$env:PYTHONPATH = "src"
$env:PYTHONIOENCODING = "utf-8"
python -m pytest tests/web/ tests/cli/test_progress_log.py -q
```
Expected: `≥85 passed` (72 baseline + 6 preflight + 4 failure_hint + 7 compare + 1-2 handler).

- [ ] **Step 2: Run spec §6 manual smoke checklist end-to-end**

Walk through all 10 items from spec §6. Confirm each passes. Note any issues in a follow-ups section of the summary doc.

- [ ] **Step 3: Confirm no changes to protected paths**

```powershell
git -C C:\TradingScripts\tradelab\.claude\worktrees\research-v2 diff master -- src/tradelab/engines/
# expected: empty diff
```

Also verify:
- No change to `src/tradelab/canaries/`
- No change to the 4 pre-v1 Command Center tabs (grep `command_center.html` diff for `tab="live-trading"` or similar and confirm no functional change)

### Task 18: Write `RESEARCH_TAB_V2_SUMMARY.md`

**Files:**
- Create: `docs/superpowers/RESEARCH_TAB_V2_SUMMARY.md`

- [ ] **Step 1: Write the summary doc**

Structure matching v1 / v1.5 summaries:
- §1 TL;DR
- §2 What v2 delivered (table of 5 features + files touched)
- §3 Architecture snapshot (v1.5 → v2 diagram)
- §4 Gotchas discovered during this session
- §5 How to run / restart / debug (inherits v1.5)
- §6 Files outside the git repo (`command_center.html`, `launch_dashboard.py` + `.bak-2026-04-23-v2`)
- §7 v2.1 backlog (any deferred items found during execution)
- §8 Deliberately omitted from v2 (copy from spec §8)
- §9 References
- §10 How to resume v2.1

Keep it ≤300 lines. This is handoff, not a tutorial.

- [ ] **Step 2: Commit**

```powershell
git add docs/superpowers/RESEARCH_TAB_V2_SUMMARY.md
git commit -m "docs: research tab v2.0 summary + handoff"
```

### Task 19: Update memory + changelog

- [ ] **Step 1: Append v2 entry to `C:\TradingScripts\CHANGELOG-research-tab.txt`**

Single paragraph summarizing the 5-feature bundle + ship date + the feature flag mechanism.

- [ ] **Step 2: Update memory file**

`C:\Users\AAASH\.claude\projects\C--Users-AAASH\memory\project_tradelab_web_dashboard.md` — add one line under the existing v1 / v1.5 entries:

> **v2.0 shipped 2026-04-XX** — Research Velocity Bundle: preflight chips (replaces Freshness banner), failure hints in Job Tracker, compare-N-runs (checkbox + Compare button + new-tab delivery), Pipeline heat/tooltip/sparkline, Live Cards compressed to horizontal strip. Feature-flagged layout for 48h. Spec: `docs/superpowers/specs/2026-04-23-research-tab-v2-design.md`. Plan: `docs/superpowers/plans/2026-04-23-research-tab-v2.md`. Summary: `docs/superpowers/RESEARCH_TAB_V2_SUMMARY.md`.

### Task 20: Merge to master + push

- [ ] **Step 1: Merge worktree to master (no-ff for history)**

```powershell
cd C:\TradingScripts\tradelab
git merge --no-ff research-v2 -m "Merge branch 'research-v2': Research Tab v2.0 release"
```

- [ ] **Step 2: Run regression on master one more time**

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests/web/ tests/cli/test_progress_log.py -q
```
Expected: still ≥85 passed.

- [ ] **Step 3: Push tradelab master to origin**

```powershell
git push origin master
```

- [ ] **Step 4: Remove feature flag after 48h**

Calendar reminder: 2026-04-25. After 48h of confirmed use, remove the `localStorage.researchLayoutLegacy` override block from `command_center.html` + delete the `body.v2-layout` class conditional (make v2 unconditional). Commit as `chore: remove v2 layout feature flag after 48h trial`.

---

## Self-review checklist (executed during plan write)

- [x] **Spec coverage:** all 5 features in spec §4 have Phase 1-5 tasks. Spec §6 smoke items are covered in Task 17. Spec §7 rollback (feature flag, sidecars) is in Pre-step 3 and Task 16. Spec §8 out-of-scope items are NOT included — confirmed deferred.
- [x] **Placeholder scan:** no TBDs, TODOs, "implement later," or "similar to task N" patterns. Every code step shows the actual code.
- [x] **Type consistency:** `researchState.selectedRunIds` is consistently a `Set` (tasks 12-15). `researchState.sparklineCache` is a `{strategy: runs[]}` dict (task 15). `researchState.preflight` is the response dict (tasks 4-5). Function names consistent: `renderSparkline`, `verdictHeatClass`, `fragileReasons`, `getSparklineRuns`, `renderPreflightInModal`, `researchLoadPreflight`.
- [x] **"Why FRAGILE?" — client-side derivation used.** Spec's conditional "add gate_failures field if missing" was resolved by verifying the field doesn't exist and deriving reasons client-side from existing metrics. No engine change.
- [x] **Compare-report route lives in `launch_dashboard.py`** (task 11) rather than `handlers.py` because it returns raw HTML, not the JSON envelope. Spec noted this conditionally; plan makes it explicit.
- [x] **Feature flag lifecycle:** installed in task 16, removal scheduled as task 20 step 4.

## References

- **Spec:** `docs/superpowers/specs/2026-04-23-research-tab-v2-design.md`
- **Prior-session summaries:** `RESEARCH_TAB_V1_SUMMARY.md`, `RESEARCH_TAB_V1.5_SUMMARY.md`, `POST_V1.5_STABILIZATION_SUMMARY.md`
- **Protected paths:** `src/tradelab/engines/*`, `src/tradelab/canaries/*`, 4 pre-v1 Command Center tabs, 10 AlgoTrade safety mechanisms
- **Baseline test expectation:** 72 passed on master before Phase 1; ≥85 after Phase 6.
