# Option H Session 3a — Dashboard Card Approval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the "Score New Strategy" authoring flow in the Research tab: paste a TradingView "List of trades" CSV + Pine source, click Score to get a verdict, click Accept to create an immutable `disabled` card in `cards.json` with a `pine_archive/` record. No lifecycle UI (toggle/delete/flatten) — that ships in 3b.

**Architecture:** Two new HTTP endpoints on the existing dashboard (`POST /tradelab/score`, `POST /tradelab/accept`) wrap the Session 2 `csv_scoring` orchestrator plus a small `CardRegistry.create` extension. Frontend is a single modal in `command_center.html`. State lives in the browser between Score and Accept; server is stateless across requests. Every card is born `disabled`; 3a intentionally has no code path to enable one.

**Tech Stack:** Python 3.13, FastAPI, pydantic v2, pytest. Frontend is plain HTML/JS in `command_center.html` (no framework).

**Pre-flight:**
- Tree should be clean at the start. Recommended: `git switch -c feat/session-3a` before Task 1.
- Set `PYTHONPATH=src` and `PYTHONIOENCODING=utf-8` in your shell for every test run (Windows console + tradelab convention).
- **Spec reference:** `docs/superpowers/specs/2026-04-24-option-h-session-3a-dashboard-card-approval-design.md`. Read it first.
- **Reference memory:** `feedback_plan_grep_verification.md` — every selector/signature in this plan was verified against master `eb39aaf` before writing, but re-verify if time has passed before starting.
- **Sibling repo:** `C:/TradingScripts/command_center.html` and `C:/TradingScripts/launch_dashboard.py` live in a separate (local-only) git repo, not in the tradelab repo. The Task 6 commit happens in that repo, not tradelab.

---

## File structure

| Path | Responsibility |
|---|---|
| Modify: `src/tradelab/csv_scoring.py` | Extend `write_report_folder` to return `(folder, audit_run_id)`; surface `record_run`'s return value so the dashboard can link back to the audit row. |
| Modify: `src/tradelab/cli_score.py` | Update the single call site of `write_report_folder` to unpack the new tuple. |
| Modify: `src/tradelab/live/cards.py` | Add `CardExistsError`, `next_version_for`, `create` (with atomic tmp+replace write and status="disabled" safety assertion). |
| Create: `src/tradelab/web/approve_strategy.py` | Pure functions `score_csv` and `accept_scored`. Directly testable. No HTTP. |
| Modify: `src/tradelab/web/handlers.py` | Two new route branches in `handle_post_with_status`: `POST /tradelab/score`, `POST /tradelab/accept`, with input validation and HTTP code mapping. |
| Modify: `.gitignore` | Ignore `pine_archive/` runtime data. |
| Create: `tests/live/__init__.py` | Empty (new test subpackage). |
| Create: `tests/live/test_cards_create.py` | Unit tests for `CardRegistry.create`, `next_version_for`, `CardExistsError`, atomic write behavior. |
| Create: `tests/web/test_approve_strategy.py` | Unit tests for `score_csv` and `accept_scored` (uses real fixtures, real csv_scoring, real audit DB in tmp). |
| Create: `tests/web/test_handlers_approve.py` | Handler-level tests for `POST /tradelab/score` and `POST /tradelab/accept` — validates request shape, error codes, envelope format. |
| Modify (separate repo): `C:/TradingScripts/command_center.html` | Add "Score New Strategy" button, modal, JS state, event handlers. |

### Why these splits

- `csv_scoring.write_report_folder` already owns the audit write. Making it return the run_id is the smallest possible change; the alternative (duplicating the audit call in `approve_strategy`) would violate DRY.
- `approve_strategy.py` is a new module, not an extension of `new_strategy.py`, because the two flows have different inputs (CSV+Pine vs Python code) and different outputs (cards.json vs strategies registry). Keeping them separate means a future change to either doesn't risk breaking the other.
- `cards.py` stays the sole writer to `cards.json`. `approve_strategy` goes through it; no bypass writes.
- Handlers stay thin — validation and routing only. All real logic is in `approve_strategy`.

---

## Reference: the moving parts

### `csv_scoring.write_report_folder` — current signature (before Task 1)

```python
# src/tradelab/csv_scoring.py:149
def write_report_folder(
    out: CSVScoringOutput,
    *,
    base_name: str,
    out_root: Path = Path("reports"),
    pine_source: Optional[str] = None,
    csv_text: Optional[str] = None,
    record_audit: bool = True,
    db_path: Path = _DEFAULT_DB_PATH,
) -> Path:
    # ... calls _audit_record_run(...) but discards the returned run_id ...
    return folder
```

`audit.history.record_run` returns `str` (uuid4 run_id — `src/tradelab/audit/history.py:91`). We want that id on the wire.

### `CardRegistry` — current shape (before Task 2)

```python
# src/tradelab/live/cards.py
class CardRegistry:
    def __init__(self, path: Path): ...
    def reload(self) -> None: ...
    def get(self, card_id: str) -> Optional[dict]: ...
    def all(self) -> dict[str, dict]: ...
    def count(self) -> int: ...
```

Read-only surface. Task 2 adds `create`, `next_version_for`, `CardExistsError` without touching existing methods.

### `handle_post_with_status` — current routing (before Task 5)

```python
# src/tradelab/web/handlers.py:340
def handle_post_with_status(path: str, body: bytes) -> Tuple[str, int]:
    try:
        payload = json.loads(body.decode()) if body else {}
    except json.JSONDecodeError:
        return _err("invalid JSON body"), 400

    if path == "/tradelab/jobs":
        return _post_job(payload)

    if path.startswith("/tradelab/jobs/") and path.endswith("/cancel"):
        ...

    if path == "/tradelab/compare":
        ...

    # Fallback to legacy POST dispatcher
    return handle_post(path, body), 200
```

Task 5 adds `POST /tradelab/score` and `POST /tradelab/accept` as new branches before the fallback.

### `cards.json` — current entries (for reference only)

```json
{
  "test-amzn-v1":       {"secret":"...","symbol":"AMZN","status":"enabled","quantity":1},
  "test-amzn-disabled": {"secret":"...","symbol":"AMZN","status":"disabled","quantity":1},
  "smoke-test-v1":      {"secret":"...","symbol":"AMZN","status":"enabled","quantity":1}
}
```

Receiver required fields: `secret`, `symbol`, `status`, optional `quantity`. Task 4 adds more keys (`card_id`, `base_name`, `version`, `verdict`, etc.) that the receiver ignores.

---

## Task 1: Extend `write_report_folder` to return audit run_id

**Files:**
- Modify: `src/tradelab/csv_scoring.py:149-220`
- Modify: `src/tradelab/cli_score.py:68-71`
- Test: `tests/test_csv_scoring.py` (extend existing file)

- [ ] **Step 1: Look at the existing test file to find a happy-path test you can extend**

Read `tests/test_csv_scoring.py` fully. Find a test that calls `write_report_folder(...)` and asserts on the returned folder. We'll extend that test to assert on the new tuple, then add one more test specifically for the `record_audit=False` path.

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_csv_scoring.py`:

```python
def test_write_report_folder_returns_audit_run_id(tmp_path: Path):
    """With record_audit=True, write_report_folder returns (folder, run_id).
    run_id must be a non-empty str (uuid4 from audit.record_run)."""
    from tradelab.csv_scoring import score_trades, write_report_folder
    from tradelab.io.tv_csv import parse_tv_trades_csv
    fixture = Path("tests/io/fixtures/tv_export_amzn_smoke.csv")
    csv_text = fixture.read_text(encoding="utf-8-sig")
    parsed = parse_tv_trades_csv(csv_text, symbol="AMZN")
    out = score_trades(parsed, strategy_name="t1", symbol="AMZN")

    # Temporary audit DB; schema seeded by record_run on first insert via _connect.
    db_path = tmp_path / "audit.db"
    result = write_report_folder(
        out, base_name="t1", out_root=tmp_path / "reports",
        csv_text=csv_text, record_audit=True, db_path=db_path,
    )

    # Must be a 2-tuple now, not a bare Path.
    assert isinstance(result, tuple) and len(result) == 2
    folder, run_id = result
    assert folder.exists() and folder.is_dir()
    assert isinstance(run_id, str) and len(run_id) > 0


def test_write_report_folder_no_audit_returns_none_run_id(tmp_path: Path):
    """With record_audit=False, run_id must be None."""
    from tradelab.csv_scoring import score_trades, write_report_folder
    from tradelab.io.tv_csv import parse_tv_trades_csv
    fixture = Path("tests/io/fixtures/tv_export_amzn_smoke.csv")
    csv_text = fixture.read_text(encoding="utf-8-sig")
    parsed = parse_tv_trades_csv(csv_text, symbol="AMZN")
    out = score_trades(parsed, strategy_name="t2", symbol="AMZN")

    folder, run_id = write_report_folder(
        out, base_name="t2", out_root=tmp_path / "reports",
        csv_text=csv_text, record_audit=False,
    )
    assert folder.exists()
    assert run_id is None
```

If an existing test in the file calls `write_report_folder(...)` and does `folder = write_report_folder(...)` (bare Path), change it now to `folder, _ = write_report_folder(...)` so the existing test doesn't fail for the wrong reason.

- [ ] **Step 3: Run the tests and verify they fail**

```
pytest tests/test_csv_scoring.py::test_write_report_folder_returns_audit_run_id tests/test_csv_scoring.py::test_write_report_folder_no_audit_returns_none_run_id -v
```

Expected: both FAIL — the new ones fail on the tuple assertion (function still returns bare `Path`).

- [ ] **Step 4: Change `write_report_folder` to return the tuple**

In `src/tradelab/csv_scoring.py:149-220`, change the signature's return annotation and wire through the run_id:

```python
def write_report_folder(
    out: CSVScoringOutput,
    *,
    base_name: str,
    out_root: Path = Path("reports"),
    pine_source: Optional[str] = None,
    csv_text: Optional[str] = None,
    record_audit: bool = True,
    db_path: Path = _DEFAULT_DB_PATH,
) -> tuple[Path, Optional[str]]:
    """Persist a full report folder under <out_root>/<base_name>_<timestamp>/.

    Returns (folder_path, audit_run_id). audit_run_id is the audit DB row id
    when record_audit=True, else None.
    """
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    folder = Path(out_root) / f"{base_name}_{ts}"
    folder.mkdir(parents=True, exist_ok=True)

    bt = out.backtest_result.model_copy(update={"strategy": base_name})

    report_path = generate_executive_report(
        bt, optuna_result=None, wf_result=None,
        universe=None, out_dir=folder, robustness_result=None,
    )

    dashboard_path = _safe_dashboard(
        CSVScoringOutput(
            backtest_result=bt,
            dsr_probability=out.dsr_probability,
            monte_carlo=out.monte_carlo,
            verdict=out.verdict,
        ),
        folder,
    )

    (folder / "backtest_result.json").write_text(
        bt.model_dump_json(indent=2), encoding="utf-8",
    )

    if csv_text is not None:
        (folder / "tv_trades.csv").write_text(csv_text, encoding="utf-8")
    if pine_source is not None:
        (folder / "strategy.pine").write_text(pine_source, encoding="utf-8")

    audit_run_id: Optional[str] = None
    if record_audit:
        audit_run_id = _audit_record_run(
            strategy_name=base_name,
            verdict=out.verdict.verdict,
            dsr_probability=out.dsr_probability,
            input_data_hash=None,
            config_hash=hash_config({
                "csv_source": "tv_strategy_tester",
                "symbol": bt.symbol,
                "timeframe": bt.timeframe,
                "starting_equity": round(bt.metrics.final_equity - bt.metrics.net_pnl, 2),
                "n_trades": bt.metrics.total_trades,
            }),
            report_card_markdown=report_path.read_text(encoding="utf-8"),
            report_card_html_path=str(dashboard_path) if dashboard_path else None,
            db_path=db_path,
        )

    return folder, audit_run_id
```

- [ ] **Step 5: Update the CLI caller**

In `src/tradelab/cli_score.py` around line 68-71, change:

```python
folder = write_report_folder(
    out, base_name=name, pine_source=pine_source,
    csv_text=csv_text, record_audit=audit,
)
```

to:

```python
folder, _run_id = write_report_folder(
    out, base_name=name, pine_source=pine_source,
    csv_text=csv_text, record_audit=audit,
)
```

(No other callers — verified by grep on master `eb39aaf`. Re-verify with `grep -rn write_report_folder src/ tests/` before committing if any time has passed.)

- [ ] **Step 6: Run the full test suite to confirm no regressions**

```
pytest tests/ -q
```

Expected: 2 new passes added to the baseline (339 passed → 341 passed). 3 pre-existing failures unchanged.

- [ ] **Step 7: Commit**

```
git add src/tradelab/csv_scoring.py src/tradelab/cli_score.py tests/test_csv_scoring.py
git commit -m "refactor(csv_scoring): return (folder, audit_run_id) from write_report_folder

Dashboard approval flow needs the audit run_id to link the Score
response back to the DB row. record_run already returns it; just
surface it through write_report_folder. Single call site
(cli_score.py) updated in the same commit."
```

---

## Task 2: `CardRegistry.create` + `next_version_for` + `CardExistsError`

**Files:**
- Modify: `src/tradelab/live/cards.py`
- Create: `tests/live/__init__.py`
- Create: `tests/live/test_cards_create.py`

- [ ] **Step 1: Create the test package marker**

```
# tests/live/__init__.py
```

(Empty file. Required so pytest discovers the subpackage.)

- [ ] **Step 2: Write the failing tests**

Create `tests/live/test_cards_create.py`:

```python
"""CardRegistry.create / next_version_for / CardExistsError."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tradelab.live.cards import CardExistsError, CardRegistry


DISABLED_CARD = {
    "card_id": "foo-v1", "secret": "s" * 32, "symbol": "AMZN",
    "status": "disabled", "quantity": None,
}


def test_create_appends_and_persists(tmp_path: Path):
    path = tmp_path / "cards.json"
    reg = CardRegistry(path)
    reg.create("foo-v1", DISABLED_CARD)

    # In-memory
    assert reg.get("foo-v1") == DISABLED_CARD

    # Persisted to disk
    on_disk = json.loads(path.read_text(encoding="utf-8-sig"))
    assert on_disk == {"foo-v1": DISABLED_CARD}


def test_create_duplicate_raises(tmp_path: Path):
    path = tmp_path / "cards.json"
    reg = CardRegistry(path)
    reg.create("foo-v1", DISABLED_CARD)
    with pytest.raises(CardExistsError):
        reg.create("foo-v1", DISABLED_CARD)


def test_create_rejects_enabled_status(tmp_path: Path):
    path = tmp_path / "cards.json"
    reg = CardRegistry(path)
    enabled = dict(DISABLED_CARD, status="enabled")
    with pytest.raises(ValueError, match="disabled"):
        reg.create("foo-v1", enabled)


def test_next_version_for_empty_registry(tmp_path: Path):
    reg = CardRegistry(tmp_path / "cards.json")
    assert reg.next_version_for("viprasol-amzn") == 1


def test_next_version_for_with_existing_versions(tmp_path: Path):
    path = tmp_path / "cards.json"
    reg = CardRegistry(path)
    reg.create("viprasol-amzn-v1", dict(DISABLED_CARD, card_id="viprasol-amzn-v1"))
    reg.create("viprasol-amzn-v2", dict(DISABLED_CARD, card_id="viprasol-amzn-v2"))
    reg.create("other-v1", dict(DISABLED_CARD, card_id="other-v1"))
    assert reg.next_version_for("viprasol-amzn") == 3
    assert reg.next_version_for("other") == 2
    assert reg.next_version_for("unseen") == 1


def test_next_version_for_ignores_suffix_collisions(tmp_path: Path):
    """viprasol-amz-v1 must not be counted under base_name 'viprasol'."""
    path = tmp_path / "cards.json"
    reg = CardRegistry(path)
    reg.create("viprasol-v1", dict(DISABLED_CARD, card_id="viprasol-v1"))
    reg.create("viprasol-amz-v1", dict(DISABLED_CARD, card_id="viprasol-amz-v1"))
    assert reg.next_version_for("viprasol") == 2
    assert reg.next_version_for("viprasol-amz") == 2


def test_create_atomic_write_on_replace_failure(tmp_path: Path, monkeypatch):
    """If os.replace fails mid-write, the existing cards.json must be untouched."""
    import os as os_mod
    path = tmp_path / "cards.json"
    reg = CardRegistry(path)
    reg.create("foo-v1", DISABLED_CARD)
    first_contents = path.read_text(encoding="utf-8-sig")

    # Monkeypatch os.replace to raise on the second create
    def failing_replace(*args, **kwargs):
        raise OSError("simulated filesystem error")
    monkeypatch.setattr(os_mod, "replace", failing_replace)

    with pytest.raises(OSError):
        reg.create("bar-v1", dict(DISABLED_CARD, card_id="bar-v1"))

    # cards.json unchanged on disk
    assert path.read_text(encoding="utf-8-sig") == first_contents
    # .tmp file may or may not exist; don't assert on it either way
```

- [ ] **Step 3: Run the failing tests**

```
pytest tests/live/test_cards_create.py -v
```

Expected: all FAIL with `AttributeError` / `ImportError` — none of the symbols exist yet.

- [ ] **Step 4: Extend `src/tradelab/live/cards.py`**

Replace the full contents of `src/tradelab/live/cards.py` with:

```python
"""Card registry — JSON-backed, thread-safe for read.

One card = one immutable strategy version × one symbol. Live trade execution
is gated by card lookup + secret validation.

Session 3a adds mutation surface: create (append-only, disabled-by-default)
+ next_version_for (for -v{n} auto-versioning). No update/delete in 3a.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from threading import RLock
from typing import Optional


class CardExistsError(Exception):
    """Raised by CardRegistry.create when card_id is already present."""


class CardRegistry:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = RLock()
        self._cards: dict[str, dict] = {}
        self.reload()

    def reload(self) -> None:
        with self._lock:
            if self.path.exists():
                self._cards = json.loads(self.path.read_text(encoding="utf-8-sig"))
            else:
                self._cards = {}

    def get(self, card_id: str) -> Optional[dict]:
        with self._lock:
            return self._cards.get(card_id)

    def all(self) -> dict[str, dict]:
        with self._lock:
            return dict(self._cards)

    def count(self) -> int:
        with self._lock:
            return len(self._cards)

    def next_version_for(self, base_name: str) -> int:
        """Return n such that {base_name}-v{n} is the next unused id.

        Matches strictly: base_name followed by '-v' followed by digits to end.
        base_name='viprasol' does NOT collide with 'viprasol-amz-v1'.
        """
        pattern = re.compile(rf"^{re.escape(base_name)}-v(\d+)$")
        with self._lock:
            versions = []
            for cid in self._cards:
                m = pattern.match(cid)
                if m:
                    versions.append(int(m.group(1)))
            return (max(versions) + 1) if versions else 1

    def create(self, card_id: str, data: dict) -> None:
        """Append a new card. Raises CardExistsError on duplicate.

        Safety guardrail for Session 3a: every created card must have
        status='disabled'. Lifecycle (enable/disable/delete) is Session 3b
        — remove this assertion when the toggle endpoint ships.
        """
        if data.get("status") != "disabled":
            raise ValueError(
                f"Session 3a safety: new cards must have status='disabled', "
                f"got {data.get('status')!r}"
            )
        with self._lock:
            if card_id in self._cards:
                raise CardExistsError(card_id)
            new_cards = dict(self._cards)
            new_cards[card_id] = data
            self._persist(new_cards)
            self._cards = new_cards

    def _persist(self, cards: dict[str, dict]) -> None:
        """Atomic write: JSON -> .tmp -> os.replace(cards.json)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(cards, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
```

- [ ] **Step 5: Run the tests — all should pass now**

```
pytest tests/live/test_cards_create.py -v
```

Expected: 7 PASSED.

- [ ] **Step 6: Run the full suite — no regressions**

```
pytest tests/ -q
```

Expected: baseline + 2 (Task 1) + 7 (Task 2) = 348 passed, 3 pre-existing failures unchanged.

- [ ] **Step 7: Commit**

```
git add src/tradelab/live/cards.py tests/live/__init__.py tests/live/test_cards_create.py
git commit -m "feat(live/cards): add CardRegistry.create, next_version_for, CardExistsError

Append-only mutation surface for Session 3a authoring flow. Cards born
disabled (safety assertion); toggle + delete land in 3b. Atomic write
via tmp+os.replace. Strict version regex so 'viprasol-amz-v1' doesn't
collide with 'viprasol' base name."
```

---

## Task 3: `approve_strategy.score_csv` (pure function)

**Files:**
- Create: `src/tradelab/web/approve_strategy.py`
- Create: `tests/web/test_approve_strategy.py`

- [ ] **Step 1: Write the failing tests for score_csv**

Create `tests/web/test_approve_strategy.py`:

```python
"""Unit tests for approve_strategy.score_csv and accept_scored."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tradelab.io.tv_csv import TVCSVParseError
from tradelab.web import approve_strategy


@pytest.fixture
def smoke_csv_text() -> str:
    return Path("tests/io/fixtures/tv_export_amzn_smoke.csv").read_text(encoding="utf-8-sig")


def test_score_csv_happy(tmp_path: Path, smoke_csv_text: str):
    """Happy-path: valid CSV scores, writes report folder + audit row."""
    db_path = tmp_path / "audit.db"
    result = approve_strategy.score_csv(
        csv_text=smoke_csv_text,
        pine_source="// pine stub",
        symbol="AMZN",
        base_name="smoke-amzn",
        timeframe="1H",
        reports_root=tmp_path / "reports",
        db_path=db_path,
    )
    # Contract: returns a dict with the keys the frontend needs.
    for key in (
        "verdict", "metrics", "report_folder", "scoring_run_id",
        "dsr_probability", "n_trades", "start_date", "end_date",
    ):
        assert key in result, f"missing key {key!r} in score_csv result"

    assert result["verdict"] in ("ROBUST", "INCONCLUSIVE", "FRAGILE")
    assert isinstance(result["scoring_run_id"], str) and result["scoring_run_id"]
    assert Path(result["report_folder"]).exists()
    assert (Path(result["report_folder"]) / "strategy.pine").read_text() == "// pine stub"
    assert (Path(result["report_folder"]) / "tv_trades.csv").read_text(encoding="utf-8") == smoke_csv_text
    assert result["n_trades"] > 0


def test_score_csv_bad_csv_raises_tv_parse_error(tmp_path: Path):
    with pytest.raises(TVCSVParseError):
        approve_strategy.score_csv(
            csv_text="not a csv at all",
            pine_source=None, symbol="AMZN", base_name="x", timeframe="1D",
            reports_root=tmp_path / "reports",
            db_path=tmp_path / "a.db",
        )


def test_score_csv_zero_closed_trades_raises(tmp_path: Path):
    """CSV with only entry rows (no exits) -> zero closed trades."""
    # One entry-only trade (no matching exit row)
    csv = (
        "Trade #,Type,Signal,Date/Time,Price USD,Contracts,Profit USD,Profit %,"
        "Cumulative profit USD,Cumulative profit %,Run-up USD,Run-up %,Drawdown USD,Drawdown %\n"
        "1,Entry long,Long,2024-01-08 09:30,150.00,10,,,,,,,,\n"
    )
    with pytest.raises(ValueError, match="no closed trades"):
        approve_strategy.score_csv(
            csv_text=csv,
            pine_source=None, symbol="AMZN", base_name="x", timeframe="1D",
            reports_root=tmp_path / "reports",
            db_path=tmp_path / "a.db",
        )
```

- [ ] **Step 2: Run the tests — expect import error / attribute error**

```
pytest tests/web/test_approve_strategy.py -v
```

Expected: all FAIL — `ModuleNotFoundError: No module named 'tradelab.web.approve_strategy'`.

- [ ] **Step 3: Create `src/tradelab/web/approve_strategy.py` with `score_csv`**

```python
"""Dashboard-side CSV-scoring + card-approval flow (Option H Session 3a).

score_csv:   parse + score + write report folder + record audit row.
             Returns a JSON-serializable dict.
accept_scored (Task 4):
             copy Pine/CSV from report folder to pine_archive/{card_id}/,
             write verdict.json, create card in registry (disabled).

Both are pure functions. No HTTP, no global singletons. Handlers in
web/handlers.py validate request shape and map exceptions to HTTP codes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from tradelab.audit.history import DEFAULT_DB_PATH as _DEFAULT_DB_PATH
from tradelab.csv_scoring import score_trades, write_report_folder
from tradelab.io.tv_csv import parse_tv_trades_csv


def score_csv(
    *,
    csv_text: str,
    pine_source: Optional[str],
    symbol: str,
    base_name: str,
    timeframe: str,
    reports_root: Path = Path("reports"),
    db_path: Path = _DEFAULT_DB_PATH,
) -> dict:
    """Parse TV CSV, score it, write report folder, record audit row.

    Raises TVCSVParseError on bad CSV, ValueError on 0 closed trades.
    Other exceptions propagate.
    """
    parsed = parse_tv_trades_csv(csv_text, symbol=symbol)
    if not parsed.trades:
        raise ValueError("csv contained no closed trades")

    out = score_trades(parsed, strategy_name=base_name, symbol=symbol,
                       timeframe=timeframe)

    folder, run_id = write_report_folder(
        out, base_name=base_name,
        out_root=reports_root,
        pine_source=pine_source,
        csv_text=csv_text,
        record_audit=True,
        db_path=db_path,
    )

    bt = out.backtest_result
    m = bt.metrics
    return {
        "verdict":          out.verdict.verdict,
        "dsr_probability":  out.dsr_probability,
        "scoring_run_id":   run_id,
        "report_folder":    str(folder).replace("\\", "/"),
        "n_trades":         m.total_trades,
        "start_date":       bt.start_date,
        "end_date":         bt.end_date,
        "metrics": {
            "net_pnl":          m.net_pnl,
            "profit_factor":    m.profit_factor,
            "total_trades":     m.total_trades,
            "win_rate":         m.win_rate,
            "max_drawdown_pct": m.max_drawdown_pct,
            "annual_return":    m.annual_return,
            "sharpe_ratio":     m.sharpe_ratio,
        },
    }
```

- [ ] **Step 4: Run the tests — all three should pass**

```
pytest tests/web/test_approve_strategy.py -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Run the full suite for regressions**

```
pytest tests/ -q
```

Expected: baseline + Task 1 (2) + Task 2 (7) + Task 3 (3) = 351 passed, 3 pre-existing.

- [ ] **Step 6: Commit**

```
git add src/tradelab/web/approve_strategy.py tests/web/test_approve_strategy.py
git commit -m "feat(web): add approve_strategy.score_csv for dashboard CSV scoring

Thin wrapper over csv_scoring that returns a JSON-serializable dict
suitable for the dashboard Score endpoint. accept_scored lands in
the next commit."
```

---

## Task 4: `approve_strategy.accept_scored` + `.gitignore` for `pine_archive/`

**Files:**
- Modify: `src/tradelab/web/approve_strategy.py`
- Modify: `tests/web/test_approve_strategy.py` (add tests)
- Modify: `.gitignore`

- [ ] **Step 1: Add `pine_archive/` to `.gitignore`**

Edit `.gitignore`. Find the block that starts:

```
# Live webhook runtime data (card registry + alert log)
# NOTE: code lives at src/tradelab/live/ (tracked); runtime state at /live/ (not tracked)
/live/*.json
/live/*.jsonl
```

Add immediately after that block:

```
# Pine archive (immutable record of approved cards, Session 3a)
/pine_archive/
```

- [ ] **Step 2: Write the failing tests for accept_scored**

Append to `tests/web/test_approve_strategy.py`:

```python
def _score_once(smoke_csv_text: str, tmp_path: Path, base_name: str) -> dict:
    """Helper: run score_csv and return its result dict."""
    return approve_strategy.score_csv(
        csv_text=smoke_csv_text,
        pine_source="// pine stub",
        symbol="AMZN", base_name=base_name, timeframe="1H",
        reports_root=tmp_path / "reports",
        db_path=tmp_path / "audit.db",
    )


def test_accept_scored_happy(tmp_path: Path, smoke_csv_text: str):
    from tradelab.live.cards import CardRegistry
    scored = _score_once(smoke_csv_text, tmp_path, "smoke-amzn")
    registry = CardRegistry(tmp_path / "cards.json")

    result = approve_strategy.accept_scored(
        base_name="smoke-amzn", symbol="AMZN", timeframe="1H",
        report_folder=scored["report_folder"],
        verdict=scored["verdict"],
        dsr_probability=scored["dsr_probability"],
        scoring_run_id=scored["scoring_run_id"],
        registry=registry,
        pine_archive_root=tmp_path / "pine_archive",
        reports_root=tmp_path / "reports",
    )
    assert result["card_id"] == "smoke-amzn-v1"
    assert isinstance(result["secret"], str) and len(result["secret"]) >= 30
    archive = Path(result["pine_archive_path"])
    assert (archive / "strategy.pine").exists()
    assert (archive / "tv_trades.csv").exists()
    verdict_json = json.loads((archive / "verdict.json").read_text(encoding="utf-8"))
    assert verdict_json["card_id"] == "smoke-amzn-v1"
    assert verdict_json["base_name"] == "smoke-amzn"
    assert verdict_json["version"] == 1

    card = registry.get("smoke-amzn-v1")
    assert card is not None
    assert card["status"] == "disabled"
    assert card["symbol"] == "AMZN"
    assert card["version"] == 1
    assert card["base_name"] == "smoke-amzn"
    assert card["secret"] == result["secret"]


def test_accept_scored_bumps_version_on_reuse(tmp_path: Path, smoke_csv_text: str):
    from tradelab.live.cards import CardRegistry
    registry = CardRegistry(tmp_path / "cards.json")

    scored1 = _score_once(smoke_csv_text, tmp_path, "smoke-amzn")
    r1 = approve_strategy.accept_scored(
        base_name="smoke-amzn", symbol="AMZN", timeframe="1H",
        report_folder=scored1["report_folder"],
        verdict=scored1["verdict"],
        dsr_probability=scored1["dsr_probability"],
        scoring_run_id=scored1["scoring_run_id"],
        registry=registry,
        pine_archive_root=tmp_path / "pine_archive",
        reports_root=tmp_path / "reports",
    )
    scored2 = _score_once(smoke_csv_text, tmp_path, "smoke-amzn")
    r2 = approve_strategy.accept_scored(
        base_name="smoke-amzn", symbol="AMZN", timeframe="1H",
        report_folder=scored2["report_folder"],
        verdict=scored2["verdict"],
        dsr_probability=scored2["dsr_probability"],
        scoring_run_id=scored2["scoring_run_id"],
        registry=registry,
        pine_archive_root=tmp_path / "pine_archive",
        reports_root=tmp_path / "reports",
    )
    assert r1["card_id"] == "smoke-amzn-v1"
    assert r2["card_id"] == "smoke-amzn-v2"
    # Two distinct Pine archive dirs
    assert r1["pine_archive_path"] != r2["pine_archive_path"]


def test_accept_scored_refuses_report_folder_outside_reports_root(tmp_path: Path, smoke_csv_text: str):
    """Paranoid path check — reject report_folder not under reports_root."""
    from tradelab.live.cards import CardRegistry
    scored = _score_once(smoke_csv_text, tmp_path, "smoke-amzn")
    registry = CardRegistry(tmp_path / "cards.json")

    # A different root that doesn't contain the report folder
    bogus_root = tmp_path / "bogus"
    bogus_root.mkdir()
    with pytest.raises(FileNotFoundError, match="report folder"):
        approve_strategy.accept_scored(
            base_name="smoke-amzn", symbol="AMZN", timeframe="1H",
            report_folder=scored["report_folder"],
            verdict=scored["verdict"],
            dsr_probability=scored["dsr_probability"],
            scoring_run_id=scored["scoring_run_id"],
            registry=registry,
            pine_archive_root=tmp_path / "pine_archive",
            reports_root=bogus_root,
        )


def test_accept_scored_refuses_missing_pine(tmp_path: Path, smoke_csv_text: str):
    """If the report folder has no strategy.pine, refuse."""
    from tradelab.live.cards import CardRegistry
    # Score WITHOUT pine_source
    scored = approve_strategy.score_csv(
        csv_text=smoke_csv_text,
        pine_source=None,
        symbol="AMZN", base_name="smoke-amzn", timeframe="1H",
        reports_root=tmp_path / "reports",
        db_path=tmp_path / "audit.db",
    )
    registry = CardRegistry(tmp_path / "cards.json")
    with pytest.raises(ValueError, match="no strategy.pine"):
        approve_strategy.accept_scored(
            base_name="smoke-amzn", symbol="AMZN", timeframe="1H",
            report_folder=scored["report_folder"],
            verdict=scored["verdict"],
            dsr_probability=scored["dsr_probability"],
            scoring_run_id=scored["scoring_run_id"],
            registry=registry,
            pine_archive_root=tmp_path / "pine_archive",
            reports_root=tmp_path / "reports",
        )


def test_accept_scored_rolls_back_pine_archive_on_registry_failure(
    tmp_path: Path, smoke_csv_text: str, monkeypatch,
):
    from tradelab.live.cards import CardRegistry, CardExistsError
    scored = _score_once(smoke_csv_text, tmp_path, "smoke-amzn")
    registry = CardRegistry(tmp_path / "cards.json")

    def boom(self, card_id, data):
        raise CardExistsError(card_id)
    monkeypatch.setattr(CardRegistry, "create", boom)

    with pytest.raises(CardExistsError):
        approve_strategy.accept_scored(
            base_name="smoke-amzn", symbol="AMZN", timeframe="1H",
            report_folder=scored["report_folder"],
            verdict=scored["verdict"],
            dsr_probability=scored["dsr_probability"],
            scoring_run_id=scored["scoring_run_id"],
            registry=registry,
            pine_archive_root=tmp_path / "pine_archive",
            reports_root=tmp_path / "reports",
        )
    # Pine archive dir must have been cleaned up
    archive_root = tmp_path / "pine_archive"
    assert not archive_root.exists() or not any(archive_root.iterdir())
```

- [ ] **Step 3: Run the new tests — expect `accept_scored` attribute error**

```
pytest tests/web/test_approve_strategy.py -v
```

Expected: the 3 original tests pass, the 5 new ones FAIL with `AttributeError: module 'tradelab.web.approve_strategy' has no attribute 'accept_scored'`.

- [ ] **Step 4: Add `accept_scored` to `src/tradelab/web/approve_strategy.py`**

Append to `src/tradelab/web/approve_strategy.py`:

```python
import json as _json
import secrets as _secrets
import shutil as _shutil
from datetime import datetime as _datetime, timezone as _timezone

from tradelab.live.cards import CardRegistry as _CardRegistry


def accept_scored(
    *,
    base_name: str,
    symbol: str,
    timeframe: str,
    report_folder: str,
    verdict: str,
    dsr_probability: Optional[float],
    scoring_run_id: str,
    registry: _CardRegistry,
    pine_archive_root: Path = Path("pine_archive"),
    reports_root: Path = Path("reports"),
) -> dict:
    """Promote a scored report folder to an immutable card + pine_archive record.

    Raises:
      FileNotFoundError: report_folder doesn't exist or is outside reports_root.
      ValueError: report_folder has no strategy.pine.
      FileExistsError: target pine_archive dir already exists.
      CardExistsError: registry refuses duplicate (caller re-computes version).
    """
    # Paranoid path check — report_folder must live under reports_root.
    rf = Path(report_folder).resolve()
    rr = Path(reports_root).resolve()
    try:
        rf.relative_to(rr)
    except ValueError as exc:
        raise FileNotFoundError(
            f"report folder {rf} is not under reports_root {rr}"
        ) from exc
    if not rf.exists() or not rf.is_dir():
        raise FileNotFoundError(f"report folder not found: {rf}")

    pine_src = rf / "strategy.pine"
    csv_src = rf / "tv_trades.csv"
    if not pine_src.exists():
        raise ValueError(
            "report folder has no strategy.pine — re-score with Pine source"
        )

    version = registry.next_version_for(base_name)
    card_id = f"{base_name}-v{version}"
    secret = _secrets.token_urlsafe(24)  # 32-char url-safe

    archive_dir = Path(pine_archive_root) / card_id
    # exist_ok=False: caller sees FileExistsError on stale dir -> HTTP 409
    archive_dir.mkdir(parents=True, exist_ok=False)

    try:
        _shutil.copy2(pine_src, archive_dir / "strategy.pine")
        if csv_src.exists():
            _shutil.copy2(csv_src, archive_dir / "tv_trades.csv")

        created_at = _datetime.now(_timezone.utc).isoformat(timespec="seconds")
        verdict_snapshot = {
            "card_id":          card_id,
            "base_name":        base_name,
            "version":          version,
            "symbol":           symbol,
            "timeframe":        timeframe,
            "verdict":          verdict,
            "dsr_probability":  dsr_probability,
            "scoring_run_id":   scoring_run_id,
            "created_at":       created_at,
            "report_folder":    str(rf).replace("\\", "/"),
        }
        (archive_dir / "verdict.json").write_text(
            _json.dumps(verdict_snapshot, indent=2), encoding="utf-8",
        )

        card = {
            "card_id":           card_id,
            "secret":            secret,
            "symbol":            symbol,
            "status":            "disabled",
            "quantity":          None,
            "created_at":        created_at,
            "base_name":         base_name,
            "version":           version,
            "timeframe":         timeframe,
            "verdict":           verdict,
            "dsr_probability":   dsr_probability,
            "report_folder":     str(rf).replace("\\", "/"),
            "pine_archive_path": str(archive_dir).replace("\\", "/"),
            "scoring_run_id":    scoring_run_id,
        }
        registry.create(card_id, card)
    except Exception:
        # Rollback the pine archive dir so a retry can re-create it cleanly.
        _shutil.rmtree(archive_dir, ignore_errors=True)
        raise

    return {
        "card_id":           card_id,
        "secret":            secret,
        "pine_archive_path": str(archive_dir).replace("\\", "/"),
    }
```

- [ ] **Step 5: Run the tests — all 8 should pass**

```
pytest tests/web/test_approve_strategy.py -v
```

Expected: 8 PASSED.

- [ ] **Step 6: Run the full suite for regressions**

```
pytest tests/ -q
```

Expected: baseline + 2 + 7 + 3 + 5 = 356 passed, 3 pre-existing.

- [ ] **Step 7: Commit**

```
git add src/tradelab/web/approve_strategy.py tests/web/test_approve_strategy.py .gitignore
git commit -m "feat(web): add approve_strategy.accept_scored + pine_archive gitignore

Promotes a scored report folder to an immutable card in cards.json
(disabled) plus a pine_archive/{card_id}/ record with strategy.pine,
tv_trades.csv, verdict.json. Rolls back the pine archive dir on any
failure downstream of its creation. Auto-versions card_id via
registry.next_version_for(base_name)."
```

---

## Task 5: HTTP handlers `POST /tradelab/score` and `POST /tradelab/accept`

**Files:**
- Modify: `src/tradelab/web/handlers.py` (add branches in `handle_post_with_status`)
- Create: `tests/web/test_handlers_approve.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/web/test_handlers_approve.py`:

```python
"""Handler-level tests for POST /tradelab/score and POST /tradelab/accept."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tradelab.web import handlers


@pytest.fixture
def smoke_csv_text() -> str:
    return Path("tests/io/fixtures/tv_export_amzn_smoke.csv").read_text(encoding="utf-8-sig")


@pytest.fixture
def handlers_with_tmp_roots(tmp_path: Path, monkeypatch):
    """Point handler path helpers at tmp_path so tests don't touch real dirs."""
    monkeypatch.setattr(handlers, "_db_path", lambda: tmp_path / "audit.db")
    monkeypatch.setattr(handlers, "_reports_root", lambda: tmp_path / "reports")
    # New helpers (defined in handlers.py Task 5, Step 3)
    monkeypatch.setattr(handlers, "_pine_archive_root", lambda: tmp_path / "pine_archive")
    monkeypatch.setattr(handlers, "_cards_path", lambda: tmp_path / "cards.json")
    return tmp_path


def _post(path: str, payload: dict):
    body = json.dumps(payload).encode()
    raw, status = handlers.handle_post_with_status(path, body)
    return json.loads(raw), status


# ─── Score endpoint ────────────────────────────────────────────────

def test_score_happy(handlers_with_tmp_roots, smoke_csv_text):
    body, status = _post("/tradelab/score", {
        "csv_text": smoke_csv_text,
        "pine_source": "// pine",
        "symbol": "AMZN",
        "base_name": "smoke-amzn",
        "timeframe": "1H",
    })
    assert status == 200
    assert body["error"] is None
    data = body["data"]
    assert data["verdict"] in ("ROBUST", "INCONCLUSIVE", "FRAGILE")
    assert data["scoring_run_id"]
    assert data["report_folder"]


@pytest.mark.parametrize("missing", ["csv_text", "symbol", "base_name", "timeframe"])
def test_score_400_on_missing_field(handlers_with_tmp_roots, smoke_csv_text, missing):
    payload = {
        "csv_text": smoke_csv_text, "pine_source": None,
        "symbol": "AMZN", "base_name": "smoke-amzn", "timeframe": "1H",
    }
    payload.pop(missing)
    body, status = _post("/tradelab/score", payload)
    assert status == 400
    assert missing in body["error"]


@pytest.mark.parametrize("bad_name", ["Bad-Name", "x", "has space", "UPPER", "a" * 49])
def test_score_400_on_bad_base_name(handlers_with_tmp_roots, smoke_csv_text, bad_name):
    body, status = _post("/tradelab/score", {
        "csv_text": smoke_csv_text, "pine_source": None,
        "symbol": "AMZN", "base_name": bad_name, "timeframe": "1H",
    })
    assert status == 400
    assert "base_name" in body["error"]


@pytest.mark.parametrize("bad_sym", ["amzn", "AMZN1", "TOOLONGSYM", "A B"])
def test_score_400_on_bad_symbol(handlers_with_tmp_roots, smoke_csv_text, bad_sym):
    body, status = _post("/tradelab/score", {
        "csv_text": smoke_csv_text, "pine_source": None,
        "symbol": bad_sym, "base_name": "smoke", "timeframe": "1H",
    })
    assert status == 400
    assert "symbol" in body["error"]


def test_score_400_on_bad_timeframe(handlers_with_tmp_roots, smoke_csv_text):
    body, status = _post("/tradelab/score", {
        "csv_text": smoke_csv_text, "pine_source": None,
        "symbol": "AMZN", "base_name": "smoke", "timeframe": "2D",
    })
    assert status == 400
    assert "timeframe" in body["error"]


def test_score_400_on_unparseable_csv(handlers_with_tmp_roots):
    body, status = _post("/tradelab/score", {
        "csv_text": "not a csv",
        "pine_source": None,
        "symbol": "AMZN", "base_name": "smoke", "timeframe": "1H",
    })
    assert status == 400
    assert body["error"]


# ─── Accept endpoint ────────────────────────────────────────────────

def test_accept_happy(handlers_with_tmp_roots, smoke_csv_text):
    # First, score to produce a report folder
    score_body, _ = _post("/tradelab/score", {
        "csv_text": smoke_csv_text, "pine_source": "// pine",
        "symbol": "AMZN", "base_name": "smoke-amzn", "timeframe": "1H",
    })
    rf = score_body["data"]["report_folder"]

    body, status = _post("/tradelab/accept", {
        "base_name": "smoke-amzn", "symbol": "AMZN",
        "timeframe": "1H", "report_folder": rf,
    })
    assert status == 200
    assert body["error"] is None
    assert body["data"]["card_id"] == "smoke-amzn-v1"
    assert body["data"]["secret"]
    assert body["data"]["pine_archive_path"]


def test_accept_404_when_report_folder_missing(handlers_with_tmp_roots):
    body, status = _post("/tradelab/accept", {
        "base_name": "x", "symbol": "AMZN",
        "timeframe": "1H",
        "report_folder": str(handlers_with_tmp_roots / "reports" / "nonexistent_123"),
    })
    assert status == 404
    assert "report folder" in body["error"]


def test_accept_400_when_pine_missing(handlers_with_tmp_roots, smoke_csv_text):
    score_body, _ = _post("/tradelab/score", {
        "csv_text": smoke_csv_text, "pine_source": None,
        "symbol": "AMZN", "base_name": "smoke-amzn", "timeframe": "1H",
    })
    rf = score_body["data"]["report_folder"]
    body, status = _post("/tradelab/accept", {
        "base_name": "smoke-amzn", "symbol": "AMZN",
        "timeframe": "1H", "report_folder": rf,
    })
    assert status == 400
    assert "strategy.pine" in body["error"]


def test_accept_400_on_missing_field(handlers_with_tmp_roots):
    body, status = _post("/tradelab/accept", {
        "base_name": "smoke-amzn", "symbol": "AMZN", "timeframe": "1H",
        # missing report_folder
    })
    assert status == 400
    assert "report_folder" in body["error"]


def test_accept_two_accepts_bumps_version(handlers_with_tmp_roots, smoke_csv_text):
    """Accept after Accept → -v2."""
    for expected in ("smoke-amzn-v1", "smoke-amzn-v2"):
        score_body, _ = _post("/tradelab/score", {
            "csv_text": smoke_csv_text, "pine_source": "// pine",
            "symbol": "AMZN", "base_name": "smoke-amzn", "timeframe": "1H",
        })
        accept_body, status = _post("/tradelab/accept", {
            "base_name": "smoke-amzn", "symbol": "AMZN",
            "timeframe": "1H", "report_folder": score_body["data"]["report_folder"],
        })
        assert status == 200
        assert accept_body["data"]["card_id"] == expected
```

- [ ] **Step 2: Run the tests — expect failures**

```
pytest tests/web/test_handlers_approve.py -v
```

Expected: all FAIL — routes unknown (fall through to `"not found"`), or missing `_pine_archive_root` / `_cards_path` monkeypatch targets.

- [ ] **Step 3: Add path helpers + validation + routing to `src/tradelab/web/handlers.py`**

Near the top of `handlers.py`, after the existing `_reports_root()` helper (around line 112), add:

```python
def _pine_archive_root() -> Path:
    return Path("pine_archive")


def _cards_path() -> Path:
    return Path("tradelab/live/cards.json")
```

Then add validation helpers near the end of the file (after `_inject_default_params`):

```python
import re as _re_mod

_BASE_NAME_RE = _re_mod.compile(r"^[a-z0-9][a-z0-9-]{1,47}$")
_SYMBOL_RE = _re_mod.compile(r"^[A-Z]{1,10}$")
_ALLOWED_TIMEFRAMES = {"1m", "5m", "15m", "30m", "1H", "4H", "1D", "1W"}


def _validate_score_payload(payload: dict) -> Optional[str]:
    """Returns error message string or None if valid."""
    for key in ("csv_text", "symbol", "base_name", "timeframe"):
        if not payload.get(key):
            return f"missing field: {key}"
    if not _BASE_NAME_RE.match(payload["base_name"]):
        return "base_name must be lowercase alphanumeric with hyphens, 2–48 chars"
    if not _SYMBOL_RE.match(payload["symbol"]):
        return "symbol must be 1–10 uppercase letters"
    if payload["timeframe"] not in _ALLOWED_TIMEFRAMES:
        return f"unknown timeframe: {payload['timeframe']!r}"
    return None


def _validate_accept_payload(payload: dict) -> Optional[str]:
    for key in ("base_name", "symbol", "timeframe", "report_folder"):
        if not payload.get(key):
            return f"missing field: {key}"
    if not _BASE_NAME_RE.match(payload["base_name"]):
        return "base_name must be lowercase alphanumeric with hyphens, 2–48 chars"
    if not _SYMBOL_RE.match(payload["symbol"]):
        return "symbol must be 1–10 uppercase letters"
    if payload["timeframe"] not in _ALLOWED_TIMEFRAMES:
        return f"unknown timeframe: {payload['timeframe']!r}"
    return None
```

Inside `handle_post_with_status`, add route branches before the final `return handle_post(path, body), 200` fallback:

```python
    if path == "/tradelab/score":
        from tradelab.io.tv_csv import TVCSVParseError
        from tradelab.web import approve_strategy

        err = _validate_score_payload(payload)
        if err:
            return _err(err), 400
        try:
            data = approve_strategy.score_csv(
                csv_text=payload["csv_text"],
                pine_source=payload.get("pine_source") or None,
                symbol=payload["symbol"],
                base_name=payload["base_name"],
                timeframe=payload["timeframe"],
                reports_root=_reports_root(),
                db_path=_db_path(),
            )
            return _ok(data), 200
        except TVCSVParseError as e:
            return _err(str(e)), 400
        except ValueError as e:
            return _err(str(e)), 400
        except Exception as e:
            print(f"[handlers] /tradelab/score unexpected: {type(e).__name__}: {e}", file=sys.stderr)
            return _err(f"scoring failed: {type(e).__name__}: {e}"), 500

    if path == "/tradelab/accept":
        from tradelab.live.cards import CardExistsError, CardRegistry
        from tradelab.web import approve_strategy

        err = _validate_accept_payload(payload)
        if err:
            return _err(err), 400
        try:
            registry = CardRegistry(_cards_path())
            data = approve_strategy.accept_scored(
                base_name=payload["base_name"],
                symbol=payload["symbol"],
                timeframe=payload["timeframe"],
                report_folder=payload["report_folder"],
                verdict=payload.get("verdict", "INCONCLUSIVE"),
                dsr_probability=payload.get("dsr_probability"),
                scoring_run_id=payload.get("scoring_run_id", ""),
                registry=registry,
                pine_archive_root=_pine_archive_root(),
                reports_root=_reports_root(),
            )
            return _ok(data), 200
        except FileNotFoundError as e:
            return _err(str(e) or "report folder not found"), 404
        except FileExistsError as e:
            return _err(f"pine archive already exists: {e}"), 409
        except CardExistsError as e:
            return _err(f"card_id {e} already registered"), 409
        except ValueError as e:
            return _err(str(e)), 400
        except Exception as e:
            print(f"[handlers] /tradelab/accept unexpected: {type(e).__name__}: {e}", file=sys.stderr)
            return _err(f"accept failed: {type(e).__name__}: {e}"), 500
```

Notes on the accept payload:
- The handler currently takes `verdict`/`dsr_probability`/`scoring_run_id` from the payload as optional. These are produced by `score_csv` and echoed back by the frontend in the Accept POST so they can be captured in the card dict + `verdict.json` without a second audit-DB round-trip. Defaults are used if missing so a cURL-driven test call still works.

Also — the tests (Step 1) don't pass these 3 optional fields in the minimal Accept body. That's intentional: the happy-path Accept works off defaults. The frontend (Task 6) always passes them.

- [ ] **Step 4: Run the tests — all should pass**

```
pytest tests/web/test_handlers_approve.py -v
```

Expected: 13 PASSED.

- [ ] **Step 5: Run the full test suite**

```
pytest tests/ -q
```

Expected: baseline + 2 + 7 + 3 + 5 + 13 = 369 passed, 3 pre-existing.

- [ ] **Step 6: Commit**

```
git add src/tradelab/web/handlers.py tests/web/test_handlers_approve.py
git commit -m "feat(web): wire POST /tradelab/score + /tradelab/accept routes

Input validation + HTTP code mapping for the dashboard card approval
flow. Score parses CSV + scores + returns verdict. Accept creates
card in registry (disabled) + promotes to pine_archive/{card_id}/.

All real logic lives in approve_strategy. Handlers stay thin."
```

---

## Task 6: Frontend modal + JS wiring in `command_center.html`

**Files:**
- Modify: `C:/TradingScripts/command_center.html` (in the sibling `C:/TradingScripts` repo, NOT tradelab)
- Create: `C:/TradingScripts/command_center.html.bak-2026-04-24-option-h-3a` (backup sidecar, per Research v2 convention)

This task ships no tests — `command_center.html` is outside the tradelab repo and the frontend convention is manual smoke via a running dashboard. Task 7 covers that smoke.

- [ ] **Step 1: Create the backup sidecar**

```
cp C:/TradingScripts/command_center.html C:/TradingScripts/command_center.html.bak-2026-04-24-option-h-3a
```

(Use `Copy-Item` in PowerShell if `cp` isn't available.)

- [ ] **Step 2: Add the "Score New Strategy" button to the Research-tab chip row**

Find the Research tab's chip row (Grep for `researchChipRow` or look near the existing "New Strategy" button). Add a new `<button>`:

```html
<button id="scoreNewStrategyBtn" class="btn btn-primary" type="button">
  Score New Strategy
</button>
```

Place it as the last child of the chip row.

- [ ] **Step 3: Add the modal HTML**

Near the bottom of `<body>`, before the closing `</body>` tag, add:

```html
<div id="modal-score-strategy" class="modal hidden" role="dialog" aria-modal="true" aria-labelledby="modal-score-strategy-title">
  <div class="modal-backdrop" data-score-dismiss></div>
  <div class="modal-dialog" style="max-width:840px;">
    <div class="modal-header">
      <h3 id="modal-score-strategy-title">Score New Strategy</h3>
      <button type="button" class="modal-close" data-score-dismiss aria-label="Close">×</button>
    </div>
    <div class="modal-body">
      <div class="form-row">
        <label for="scoreCsvTextarea">TradingView CSV (List of trades export)</label>
        <textarea id="scoreCsvTextarea" rows="8" spellcheck="false"
                  placeholder="Paste the full CSV here, including the header row."></textarea>
      </div>
      <div class="form-row">
        <label for="scorePineTextarea">Pine source</label>
        <textarea id="scorePineTextarea" rows="6" spellcheck="false"
                  placeholder="Paste the Pine strategy source here."></textarea>
      </div>
      <div class="form-grid" style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;">
        <div class="form-row">
          <label for="scoreSymbolInput">Symbol</label>
          <input id="scoreSymbolInput" type="text" maxlength="10" placeholder="AMZN">
        </div>
        <div class="form-row">
          <label for="scoreBaseNameInput">Base name</label>
          <input id="scoreBaseNameInput" type="text" maxlength="48" placeholder="viprasol-amzn">
        </div>
        <div class="form-row">
          <label for="scoreTimeframeSelect">Timeframe</label>
          <select id="scoreTimeframeSelect">
            <option value="1m">1m</option>
            <option value="5m">5m</option>
            <option value="15m">15m</option>
            <option value="30m">30m</option>
            <option value="1H" selected>1H</option>
            <option value="4H">4H</option>
            <option value="1D">1D</option>
            <option value="1W">1W</option>
          </select>
        </div>
      </div>

      <div class="modal-error" id="scoreError" hidden></div>

      <div class="modal-actions">
        <button id="scoreSubmitBtn" class="btn btn-primary" type="button">Score</button>
      </div>

      <div id="scoreVerdictPanel" hidden style="margin-top:16px;padding:12px;border:1px solid var(--border);border-radius:6px;">
        <!-- populated after successful Score -->
      </div>

      <div class="modal-actions" id="scoreAcceptRow" hidden style="margin-top:12px;">
        <button id="scoreAcceptBtn" class="btn btn-primary" type="button" disabled>Accept</button>
      </div>

      <div id="scoreSuccessPanel" hidden style="margin-top:16px;padding:12px;border:1px solid var(--border);border-radius:6px;background:var(--surface);">
        <!-- populated after successful Accept -->
      </div>
    </div>
  </div>
</div>
```

Style classes used (`modal`, `modal-backdrop`, `modal-dialog`, etc.) are already defined in the file by Research v2's modal. Re-use them.

- [ ] **Step 4: Add JS state + event wiring inside the existing IIFE**

Find the existing `researchState` declaration (around line 2267, Grep `let researchState`). Add a `scoreSession` field to the initial object:

```js
let researchState = {
  loaded: false,
  // ... existing fields unchanged ...
  scoreSession: null,
};
```

Then, inside the same IIFE where `renderLiveCard`, `researchLoadPreflight`, etc. live, add these functions. Place them after the last existing research-tab function but before any final `})();` IIFE close:

```js
function openScoreModal() {
  researchState.scoreSession = null;
  document.getElementById('scoreCsvTextarea').value = '';
  document.getElementById('scorePineTextarea').value = '';
  document.getElementById('scoreSymbolInput').value = '';
  document.getElementById('scoreBaseNameInput').value = '';
  document.getElementById('scoreTimeframeSelect').value = '1H';
  document.getElementById('scoreError').hidden = true;
  document.getElementById('scoreError').textContent = '';
  document.getElementById('scoreVerdictPanel').hidden = true;
  document.getElementById('scoreAcceptRow').hidden = true;
  document.getElementById('scoreAcceptBtn').disabled = true;
  document.getElementById('scoreSuccessPanel').hidden = true;
  document.getElementById('scoreSubmitBtn').disabled = false;
  document.getElementById('scoreSubmitBtn').textContent = 'Score';
  document.getElementById('modal-score-strategy').classList.remove('hidden');
}

function closeScoreModal() {
  document.getElementById('modal-score-strategy').classList.add('hidden');
  researchState.scoreSession = null;
}

function scoreShowError(msg) {
  const el = document.getElementById('scoreError');
  el.textContent = msg;
  el.hidden = false;
}

function scoreRenderVerdictPanel(data) {
  const panel = document.getElementById('scoreVerdictPanel');
  while (panel.firstChild) panel.removeChild(panel.firstChild);
  const verdictSpan = document.createElement('span');
  verdictSpan.className = 'verdict-pill ' + verdictHeatClass(data.verdict);
  verdictSpan.textContent = data.verdict;
  const h = document.createElement('h4');
  h.appendChild(document.createTextNode('Verdict: '));
  h.appendChild(verdictSpan);
  panel.appendChild(h);

  const ul = document.createElement('ul');
  ul.style.margin = '8px 0 0'; ul.style.padding = '0 0 0 18px';
  const rows = [
    ['Trades', data.n_trades],
    ['Window', `${data.start_date} → ${data.end_date}`],
    ['Net P&L', data.metrics && data.metrics.net_pnl],
    ['Profit Factor', data.metrics && data.metrics.profit_factor],
    ['Max DD %', data.metrics && data.metrics.max_drawdown_pct],
    ['DSR probability', data.dsr_probability],
  ];
  rows.forEach(([k, v]) => {
    const li = document.createElement('li');
    li.textContent = `${k}: ${v == null ? 'n/a' : v}`;
    ul.appendChild(li);
  });
  panel.appendChild(ul);
  panel.hidden = false;
}

async function researchHandleScore() {
  document.getElementById('scoreError').hidden = true;
  const csv = document.getElementById('scoreCsvTextarea').value.trim();
  const pine = document.getElementById('scorePineTextarea').value;
  const symbol = document.getElementById('scoreSymbolInput').value.trim();
  const baseName = document.getElementById('scoreBaseNameInput').value.trim();
  const timeframe = document.getElementById('scoreTimeframeSelect').value;

  if (!csv) return scoreShowError('Paste the CSV first.');
  if (!symbol) return scoreShowError('Enter a Symbol.');
  if (!baseName) return scoreShowError('Enter a Base name.');
  if (!pine.trim() && !confirm('No Pine source — archive will be incomplete. Continue?')) {
    return;
  }

  const submitBtn = document.getElementById('scoreSubmitBtn');
  submitBtn.disabled = true;
  submitBtn.textContent = 'Scoring…';

  try {
    const resp = await fetch('/tradelab/score', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        csv_text: csv, pine_source: pine || null,
        symbol, base_name: baseName, timeframe,
      }),
    });
    const payload = await resp.json();
    if (!resp.ok || payload.error) {
      scoreShowError(payload.error || `HTTP ${resp.status}`);
      return;
    }
    researchState.scoreSession = {
      ...payload.data, base_name: baseName, symbol, timeframe,
    };
    scoreRenderVerdictPanel(payload.data);
    document.getElementById('scoreAcceptRow').hidden = false;
    document.getElementById('scoreAcceptBtn').disabled = false;
  } catch (e) {
    scoreShowError(`Network error: ${e.message || e}`);
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = 'Score';
  }
}

async function researchHandleAccept() {
  const s = researchState.scoreSession;
  if (!s) return scoreShowError('No scored session — click Score first.');

  if (s.verdict === 'FRAGILE') {
    const typed = prompt('This strategy is FRAGILE. Type FRAGILE to confirm approval:');
    if (typed !== 'FRAGILE') {
      scoreShowError('Accept cancelled.');
      return;
    }
  }

  const acceptBtn = document.getElementById('scoreAcceptBtn');
  acceptBtn.disabled = true;

  try {
    const resp = await fetch('/tradelab/accept', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        base_name: s.base_name, symbol: s.symbol, timeframe: s.timeframe,
        report_folder: s.report_folder,
        verdict: s.verdict,
        dsr_probability: s.dsr_probability,
        scoring_run_id: s.scoring_run_id,
      }),
    });
    const payload = await resp.json();
    if (!resp.ok || payload.error) {
      scoreShowError(payload.error || `HTTP ${resp.status}`);
      acceptBtn.disabled = false;
      return;
    }
    scoreRenderSuccessPanel(payload.data, s);
  } catch (e) {
    scoreShowError(`Network error: ${e.message || e}`);
    acceptBtn.disabled = false;
  }
}

function scoreRenderSuccessPanel(data, session) {
  const panel = document.getElementById('scoreSuccessPanel');
  while (panel.firstChild) panel.removeChild(panel.firstChild);

  const h = document.createElement('h4');
  h.textContent = 'Card created (disabled)';
  panel.appendChild(h);

  const idLine = document.createElement('p');
  idLine.appendChild(document.createTextNode('card_id: '));
  const idCode = document.createElement('code');
  idCode.textContent = data.card_id;
  idLine.appendChild(idCode);
  panel.appendChild(idLine);

  const secretLine = document.createElement('p');
  secretLine.appendChild(document.createTextNode('secret: '));
  const secretCode = document.createElement('code');
  secretCode.textContent = data.secret;
  secretLine.appendChild(secretCode);
  const copySecret = document.createElement('button');
  copySecret.type = 'button';
  copySecret.className = 'btn';
  copySecret.style.marginLeft = '8px';
  copySecret.textContent = 'Copy';
  copySecret.addEventListener('click', () => {
    navigator.clipboard.writeText(data.secret);
    copySecret.textContent = 'Copied';
    setTimeout(() => { copySecret.textContent = 'Copy'; }, 1500);
  });
  secretLine.appendChild(copySecret);
  panel.appendChild(secretLine);

  const tmplLabel = document.createElement('p');
  tmplLabel.textContent = 'TradingView Alert Message — paste this into the alert dialog:';
  panel.appendChild(tmplLabel);

  const template = JSON.stringify({
    card_id: data.card_id,
    secret: data.secret,
    action: '{{strategy.order.action}}',
    symbol: '{{ticker}}',
    contracts: '{{strategy.order.contracts}}',
  }, null, 2);
  const pre = document.createElement('pre');
  pre.style.padding = '8px'; pre.style.background = 'var(--bg)';
  pre.textContent = template;
  panel.appendChild(pre);
  const copyTmpl = document.createElement('button');
  copyTmpl.type = 'button';
  copyTmpl.className = 'btn';
  copyTmpl.textContent = 'Copy alert message';
  copyTmpl.addEventListener('click', () => {
    navigator.clipboard.writeText(template);
    copyTmpl.textContent = 'Copied';
    setTimeout(() => { copyTmpl.textContent = 'Copy alert message'; }, 1500);
  });
  panel.appendChild(copyTmpl);

  const footer = document.createElement('p');
  footer.style.marginTop = '12px';
  footer.style.color = 'var(--text3)';
  footer.textContent =
    'Card is disabled. Edit tradelab/live/cards.json and restart the receiver to enable. ' +
    '(Session 3b will add a toggle.)';
  panel.appendChild(footer);

  panel.hidden = false;
}

// Event wiring — runs once at IIFE init.
document.getElementById('scoreNewStrategyBtn').addEventListener('click', openScoreModal);
document.getElementById('scoreSubmitBtn').addEventListener('click', researchHandleScore);
document.getElementById('scoreAcceptBtn').addEventListener('click', researchHandleAccept);
document.getElementById('modal-score-strategy').addEventListener('click', (e) => {
  if (e.target.matches('[data-score-dismiss]')) closeScoreModal();
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' &&
      !document.getElementById('modal-score-strategy').classList.contains('hidden')) {
    closeScoreModal();
  }
});
```

**XSS discipline:** every `user-supplied` or server-returned string goes through `textContent`, `createTextNode`, or `dataset` — never raw `innerHTML` with `${…}` interpolation. This is the exact pattern Research v2 established (commits `8ef29ed`, `2380635`, `9e7e4ef`).

- [ ] **Step 5: Restart the dashboard and do a one-minute visual smoke**

Stop and restart `launch_dashboard.py`. Hard-refresh the browser (Ctrl+F5). In the Research tab:

1. Click **Score New Strategy** → modal opens.
2. Click the backdrop or press Esc → modal closes.
3. Open again, click Score with empty fields → inline error `"Paste the CSV first."`.

Don't do a full end-to-end smoke here — Task 7 covers that against a running receiver.

- [ ] **Step 6: Commit in the `C:/TradingScripts` repo**

```
cd C:/TradingScripts
git add command_center.html command_center.html.bak-2026-04-24-option-h-3a
git commit -m "feat(command-center): add Score New Strategy modal for Option H 3a

Paste CSV + Pine → POST /tradelab/score → verdict panel → Accept
(with FRAGILE type-confirm) → POST /tradelab/accept → success panel
with card_id, secret, and TradingView Alert Message template.

Modal + JS follows Research v2 patterns (textContent/createElement
for all server-supplied strings, event delegation, dismiss-on-backdrop,
ESC to close). Backup sidecar per convention."
```

---

## Task 7: Manual smoke + regression + cleanup

**Files:** none modified.

- [ ] **Step 1: Confirm services are up**

```powershell
foreach ($p in 8877,8878,4040) { $c = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue; if ($c) { "port ${p}: LISTEN pid $($c[0].OwningProcess)" } else { "port ${p}: NOT LISTENING" } }
```

Expected: all three listening. If not, restart per `OPTION_H_HANDOFF_2026-04-24.md` §9.

- [ ] **Step 2: Full test suite regression**

```powershell
cd C:\TradingScripts\tradelab
$env:PYTHONPATH = "src"; $env:PYTHONIOENCODING = "utf-8"
python -m pytest tests/ -q
```

Expected: baseline (339) + 2 + 7 + 3 + 5 + 13 = **369 passed, 3 pre-existing failures**. Zero new failures.

If new failures appear, STOP and diagnose before continuing — do not ship.

- [ ] **Step 3: End-to-end happy path in the browser**

1. Research tab → **Score New Strategy** → modal opens.
2. Paste the content of `tests/io/fixtures/tv_export_amzn_smoke.csv` into the CSV textarea.
3. Paste `// viprasol smoke stub` into the Pine textarea.
4. Symbol: `AMZN`. Base name: `smoke-amzn`. Timeframe: `1H`.
5. Click **Score**. Expect: verdict panel renders (likely `INCONCLUSIVE` or `FRAGILE` on 6 trades). Accept button enables.
6. Click **Accept**. If verdict is FRAGILE, type `FRAGILE` in the prompt. Expect: success panel with `card_id: smoke-amzn-v1`, secret, TV alert template. Copy buttons work.

- [ ] **Step 4: Verify on-disk state**

```powershell
cat C:\TradingScripts\tradelab\live\cards.json
ls C:\TradingScripts\tradelab\pine_archive\smoke-amzn-v1\
cat C:\TradingScripts\tradelab\pine_archive\smoke-amzn-v1\verdict.json
```

Expected:
- `cards.json` contains `smoke-amzn-v1` with `"status": "disabled"`, `"version": 1`, `"symbol": "AMZN"`, matching secret.
- `pine_archive/smoke-amzn-v1/` has `strategy.pine`, `tv_trades.csv`, `verdict.json`.
- `verdict.json` has `"card_id": "smoke-amzn-v1"`, `"version": 1`, `"base_name": "smoke-amzn"`.

- [ ] **Step 5: Verify versioning — run the flow a second time**

Repeat Step 3 with the same inputs. Expect: `card_id: smoke-amzn-v2`. Verify `cards.json` now has both `-v1` and `-v2` entries with distinct secrets.

- [ ] **Step 6: Verify disabled-by-default invariant against the receiver**

The receiver has `cards` loaded at startup and has NOT reloaded (3a intentionally has no reload endpoint). Even if the receiver knew about the new card, `status=="disabled"` rejects it. Fire a test webhook:

```powershell
$body = @{
  card_id = "smoke-amzn-v1"
  secret  = "<paste the secret from step 3>"
  action  = "buy"
  symbol  = "AMZN"
  contracts = 1
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8878/webhook" -ContentType "application/json" -Body $body
```

Expected responses (either is acceptable for 3a since receiver's in-memory view is stale):
- `{"error":"unknown card_id"}` (receiver hasn't reloaded cards.json) — **expected**, confirms 3a's "no receiver reload" scope boundary.
- `{"error":"card disabled"}` (if the receiver happens to have reloaded) — also acceptable, confirms the disabled-by-default invariant.

Either proves nothing unsafe was created.

- [ ] **Step 7: Clean up test artifacts**

```powershell
# Remove the two test cards from cards.json — hand-edit, or:
python -c "import json; p=r'C:\TradingScripts\tradelab\live\cards.json'; d=json.load(open(p)); [d.pop(k,None) for k in list(d) if k.startswith('smoke-amzn-v')]; json.dump(d, open(p,'w'), indent=2)"

# Remove the pine_archive dirs
Remove-Item -Recurse -Force C:\TradingScripts\tradelab\pine_archive\smoke-amzn-v1 -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force C:\TradingScripts\tradelab\pine_archive\smoke-amzn-v2 -ErrorAction SilentlyContinue

# Remove the transient report folders
Remove-Item -Recurse -Force C:\TradingScripts\tradelab\reports\smoke-amzn_* -ErrorAction SilentlyContinue
```

- [ ] **Step 8: Final state check + declare done**

```powershell
cd C:\TradingScripts\tradelab
git status                 # clean working tree
git log --oneline -7       # 6 new commits (Tasks 1-5 + Task 4 gitignore)
cat live\cards.json        # 3 original test cards only (no smoke-* entries)
```

Session 3a is complete when:

- All pytest regressions green (369 passed, 3 pre-existing).
- End-to-end browser smoke succeeds with `-v1` then `-v2`.
- Versioning works across repeated accepts.
- Disabled-by-default invariant verified at the receiver.
- No test artifacts left on disk.
- 6 clean commits in tradelab + 1 commit in `C:/TradingScripts`.

Next session (3b): card list UI, toggle ON/OFF, delete + flatten, receiver hot-reload. The spec for that is not yet written — start by reading `OPTION_H_SESSION_2_COMPLETE_2026-04-24.md` §4 Session 3 task list and running `superpowers:brainstorming` against the remainder.

---

## Self-review notes

This plan was self-reviewed against the spec `2026-04-24-option-h-session-3a-dashboard-card-approval-design.md` before publication:

- **Spec §2 (decisions)** — every decision has a task: TV-SOT backtest length (no code change required, documented in Task 5 validation comment); soft FRAGILE gate (Task 6 `researchHandleAccept`); always-version card_ids (Task 2 `next_version_for` + Task 4 `accept_scored`); auto-secret retrievable (Task 4 stores in card dict; Task 6 displays); V1 form fields (Task 6 modal); two-step Score/Accept (Tasks 3/4/5); Pine archive on Accept (Task 4); modal placement (Task 6).
- **Spec §4.2 card schema** — all 13 fields written by `accept_scored` in Task 4 Step 4.
- **Spec §6 error table** — all rows covered by tests in Tasks 3/4/5. Note: the `pine_archive already exists` 409 case is not directly tested (requires pre-seeding `pine_archive/`); tracked as a known gap — if it bites in live use, add a test then.
- **Spec §7 manual smoke** — all 9 steps present in Task 7 as concrete commands.
- **Type consistency** — `score_csv` return keys match exactly between Task 3 Step 3 implementation and Task 4 test helper `_score_once` consumption (`report_folder`, `verdict`, `dsr_probability`, `scoring_run_id`). `accept_scored` return keys (`card_id`, `secret`, `pine_archive_path`) match between Task 4 implementation and Task 5 handler test assertions.
- **No placeholders** — every step contains the actual code or command the engineer needs. No "implement appropriate error handling" / "similar to Task N" / "TODO".
- **Known minor gap:** Task 5 handler passes `verdict`/`dsr_probability`/`scoring_run_id` through from the Accept POST, but defaults to `"INCONCLUSIVE"` / `None` / `""` if missing. This means a hand-rolled cURL accept (no prior Score) would still work but with incorrect verdict metadata in the card. The frontend always passes them correctly. Acceptable for 3a; 3b could tighten to require them.
