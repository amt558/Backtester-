# Python Strategy Import — Implementation Plan (Phase 1 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the Command Center auto-discover Python `Strategy` subclasses in `src/tradelab/strategies/` and import (register) a manually-selected one, retiring the Pine/CSV input from the UI.

**Architecture:** Pure additive backend (one discovery scanner + two routes reusing the existing `new_strategy` registration helpers), plus a frontend conversion of the existing "Score New Strategy" modal into an "Import Strategy" modal (dropdown of discoverable strategies + Import button; Pine/CSV inputs removed). No engine changes; the imported strategy becomes testable via the existing `tradelab run` path.

**Tech Stack:** Python (importlib, pydantic, typer), the existing `tradelab.web.handlers` GET/POST dispatch, `tradelab.registry`, `tradelab.web.new_strategy`, vanilla JS in `command_center.html`.

**This is Phase 1 of 3** for the Python-only lifecycle (spec: `docs/superpowers/specs/2026-05-31-python-only-strategy-lifecycle-design.md`). Phase 2 = Test + QuantStats verification. Phase 3 = Qualify/Accept toggle + Overview card + Alpaca enrollment (the Alpaca-wiring is grounded at the start of Phase 3).

---

### Task 1: Discovery scanner

**Files:**
- Modify: `tradelab/src/tradelab/web/new_strategy.py` (append a function)
- Test: `tradelab/tests/web/test_strategy_discovery.py`

- [ ] **Step 1: Write the failing test**

```python
# tradelab/tests/web/test_strategy_discovery.py
from pathlib import Path
from tradelab.web.new_strategy import discover_unregistered_strategies


def test_discovery_finds_unregistered_strategy_files(tmp_path, monkeypatch):
    # a fake strategies dir with one registered + one new strategy file
    strat = tmp_path / "tradelab" / "strategies"
    strat.mkdir(parents=True)
    (strat / "__init__.py").write_text("")
    (strat / "base.py").write_text("")  # must be skipped

    # Registered set: only s2_pocket_pivot's module is registered.
    monkeypatch.setattr(
        "tradelab.web.new_strategy.list_registered_strategies",
        lambda: {"s2_pocket_pivot": type("E", (), {
            "module": "tradelab.strategies.s2_pocket_pivot", "class_name": "S2PocketPivot"})()},
    )

    # Two real importable modules already exist in the package; discovery imports
    # by module path, so we assert against the real package, not tmp_path files.
    found = discover_unregistered_strategies()
    names = {d["suggested_name"] for d in found}
    # s2_pocket_pivot is registered -> excluded; viprasol_v83 is not -> included
    assert "s2_pocket_pivot" not in names
    assert "viprasol_v83" in names
    rec = next(d for d in found if d["suggested_name"] == "viprasol_v83")
    assert rec["class_name"] == "ViprasolV83"
    assert rec["module"] == "tradelab.strategies.viprasol_v83"
    assert rec["timeframe"] == "1D"
    assert rec["requires_benchmark"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tradelab && python -m pytest tests/web/test_strategy_discovery.py -q`
Expected: FAIL with `ImportError: cannot import name 'discover_unregistered_strategies'`.

- [ ] **Step 3: Write minimal implementation**

Append to `tradelab/src/tradelab/web/new_strategy.py`:

```python
def discover_unregistered_strategies(src_root: Optional[Path] = None) -> list[dict]:
    """Scan src/tradelab/strategies/ for Strategy subclasses whose module is not
    yet registered in tradelab.yaml. Returns one record per importable subclass.

    Records: {module, class_name, suggested_name, timeframe, requires_benchmark}.
    Files that fail to import or define no Strategy subclass are silently skipped
    (a half-written strategy must never break the scan)."""
    import importlib

    if src_root is None:
        src_root = Path("src")
    try:
        registered = list_registered_strategies()
        registered_modules = {getattr(e, "module", None) for e in registered.values()}
    except Exception:
        registered_modules = set()

    strat_dir = src_root / "tradelab" / "strategies"
    out: list[dict] = []
    if not strat_dir.is_dir():
        return out
    for py in sorted(strat_dir.glob("*.py")):
        if py.name in ("__init__.py", "base.py"):
            continue
        module_path = f"tradelab.strategies.{py.stem}"
        if module_path in registered_modules:
            continue
        try:
            mod = importlib.import_module(module_path)
        except Exception:
            continue
        for v in vars(mod).values():
            if (isinstance(v, type) and issubclass(v, Strategy)
                    and v is not Strategy and v.__module__ == module_path):
                out.append({
                    "module": module_path,
                    "class_name": v.__name__,
                    "suggested_name": py.stem,
                    "timeframe": getattr(v, "timeframe", "1D"),
                    "requires_benchmark": bool(getattr(v, "requires_benchmark", False)),
                })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tradelab && python -m pytest tests/web/test_strategy_discovery.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd tradelab && git add src/tradelab/web/new_strategy.py tests/web/test_strategy_discovery.py
git commit -m "feat(import): discover unregistered Python strategies in strategies/"
```

---

### Task 2: Import (register a discovered strategy)

**Files:**
- Modify: `tradelab/src/tradelab/web/new_strategy.py` (append a function)
- Test: `tradelab/tests/web/test_strategy_discovery.py` (add cases)

- [ ] **Step 1: Write the failing test**

```python
def test_import_discovered_appends_yaml_entry(tmp_path, monkeypatch):
    from tradelab.web.new_strategy import import_discovered
    yaml = tmp_path / "tradelab.yaml"
    yaml.write_text("strategies:\n  s2_pocket_pivot:\n    module: tradelab.strategies.s2_pocket_pivot\n    class_name: S2PocketPivot\n    params: {}\n")
    monkeypatch.setattr("tradelab.web.new_strategy._is_registered", lambda n: False)

    res = import_discovered("viprasol_v83", "ViprasolV83", yaml_path=yaml)
    assert res["error"] is None and res["registered"] is True
    text = yaml.read_text()
    assert "  viprasol_v83:" in text
    assert "module: tradelab.strategies.viprasol_v83" in text
    assert "class_name: ViprasolV83" in text


def test_import_discovered_rejects_duplicate(tmp_path, monkeypatch):
    from tradelab.web.new_strategy import import_discovered
    yaml = tmp_path / "tradelab.yaml"
    yaml.write_text("strategies:\n")
    monkeypatch.setattr("tradelab.web.new_strategy._is_registered", lambda n: True)
    res = import_discovered("s2_pocket_pivot", "S2PocketPivot", yaml_path=yaml)
    assert res["error"] is not None and res["registered"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tradelab && python -m pytest tests/web/test_strategy_discovery.py -q`
Expected: FAIL with `ImportError: cannot import name 'import_discovered'`.

- [ ] **Step 3: Write minimal implementation**

Append to `tradelab/src/tradelab/web/new_strategy.py`. The file already lives in
`strategies/`, so this only writes the yaml entry (reusing `_append_strategy_to_yaml`).
The registry name is the file stem, so the existing helper's
`module: tradelab.strategies.{name}` is correct.

```python
def import_discovered(
    name: str,
    class_name: str,
    yaml_path: Optional[Path] = None,
) -> dict:
    """Register an already-on-disk discovered strategy by appending its
    tradelab.yaml entry. `name` MUST equal the file stem (module is
    tradelab.strategies.<name>). Idempotent; refuses an already-registered name."""
    name = _normalize_name(name)
    if _is_registered(name):
        return {"error": f"'{name}' is already registered", "registered": False}
    if yaml_path is None:
        yaml_path = Path("tradelab.yaml")
    _append_strategy_to_yaml(yaml_path, name, class_name)
    return {"error": None, "registered": True, "name": name}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tradelab && python -m pytest tests/web/test_strategy_discovery.py -q`
Expected: PASS (all 3 tests).

- [ ] **Step 5: Commit**

```bash
cd tradelab && git add src/tradelab/web/new_strategy.py tests/web/test_strategy_discovery.py
git commit -m "feat(import): register a discovered strategy via tradelab.yaml"
```

---

### Task 3: HTTP routes (discoverable + import)

**Files:**
- Modify: `tradelab/src/tradelab/web/handlers.py` (GET dispatcher + POST dispatcher)
- Test: `tradelab/tests/web/test_strategy_discovery.py` (add route cases)

- [ ] **Step 1: Write the failing test**

```python
def test_discoverable_route_returns_records():
    import json
    from tradelab.web import handlers
    body, status = handlers.handle_get_with_status("/tradelab/strategies/discoverable")
    assert status == 200
    data = json.loads(body)["data"]
    assert "strategies" in data and isinstance(data["strategies"], list)


def test_import_route_rejects_missing_fields():
    import json
    from tradelab.web import handlers
    body, status = handlers.handle_post_with_status(
        "/tradelab/strategies/import", json.dumps({"name": "x"}).encode())
    assert status == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tradelab && python -m pytest tests/web/test_strategy_discovery.py -q -k route`
Expected: FAIL (routes return 404 / not found).

- [ ] **Step 3: Write minimal implementation**

In `handlers.py`, in the GET dispatcher (`handle_get_with_status`), add near the other
`/tradelab/strategies` matchers:

```python
    if path == "/tradelab/strategies/discoverable":
        from ..web.new_strategy import discover_unregistered_strategies
        try:
            return _ok({"strategies": discover_unregistered_strategies()}), 200
        except Exception as e:
            return _err(f"discovery failed: {type(e).__name__}: {e}"), 500
```

In the POST dispatcher (`handle_post_with_status`), add:

```python
    if path == "/tradelab/strategies/import":
        from ..web.new_strategy import import_discovered
        try:
            payload = json.loads(body or b"{}")
        except json.JSONDecodeError:
            return _err("invalid JSON body"), 400
        name = (payload.get("name") or "").strip()
        class_name = (payload.get("class_name") or "").strip()
        if not name or not class_name:
            return _err("name and class_name are required"), 400
        res = import_discovered(name, class_name)
        if res.get("error"):
            return _err(res["error"]), 409
        return _ok(res), 200
```

(Confirm the POST dispatcher's body parameter name by reading the function signature
in `handlers.py`; use whatever it binds the request body to — likely `body`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tradelab && python -m pytest tests/web/test_strategy_discovery.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd tradelab && git add src/tradelab/web/handlers.py tests/web/test_strategy_discovery.py
git commit -m "feat(import): /tradelab/strategies/discoverable + /import routes"
```

---

### Task 4: Frontend — convert the Score modal into an Import modal

**Files:**
- Modify: `command_center.html` (root repo) — modal HTML at ~1568-1600, the score
  submit/register JS (`onNsRegister`, score CSV/Pine handlers ~5042-5110, 5345-5400),
  and the modal-open trigger.
- Test: `tradelab/tests/web/test_command_center_html.py` (add Import-modal asserts)

- [ ] **Step 1: Write the failing test**

```python
def test_import_modal_has_discovery_dropdown_and_no_pine_csv(html: str) -> None:
    # The new Import modal exposes a discovery <select> + Import button.
    assert 'id="importStrategySelect"' in html
    assert 'id="importStrategyBtn"' in html
    assert "/tradelab/strategies/discoverable" in html
    assert "/tradelab/strategies/import" in html
    # Pine/CSV inputs are gone from the import flow.
    assert 'id="scorePineFileInput"' not in html
    assert 'id="scoreCsvFileInput"' not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tradelab && python -m pytest tests/web/test_command_center_html.py -q -k import_modal`
Expected: FAIL (ids absent; Pine/CSV ids still present).

- [ ] **Step 3: Write minimal implementation**

Replace the body of the `scoreModal` dialog (the `.settings-label` blocks for CSV +
Pine inputs at ~1573-1600) with an Import body. Keep the modal shell/overlay:

```html
        <label class="settings-label">Discovered Python strategies</label>
        <div class="settings-row">
          <select id="importStrategySelect" class="settings-input" style="flex:1;">
            <option value="">Scanning src/tradelab/strategies/ …</option>
          </select>
          <button id="importRefreshBtn" class="btn" type="button" title="Re-scan">↻</button>
        </div>
        <div id="importStrategyMeta" style="font-size:11px;color:var(--text3);margin-top:6px;"></div>
        <div class="settings-row" style="margin-top:10px;">
          <button id="importStrategyBtn" class="btn primary" type="button">Import</button>
        </div>
        <div id="importStrategyStatus" style="font-size:11px;margin-top:8px;"></div>
```

Add JS (near the old score handlers; delete the CSV/Pine handler functions
`onScoreSubmit`/pine-lint/`onNsRegister` Pine path that referenced the removed ids):

```javascript
    async function loadDiscoverableStrategies() {
      const sel = document.getElementById('importStrategySelect');
      const meta = document.getElementById('importStrategyMeta');
      sel.innerHTML = '<option value="">Scanning…</option>';
      try {
        const r = await fetch('/tradelab/strategies/discoverable');
        const env = await r.json();
        const list = (env.data && env.data.strategies) || [];
        if (!list.length) {
          sel.innerHTML = '<option value="">No new strategies in src/tradelab/strategies/</option>';
          meta.textContent = '';
          return;
        }
        sel.innerHTML = list.map(s =>
          `<option value="${_esc(s.suggested_name)}" data-class="${_esc(s.class_name)}" `
          + `data-tf="${_esc(s.timeframe)}" data-bench="${s.requires_benchmark}">`
          + `${_esc(s.suggested_name)} (${_esc(s.class_name)})</option>`).join('');
        sel.onchange = () => {
          const o = sel.selectedOptions[0];
          meta.textContent = o ? `${o.dataset.class} · ${o.dataset.tf}`
            + (o.dataset.bench === 'true' ? ' · needs SPY benchmark' : '') : '';
        };
        sel.onchange();
      } catch (e) {
        sel.innerHTML = `<option value="">Discovery failed: ${_esc(e.message || e)}</option>`;
      }
    }

    async function onImportStrategy() {
      const sel = document.getElementById('importStrategySelect');
      const status = document.getElementById('importStrategyStatus');
      const o = sel.selectedOptions[0];
      if (!o || !o.value) { status.textContent = 'Pick a strategy first.'; return; }
      status.textContent = 'Importing…';
      try {
        const r = await fetch('/tradelab/strategies/import', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({name: o.value, class_name: o.dataset.class}),
        });
        const env = await r.json();
        if (!r.ok || env.error) throw new Error(env.error || ('HTTP ' + r.status));
        status.innerHTML = `<span style="color:var(--green)">Imported ${_esc(o.value)} — now testable.</span>`;
        loadDiscoverableStrategies();
      } catch (e) {
        status.innerHTML = `<span style="color:var(--red)">${_esc(e.message || e)}</span>`;
      }
    }
```

Wire on DOM-ready (next to the existing `signalsCloseBtn` wiring):

```javascript
    document.getElementById('importStrategyBtn').addEventListener('click', onImportStrategy);
    document.getElementById('importRefreshBtn').addEventListener('click', loadDiscoverableStrategies);
```

And call `loadDiscoverableStrategies()` in the score-modal open handler (rename its
title to "Import Strategy").

- [ ] **Step 4: Run tests**

Run: `cd tradelab && python -m pytest tests/web/test_command_center_html.py -q -k import_modal`
Expected: PASS. Then run the full FE file and confirm the **pre-existing** V3 Task14/15
failures are unchanged (no NEW failures introduced):
`python -m pytest tests/web/test_command_center_html.py -q` → same failure count as before this task.

- [ ] **Step 5: Commit (root repo for command_center.html)**

```bash
cd C:/TradingScripts && git add command_center.html
git -C C:/TradingScripts/tradelab add tests/web/test_command_center_html.py
git commit -m "feat(import): Import Strategy modal (discovery dropdown), retire Pine/CSV inputs"
git -C C:/TradingScripts/tradelab commit -m "test(import): assert Import modal + no Pine/CSV inputs"
```

---

### Task 5: Unwire the Pine/CSV entry points + inbox watcher from the UI

**Files:**
- Modify: `command_center.html` — remove/redirect the buttons/menu items that opened
  the old CSV-paste / Pine-score flows so the only "add strategy" path is Import.
- (Do NOT delete `csv_scoring.py`, the inbox watcher, or `/tradelab/new-strategy`;
  they stay in the repo, just unreachable from the dashboard.)

- [ ] **Step 1: Write the failing test**

```python
def test_no_pine_or_csv_score_triggers_in_ui(html: str) -> None:
    # the score-by-CSV/Pine openers are gone; only Import remains
    assert "scoreCsvTextarea" not in html
    assert "scorePineTextarea" not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tradelab && python -m pytest tests/web/test_command_center_html.py -q -k pine_or_csv`
Expected: FAIL (textarea ids still present).

- [ ] **Step 3: Remove the Pine/CSV textareas + their handlers**

Delete the `scoreCsvTextarea` / `scorePineTextarea` elements and the JS functions that
read them (the CSV-paste submit + Pine-lint). Repoint the modal-open button to call
`loadDiscoverableStrategies()` only.

- [ ] **Step 4: Run tests**

Run: `cd tradelab && python -m pytest tests/web/test_command_center_html.py -q -k "pine_or_csv or import_modal"`
Expected: PASS. Full-file failure count unchanged vs the pre-existing V3 baseline.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts && git add command_center.html
git -C C:/TradingScripts/tradelab add tests/web/test_command_center_html.py
git commit -m "refactor(import): remove Pine/CSV UI entry points (machinery kept in repo)"
git -C C:/TradingScripts/tradelab commit -m "test(import): assert Pine/CSV UI entry points removed"
```

---

## Self-review

- **Spec coverage:** Component 1 (Import: Method A + discovery C) → Tasks 1-5. ✓
  Components 2-5 (Test, Qualify/Accept, Overview/Alpaca, QuantStats) are **Phases 2-3**,
  intentionally out of this plan.
- **Placeholder scan:** one explicit verify step (confirm the POST body param name in
  `handlers.py`) — a read, not a placeholder; all code blocks are complete.
- **Type consistency:** `discover_unregistered_strategies` record keys
  (`module/class_name/suggested_name/timeframe/requires_benchmark`) are consumed
  verbatim by the route and the FE dropdown; `import_discovered(name, class_name)`
  signature matches the route call and the FE POST body.

## Notes for Phases 2-3
- Phase 2 (Test + QuantStats): reuse the existing run trigger; add a QuantStats
  tearsheet regression. Small.
- Phase 3 (Qualify/Accept/Overview/Alpaca): **must begin by reading
  `alpaca_trading_bot.py` + `tradelab/live/` + the `/tradelab/cards` renderer** to
  ground the live-roster enrollment contract before any wiring. Paper-default,
  kill-switch-protected, advisory gating per the spec.
