# Phase 3a — Card Lifecycle (Accept + Toggle + Overview card)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Promote a tested Python strategy run into a live **card** (enable/disable toggle, verdict-stamped, **paper-mode recorded**) shown on the Overview tab — the full control surface for live trading, WITHOUT yet placing any orders.

**Architecture:** A new Python-compatible accept backend `accept_python_run` (sibling to the Pine-only `accept_scored`; no `strategy.pine`/`pine_archive` requirement, **advisory** gating instead of a hard ROBUST gate), a `POST /tradelab/strategies/accept` route, reuse of the existing `CardRegistry.set_status` for the on/off toggle, and Overview-card rendering of the new Python cards. Cards record `mode:"paper"` and `source:"python"` so the future Phase-4 execution engine runs them paper-only until the user explicitly goes live.

**Tech Stack:** `tradelab.web.approve_strategy`, `tradelab.live.cards.CardRegistry`, `tradelab.web.handlers` dispatch, vanilla JS in `command_center.html`.

**SAFETY:** Phase 3a places **NO orders**. It only creates/toggles card metadata. Real-money risk is zero here. The execution engine is Phase 4 (paper-locked).

**Verified context:** `CardRegistry(path)` has `.create(card_id, data)`, `.next_version_for(base_name)`, `.set_status(card_id, status)`, `.get`, `.all_hydrated`. The existing `/tradelab/accept` route (handlers.py:1002) calls `accept_scored` and uses helpers `_cards_path()`, `_reports_root()`. `accept_scored` raises `ActivationGateFailed` when `activate=True` and verdict≠ROBUST — we reuse that exception type as the advisory-confirm signal. A tested run folder has `backtest_result.json` (symbol, timeframe), `robustness_result.json` (`verdict.verdict`), and `validation.json`.

**Phase 3a of the 3a→4 split.** Phase 4 = the paper-locked live execution engine (its own spec).

---

### Task 1: `accept_python_run` backend

**Files:**
- Modify: `src/tradelab/web/approve_strategy.py` (add a function; reuse `ActivationGateFailed`, `_secrets`, `_datetime`, `_timezone` already imported there)
- Test: `tests/web/test_accept_python.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/web/test_accept_python.py
from pathlib import Path
import pytest
from tradelab.live.cards import CardRegistry
from tradelab.web.approve_strategy import accept_python_run, ActivationGateFailed


def _run_folder(tmp_path: Path) -> Path:
    rf = tmp_path / "reports" / "frog_2026-05-31_120000"
    rf.mkdir(parents=True)
    (rf / "backtest_result.json").write_text("{}")
    return rf


def _registry(tmp_path: Path) -> CardRegistry:
    cj = tmp_path / "cards.json"
    cj.write_text("{}")
    return CardRegistry(cj)


def test_accept_python_creates_disabled_card(tmp_path):
    rf = _run_folder(tmp_path)
    reg = _registry(tmp_path)
    card = accept_python_run(
        base_name="frog", symbol="AAPL", timeframe="1D",
        report_folder=str(rf), verdict="INCONCLUSIVE", dsr_probability=0.4,
        scoring_run_id="run-1", strategy="frog", registry=reg,
        reports_root=tmp_path / "reports", activate=False,
    )
    assert card["card_id"] == "frog-v1"
    assert card["status"] == "disabled"
    assert card["mode"] == "paper"
    assert card["source"] == "python"
    assert card["strategy"] == "frog"
    assert "secret" in card and "pine_archive_path" not in card
    assert reg.get("frog-v1") is not None


def test_accept_python_advisory_gate_blocks_non_robust_activate(tmp_path):
    rf = _run_folder(tmp_path)
    reg = _registry(tmp_path)
    with pytest.raises(ActivationGateFailed):
        accept_python_run(
            base_name="frog", symbol="AAPL", timeframe="1D",
            report_folder=str(rf), verdict="FRAGILE", dsr_probability=None,
            scoring_run_id="run-1", strategy="frog", registry=reg,
            reports_root=tmp_path / "reports", activate=True, confirm_non_robust=False,
        )


def test_accept_python_confirm_overrides_advisory_gate(tmp_path):
    rf = _run_folder(tmp_path)
    reg = _registry(tmp_path)
    card = accept_python_run(
        base_name="frog", symbol="AAPL", timeframe="1D",
        report_folder=str(rf), verdict="FRAGILE", dsr_probability=None,
        scoring_run_id="run-1", strategy="frog", registry=reg,
        reports_root=tmp_path / "reports", activate=True, confirm_non_robust=True,
    )
    assert card["status"] == "enabled"
    assert card["activated_verdict"] == "FRAGILE"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd tradelab && python -m pytest tests/web/test_accept_python.py -q`
Expected: FAIL (`cannot import name 'accept_python_run'`).

- [ ] **Step 3: Implement** — add to `src/tradelab/web/approve_strategy.py` (mirror `accept_scored`'s imports/style; NO pine requirement):

```python
def accept_python_run(
    *,
    base_name: str,
    symbol: str,
    timeframe: str,
    report_folder: str,
    verdict: str,
    dsr_probability: Optional[float],
    scoring_run_id: str,
    strategy: str,
    registry: _CardRegistry,
    reports_root: Path = Path("reports"),
    activate: bool = False,
    confirm_non_robust: bool = False,
    mode: str = "paper",
) -> dict:
    """Promote a tested Python-strategy run to a live card.

    Unlike accept_scored this requires NO strategy.pine / pine_archive. Gating is
    ADVISORY: activating a non-ROBUST verdict is allowed only when
    confirm_non_robust=True; otherwise ActivationGateFailed is raised so the UI
    can ask for explicit confirmation. Cards are created paper-mode by default.
    """
    rf = Path(report_folder).resolve()
    rr = Path(reports_root).resolve()
    try:
        rf.relative_to(rr)
    except ValueError as exc:
        raise FileNotFoundError(f"report folder {rf} is not under reports_root {rr}") from exc
    if not rf.exists() or not rf.is_dir():
        raise FileNotFoundError(f"report folder not found: {rf}")

    normalized_verdict = (verdict or "").strip().upper()
    if activate and normalized_verdict != "ROBUST" and not confirm_non_robust:
        raise ActivationGateFailed(
            f"Verdict is {normalized_verdict or 'unknown'} (not ROBUST). "
            f"Re-submit with confirm_non_robust=true to accept anyway."
        )

    version = registry.next_version_for(base_name)
    card_id = f"{base_name}-v{version}"
    created_at = _datetime.now(_timezone.utc).isoformat(timespec="seconds")
    card = {
        "card_id": card_id,
        "secret": _secrets.token_urlsafe(24),
        "symbol": symbol,
        "status": "enabled" if activate else "disabled",
        "quantity": None,
        "created_at": created_at,
        "base_name": base_name,
        "version": version,
        "timeframe": timeframe,
        "verdict": verdict,
        "dsr_probability": dsr_probability,
        "report_folder": str(rf).replace("\\", "/"),
        "scoring_run_id": scoring_run_id,
        "strategy": strategy,
        "mode": mode,
        "source": "python",
    }
    if activate:
        card["activated_at"] = created_at
        card["activated_verdict"] = normalized_verdict
    registry.create(card_id, card)
    return card
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd tradelab && python -m pytest tests/web/test_accept_python.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
cd tradelab && git add src/tradelab/web/approve_strategy.py tests/web/test_accept_python.py
git commit -m "feat(accept): Python-compatible accept_python_run (advisory gate, paper card)"
```

---

### Task 2: `POST /tradelab/strategies/accept` route

**Files:**
- Modify: `src/tradelab/web/handlers.py` (POST dispatcher, near `/tradelab/accept`)
- Test: `tests/web/test_accept_python.py` (add route cases)

- [ ] **Step 1: Write the failing test**

```python
def test_accept_route_requires_fields():
    import json
    from tradelab.web import handlers
    body, status = handlers.handle_post_with_status(
        "/tradelab/strategies/accept", json.dumps({"base_name": "frog"}).encode())
    assert status == 400
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd tradelab && python -m pytest tests/web/test_accept_python.py -q -k route`
Expected: FAIL (route not found → falls through; status not 400).

- [ ] **Step 3: Implement** — in `handle_post_with_status`, near the `/tradelab/accept` block, add:

```python
    if path == "/tradelab/strategies/accept":
        from tradelab.live.cards import CardExistsError, CardRegistry
        from tradelab.web import approve_strategy
        required = ("base_name", "symbol", "timeframe", "report_folder", "strategy")
        missing = [k for k in required if not (payload.get(k) or "").strip()]
        if missing:
            return _err(f"missing required fields: {', '.join(missing)}"), 400
        try:
            card = approve_strategy.accept_python_run(
                base_name=payload["base_name"], symbol=payload["symbol"],
                timeframe=payload["timeframe"], report_folder=payload["report_folder"],
                verdict=payload.get("verdict", "INCONCLUSIVE"),
                dsr_probability=payload.get("dsr_probability"),
                scoring_run_id=payload.get("scoring_run_id", ""),
                strategy=payload["strategy"],
                registry=CardRegistry(_cards_path()),
                reports_root=_reports_root(),
                activate=bool(payload.get("activate", False)),
                confirm_non_robust=bool(payload.get("confirm_non_robust", False)),
            )
            return _ok(card), 200
        except approve_strategy.ActivationGateFailed as e:
            return _err(str(e)), 422
        except FileNotFoundError:
            return _err("report folder not found"), 404
        except CardExistsError as e:
            return _err(f"card_id {e} already registered"), 409
        except Exception as e:
            return _err(f"accept failed: {type(e).__name__}: {e}"), 500
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd tradelab && python -m pytest tests/web/test_accept_python.py -q`
Expected: PASS (4 tests). Also `python -m pytest tests/web/ -q` → 71 pre-existing FE failures unchanged, no new.

- [ ] **Step 5: Commit**

```bash
cd tradelab && git add src/tradelab/web/handlers.py tests/web/test_accept_python.py
git commit -m "feat(accept): POST /tradelab/strategies/accept route (advisory, 422 on gate)"
```

---

### Task 3: Confirm the enable/disable toggle endpoint

**Files:** Read-only investigation + a test (and a small add only if missing).
- Test: `tests/web/test_accept_python.py` (add a toggle case)

- [ ] **Step 1: Find the existing card status toggle.** READ `handlers.py` `handle_patch_with_status` (and any `set_status` usage). The dashboard already enables/disables live cards. Identify the route (likely `PATCH /tradelab/cards/{id}` with `{status}` calling `CardRegistry.set_status`).

- [ ] **Step 2: Write a test that toggles a card created by accept_python_run** through that real endpoint (create via accept_python_run into a temp cards.json patched via the handler's `_cards_path`, then call the toggle handler, assert status flips). If NO toggle endpoint exists, add `PATCH /tradelab/cards/{id}` that validates `status ∈ {enabled,disabled}` and calls `set_status`, and test it.

- [ ] **Step 3: Run, then commit**

Run: `cd tradelab && python -m pytest tests/web/test_accept_python.py -q`
```bash
git add -A && git commit -m "test(accept): card enable/disable toggle works on python cards"
```

---

### Task 4: Frontend — Accept button + Overview card

**Files:** `command_center.html` (root repo); `tests/web/test_command_center_html.py`.

- [ ] **Step 1: READ** how the Overview live cards render (`loadOverviewLiveCards`, `/tradelab/cards`) and how an existing card's enable/disable toggle is wired in the FE. Python cards land in the same `cards.json`, so they should render via the existing path — confirm they don't break on the absent `pine_archive_path`.

- [ ] **Step 2: Write FE contract test** asserting an "Accept" affordance exists that POSTs to `/tradelab/strategies/accept`, and that the advisory confirm flow (re-POST with `confirm_non_robust`) is present:

```python
def test_accept_flow_posts_to_strategies_accept(html: str) -> None:
    assert "/tradelab/strategies/accept" in html
    assert "confirm_non_robust" in html
```

- [ ] **Step 3: Implement** an Accept control on a tested run (e.g. in the run/Validation view or the Overview "promote" affordance): POST `/tradelab/strategies/accept` with `{base_name, strategy, symbol, timeframe, report_folder, verdict, dsr_probability, scoring_run_id, activate:true}`. On `422` (advisory gate), show a confirm dialog ("Verdict is not ROBUST — accept anyway?") and re-POST with `confirm_non_robust:true`. After success, refresh the Overview cards. The new card renders with its verdict badge + the existing enable/disable toggle. Pull `symbol/timeframe/verdict/dsr/report_folder/scoring_run_id` from the run's `/tradelab/runs/{id}/...` data already available in the FE.

- [ ] **Step 4: Run tests** — new FE test passes; full FE file failure count unchanged (71 pre-existing).

- [ ] **Step 5: Commit (both repos)** — command_center.html (root), test file (tradelab).

---

## Self-review
- **Spec coverage:** advisory Accept (Component 3) → Tasks 1-2,4; on/off toggle (card authority) → Task 3; Overview card → Task 4; paper-mode recorded for Phase-4 → card `mode:"paper"`. NO order placement (correct for 3a). ✓
- **Placeholder scan:** Tasks 3-4 contain READ steps (locate the existing toggle endpoint + Overview renderer) — investigations, not placeholders; backend Tasks 1-2 ship complete code.
- **Type consistency:** card schema keys produced by `accept_python_run` (esp. `strategy`, `mode`, `source`, `scoring_run_id`) are what the Overview renderer and the future Phase-4 runner will read; the route passes exactly the `accept_python_run` kwargs.

## Phase 4 (next, paper-locked) — scope only
A scheduled runner that: loads `enabled` python cards from `cards.json`, `instantiate_strategy(card["strategy"])`, pulls fresh parquet data, runs `generate_signals`, and submits **paper** Alpaca orders via `tradelab.live.alpaca_client`, gated by the Command Center max-drawdown / `kill_switch`, refusing live unless an explicit live flag is set. Own spec + plan + heavy review.
