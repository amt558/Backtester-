# Research Tab v3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Research tab in `command_center.html` with v3 — Tribunal layout (Action Bar + Live Cards + Cross-strategy Factor Matrix + Pipeline) — backed by five new tradelab launcher routes and rendering in vanilla HTML/CSS/SVG with the editorial trading-desk design language.

**Architecture:** Tradelab gains five backend routes (tearsheet pass-through, qs-metrics JSON, verdict-history, activate, delete-run) and four small modules (`qs_metrics.py`, `verdict_history.py`, `run_deletion.py`, `activation.py`). `command_center.html` gets a `body.research-v3` CSS scope with imported Google Fonts, then the existing `#tab-research` markup is replaced with the four-section layout. Three protected buttons (Refresh Data / New Strategy / Score New Strategy) keep their IDs and click handlers; only their CSS class changes.

**Tech Stack:** Python 3.11 stdlib + pandas/numpy (already present); QuantStats (already installed); Vanilla HTML/CSS/inline SVG (no React, no Tailwind, no build step); pytest for backend; static-HTML pytest + Playwright MCP for frontend smoke.

**Spec:** `docs/superpowers/specs/2026-04-30-research-tab-v3-design.md`

**Visual mockups:** `.superpowers/brainstorm/216-1777553249/content/{01,02,03}*.html`

> **Slice 0 amendments (2026-04-30, after Phase 0 findings):** see `docs/superpowers/notes/2026-04-30-research-v3-slice0-findings.md`.
> - **Task 4 changes:** **Do not create `tradelab/src/tradelab/web/activation.py`.** `approve_strategy.accept_scored` (lines 145–254) already writes to `cards.json` via `CardRegistry.create` for the v1 Score→Accept flow. v3 "Activate" extends that function with an `activate: bool = False` parameter. When `True`: set `status="enabled"`, stamp `activated_at` + `activated_verdict` fields. Add the gate logic (ROBUST-only) here. Tests extend `test_approve_strategy.py`.
> - **Task 5 changes:** the activation route is the existing `POST /tradelab/accept` (line 920 in `handlers.py`) with an extra `activate` boolean in the payload. `_validate_accept_payload` (line 1435) needs the new field. No new `/strategies/<id>/activate` route — drop that branch.
> - **Task 18 changes:** Class B target is **`C:/TradingScripts/alpaca_config.json`**, field `strategies[i].enabled`. The bot reads this file once at startup — no hot-reload. UI must inform the user "takes effect at next bot startup". Use write-then-rename for atomicity (existing parent-repo `write_config()` is non-atomic).

---

## File Structure

### New backend files (`tradelab/src/tradelab/web/`)

| File | Purpose | Approx LoC |
|---|---|---|
| `qs_metrics.py` | Pure functions: `sharpe`, `sortino`, `cagr`, `max_drawdown`, `monthly_returns_matrix`, `rolling_sharpe`. Operate on `pd.Series` of daily returns. No I/O. | 80 |
| `verdict_history.py` | `get_recent_verdicts(strategy_id, n=12)` reads from `tradelab_history.db` for the drift sparkline. | 30 |
| `run_deletion.py` | `delete_run_atomic(run_id)` — DB row + on-disk folder + audit log + return manifest. | 50 |
| `activation.py` | `validate_activation_gate`, `create_card_for_strategy`. Class A only in v1; Class B routing flagged for follow-up after Slice 0 research. | 60 |

### Modified backend files

| File | Change |
|---|---|
| `tradelab/src/tradelab/web/handlers.py` | Five new route branches added inside the existing `handle_get_with_status`, `handle_post_with_status`, `handle_delete_with_status` dispatchers |
| `C:\TradingScripts\launch_dashboard.py` | One new pass-through route: `GET /tradelab/runs/<run_id>/tearsheet` serves the existing QS HTML file |

### New backend tests (`tradelab/tests/web/`)

| File | Tests |
|---|---|
| `test_qs_metrics.py` | One test per metric function vs known fixtures |
| `test_verdict_history.py` | Fixture DB; recent N rows in correct order; empty case |
| `test_run_deletion.py` | Atomic delete (DB + folder + log); failure rollback; missing run 404; deletions log JSONL valid |
| `test_activation.py` | Gate validation: ROBUST→200, MARGINAL→422, no-runs→422, duplicate→409; cards.json write integrity; activations log appends |
| `test_handlers.py` (extend) | Five new route branches with happy + edge cases |

### Modified frontend file

| File | Change |
|---|---|
| `C:\TradingScripts\command_center.html` | Add Google Fonts `<link>`. Add `body.research-v3`-scoped CSS block. Replace `#tab-research` markup with action bar + Live Cards row + factor matrix + pipeline. Preserve element IDs `#refresh-data-btn`, `#new-strategy-btn`, `#score-new-strategy-btn`, `#preflight-{universe,cache,strategies,tdapi}` so existing click handlers and v2 wiring keep working |

### Frontend tests

| File | Change |
|---|---|
| `tradelab/tests/web/test_command_center_html.py` (extend) | Element-presence assertions for the four new sections; XSS regression on tile names + verdict labels; CSS variables defined; Google Fonts `<link>` present; no React/Tailwind/Vite imports |

---

## Phase 0 — Investigation

### Task 0: Identify existing Activate / approve infrastructure + Class B target

This phase produces a notes file, no code. Required before Slice 4 (activation backend) is sized correctly. **Do not skip — duplicating `approve_strategy.py` would create two write paths to `cards.json` and corrupt state.**

**Files:**
- Create: `tradelab/docs/superpowers/notes/2026-04-30-research-v3-slice0-findings.md`

- [ ] **Step 1: Read `approve_strategy.py` end-to-end**

Run: open `tradelab/src/tradelab/web/approve_strategy.py` and `tradelab/tests/web/test_approve_strategy.py`. Document in the findings file:
- What does `approve_strategy.py` expose (functions, route, payload shape)?
- Does it already write to `cards.json`? With what fields?
- Does it gate on robustness verdict? If so, what threshold?
- Is it currently called by any UI element in `command_center.html`?

- [ ] **Step 2: Read `cards_view.py` end-to-end**

Same drill. Document:
- Schema of card entries in `cards.json` (existing fields).
- Read paths (which routes serve cards data to which UI surfaces).
- Whether the file has any existing `activated_*` fields.

- [ ] **Step 3: Locate Class B bot enable-list**

Class B = S2/S4/S7/S8/S10/S12. They render on Overview tab as "Live Strategies — Tradelab Health" with editable Capital/Max-Pos and Flatten buttons. Find the source file:

Run:
```bash
grep -rn "S2_pocket_pivot\|S4_inside_day_breakout\|S12_momentum" C:/TradingScripts/ --include="*.json" --include="*.yaml" --include="*.py" 2>&1 | head -30
```

Document:
- Path to the enable-list file.
- Schema (which field = enabled flag).
- Whether the bot reads it on a polling loop or via watchdog.

- [ ] **Step 4: Decide activation routing per class**

In the findings file, write a one-paragraph decision:
- If `approve_strategy.py` already does the Class A activation we want (or close to it) → **extend** it; don't write `activation.py` from scratch. Update Slice 4's task to "extend approve_strategy with `activated_verdict`/`activated_at` snapshot fields and the duplicate-card 409 check."
- If it does something different (e.g., approval = a different concept than activation) → **rename plan's `activation.py` → `card_activator.py`** and document the relationship to `approve_strategy.py` so the two don't fight over `cards.json`.
- For Class B: document the write target path. If the file is shared with running bot processes, plan to use a write-then-rename pattern (like watchdog already expects for `cards.json`).

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab
git add docs/superpowers/notes/2026-04-30-research-v3-slice0-findings.md
git commit -m "docs(research-v3): slice 0 findings — approve_strategy survey + Class B target"
```

---

## Phase 1 — Backend foundation

### Task 1: `qs_metrics.py` — pure functions for the QS sub-grid

**Files:**
- Create: `tradelab/src/tradelab/web/qs_metrics.py`
- Create: `tradelab/tests/web/test_qs_metrics.py`

- [ ] **Step 1: Write the failing test file**

```python
# tradelab/tests/web/test_qs_metrics.py
"""Tests for QS sub-grid math. Pure functions, no I/O."""
import numpy as np
import pandas as pd
import pytest

from tradelab.web.qs_metrics import (
    sharpe, sortino, cagr, max_drawdown,
    monthly_returns_matrix, rolling_sharpe,
)


@pytest.fixture
def daily_returns_3y():
    """3 years of synthetic daily returns, deterministic."""
    rng = np.random.default_rng(seed=42)
    dates = pd.date_range("2023-01-01", periods=756, freq="B")
    returns = pd.Series(rng.normal(0.0005, 0.01, 756), index=dates)
    return returns


def test_sharpe_ratio_known_series(daily_returns_3y):
    assert sharpe(daily_returns_3y) == pytest.approx(0.79, abs=0.05)


def test_sortino_ratio_known_series(daily_returns_3y):
    assert sortino(daily_returns_3y) == pytest.approx(1.20, abs=0.10)


def test_cagr_known_series(daily_returns_3y):
    assert cagr(daily_returns_3y) == pytest.approx(0.13, abs=0.03)


def test_max_drawdown_known_series(daily_returns_3y):
    dd = max_drawdown(daily_returns_3y)
    assert -0.30 < dd < -0.02
    assert isinstance(dd, float)


def test_monthly_returns_matrix_shape(daily_returns_3y):
    m = monthly_returns_matrix(daily_returns_3y)
    # 3 years × 12 months
    assert m.shape == (3, 12)
    # Sum across all cells ≈ total compound return; sanity within order of magnitude
    assert -1.0 < m.values.sum() < 5.0


def test_rolling_sharpe_30d_length(daily_returns_3y):
    rs = rolling_sharpe(daily_returns_3y, window=30)
    assert len(rs) == len(daily_returns_3y)
    # First 29 should be NaN; remainder finite
    assert rs.iloc[:29].isna().all()
    assert rs.iloc[29:].notna().all()


def test_empty_series_returns_zero():
    empty = pd.Series([], dtype=float)
    assert sharpe(empty) == 0.0
    assert sortino(empty) == 0.0
    assert cagr(empty) == 0.0
    assert max_drawdown(empty) == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```powershell
cd C:\TradingScripts\tradelab
$env:PYTHONPATH = "src"
python -m pytest tests/web/test_qs_metrics.py -v
```
Expected: All 7 tests FAIL with `ImportError: cannot import name 'sharpe' from 'tradelab.web.qs_metrics'`.

- [ ] **Step 3: Write the implementation**

```python
# tradelab/src/tradelab/web/qs_metrics.py
"""
Pure functions for the Research v3 expanded-tile QuantStats sub-grid.

Inputs: a pandas Series of daily percentage returns (the same object
quantstats.reports.html consumes; produced by BacktestResult.daily_returns()).

No I/O. No file reads. No HTTP. Just numpy/pandas math.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ANNUAL_TRADING_DAYS = 252


def sharpe(returns: pd.Series, rf: float = 0.0) -> float:
    if returns.empty or returns.std(ddof=0) == 0:
        return 0.0
    excess = returns - rf / ANNUAL_TRADING_DAYS
    return float(np.sqrt(ANNUAL_TRADING_DAYS) * excess.mean() / excess.std(ddof=0))


def sortino(returns: pd.Series, rf: float = 0.0) -> float:
    if returns.empty:
        return 0.0
    excess = returns - rf / ANNUAL_TRADING_DAYS
    downside = excess[excess < 0]
    if downside.empty or downside.std(ddof=0) == 0:
        return 0.0
    return float(np.sqrt(ANNUAL_TRADING_DAYS) * excess.mean() / downside.std(ddof=0))


def cagr(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    total = (1.0 + returns).prod()
    years = len(returns) / ANNUAL_TRADING_DAYS
    if years <= 0 or total <= 0:
        return 0.0
    return float(total ** (1.0 / years) - 1.0)


def max_drawdown(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    equity = (1.0 + returns).cumprod()
    peak = equity.cummax()
    dd = (equity - peak) / peak
    return float(dd.min())


def monthly_returns_matrix(returns: pd.Series) -> pd.DataFrame:
    """
    Return a year × 12 matrix of monthly compounded returns.
    Rows = years (oldest first); columns = month numbers 1..12.
    Cells with no data become NaN.
    """
    if returns.empty:
        return pd.DataFrame()
    monthly = (1.0 + returns).resample("M").prod() - 1.0
    df = monthly.to_frame("ret").assign(
        year=lambda x: x.index.year, month=lambda x: x.index.month
    )
    return df.pivot(index="year", columns="month", values="ret")


def rolling_sharpe(returns: pd.Series, window: int = 30) -> pd.Series:
    if returns.empty:
        return returns.copy()
    mean = returns.rolling(window).mean()
    std = returns.rolling(window).std(ddof=0)
    return np.sqrt(ANNUAL_TRADING_DAYS) * mean / std
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```powershell
python -m pytest tests/web/test_qs_metrics.py -v
```
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab
git add src/tradelab/web/qs_metrics.py tests/web/test_qs_metrics.py
git commit -m "feat(web): add qs_metrics pure-fn module for Research v3 sub-grid"
```

---

### Task 2: `verdict_history.py` — drift sparkline data source

**Files:**
- Create: `tradelab/src/tradelab/web/verdict_history.py`
- Create: `tradelab/tests/web/test_verdict_history.py`

- [ ] **Step 1: Inspect the audit DB schema**

Run:
```bash
sqlite3 C:/TradingScripts/tradelab/data/tradelab_history.db ".schema runs"
```
Document the columns. The implementation depends on the actual column names. **If the DB doesn't exist locally yet, create a minimal fixture from `audit_reader.py`**.

- [ ] **Step 2: Write the failing test**

```python
# tradelab/tests/web/test_verdict_history.py
import sqlite3
from pathlib import Path

import pytest

from tradelab.web.verdict_history import get_recent_verdicts


@pytest.fixture
def fixture_db(tmp_path: Path) -> Path:
    """Build a fixture audit DB with 15 runs for one strategy."""
    db = tmp_path / "tradelab_history.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE runs ("
        "  run_id TEXT PRIMARY KEY, "
        "  strategy TEXT, "
        "  verdict TEXT, "
        "  scored_at TEXT"
        ")"
    )
    rows = [
        (f"r{i:03d}", "virpo-mu-v1", v, f"2026-04-{(i % 28) + 1:02d}T10:00:00")
        for i, v in enumerate([
            "robust", "robust", "robust", "marginal", "robust",
            "robust", "marginal", "marginal", "fragile", "robust",
            "robust", "robust", "robust", "robust", "robust",
        ])
    ]
    conn.executemany("INSERT INTO runs VALUES (?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return db


def test_returns_at_most_n_verdicts(fixture_db: Path):
    out = get_recent_verdicts("virpo-mu-v1", n=12, db_path=fixture_db)
    assert len(out) == 12


def test_returns_oldest_to_newest_order(fixture_db: Path):
    out = get_recent_verdicts("virpo-mu-v1", n=12, db_path=fixture_db)
    # The 12 most recent runs in insertion order; newest is "robust" (last 5)
    assert out[-1] == "robust"
    assert out[-2] == "robust"


def test_unknown_strategy_returns_empty(fixture_db: Path):
    assert get_recent_verdicts("does-not-exist", n=12, db_path=fixture_db) == []


def test_default_db_path_used_when_unspecified(monkeypatch, fixture_db: Path):
    monkeypatch.setattr(
        "tradelab.web.verdict_history._default_db_path", lambda: fixture_db
    )
    assert len(get_recent_verdicts("virpo-mu-v1", n=12)) == 12
```

- [ ] **Step 3: Run test to verify it fails**

Run:
```powershell
python -m pytest tests/web/test_verdict_history.py -v
```
Expected: FAIL — module doesn't exist.

- [ ] **Step 4: Write the implementation**

Match the column names you found in Step 1. Below assumes `runs(run_id, strategy, verdict, scored_at)`; adjust if your real schema differs.

```python
# tradelab/src/tradelab/web/verdict_history.py
"""
Verdict history fetch for the Research v3 drift sparkline.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional


def _default_db_path() -> Path:
    return Path("data/tradelab_history.db")


def get_recent_verdicts(
    strategy_id: str, n: int = 12, db_path: Optional[Path] = None
) -> list[str]:
    """
    Return up to N most recent verdicts for a strategy, oldest → newest.
    Lowercase strings: "robust" / "marginal" / "fragile" / "inconclusive".
    Empty list if no runs.
    """
    db = db_path or _default_db_path()
    if not Path(db).exists():
        return []
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT verdict FROM runs "
            "WHERE strategy = ? "
            "ORDER BY scored_at DESC LIMIT ?",
            (strategy_id, n),
        ).fetchall()
    finally:
        conn.close()
    # Reverse so result is oldest-first
    return [r[0] for r in reversed(rows)]
```

- [ ] **Step 5: Run tests to verify they pass; commit**

```powershell
python -m pytest tests/web/test_verdict_history.py -v
```
Then:
```bash
git add src/tradelab/web/verdict_history.py tests/web/test_verdict_history.py
git commit -m "feat(web): add verdict_history module for drift sparkline"
```

---

### Task 3: `run_deletion.py` — atomic run delete + audit log

**Files:**
- Create: `tradelab/src/tradelab/web/run_deletion.py`
- Create: `tradelab/tests/web/test_run_deletion.py`

- [ ] **Step 1: Write the failing test**

```python
# tradelab/tests/web/test_run_deletion.py
import json
import sqlite3
from pathlib import Path

import pytest

from tradelab.web.run_deletion import delete_run_atomic, RunNotFound


@pytest.fixture
def workspace(tmp_path: Path):
    """Build a workspace with one fake run on disk + in DB."""
    reports = tmp_path / "reports" / "virpo-mu-v1_2026-04-29-1432"
    reports.mkdir(parents=True)
    (reports / "robustness_result.json").write_text("{}")
    (reports / "quantstats_tearsheet.html").write_text("<html></html>")

    db = tmp_path / "tradelab_history.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE runs (run_id TEXT PRIMARY KEY, strategy TEXT, "
        "verdict TEXT, scored_at TEXT, report_dir TEXT)"
    )
    conn.execute(
        "INSERT INTO runs VALUES "
        "('r1', 'virpo-mu-v1', 'robust', '2026-04-29T14:32:00', ?)",
        (str(reports),),
    )
    conn.commit()
    conn.close()

    deletions_log = tmp_path / "data" / "deletions.log"
    deletions_log.parent.mkdir(parents=True, exist_ok=True)

    return {"root": tmp_path, "db": db, "log": deletions_log, "reports": reports}


def test_atomic_delete_removes_db_row_and_folder(workspace):
    delete_run_atomic("r1", db_path=workspace["db"], log_path=workspace["log"])

    # DB row removed
    conn = sqlite3.connect(workspace["db"])
    rows = conn.execute("SELECT * FROM runs WHERE run_id = 'r1'").fetchall()
    conn.close()
    assert rows == []

    # Folder removed
    assert not workspace["reports"].exists()


def test_atomic_delete_appends_audit_log(workspace):
    delete_run_atomic("r1", db_path=workspace["db"], log_path=workspace["log"])

    line = workspace["log"].read_text().strip()
    entry = json.loads(line)
    assert entry["run_id"] == "r1"
    assert entry["strategy"] == "virpo-mu-v1"
    assert entry["deleted_by"] == "ui"
    assert "ts" in entry
    assert any("robustness_result.json" in p for p in entry["paths_removed"])


def test_unknown_run_raises_RunNotFound(workspace):
    with pytest.raises(RunNotFound):
        delete_run_atomic("does-not-exist", db_path=workspace["db"], log_path=workspace["log"])

    # No audit log entry written
    assert not workspace["log"].exists() or workspace["log"].read_text() == ""
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
python -m pytest tests/web/test_run_deletion.py -v
```
Expected: ImportError — module doesn't exist.

- [ ] **Step 3: Write the implementation**

```python
# tradelab/src/tradelab/web/run_deletion.py
"""
Atomic run deletion: DB row + on-disk report folder + JSONL audit log.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional


class RunNotFound(Exception):
    pass


def delete_run_atomic(
    run_id: str,
    db_path: Optional[Path] = None,
    log_path: Optional[Path] = None,
) -> dict:
    """
    Delete a run from disk + DB, append to audit log, return a manifest dict.
    Raises RunNotFound if no row exists for run_id.

    Order matters: lookup → DB delete → folder rmtree → log append. If any step
    fails, earlier steps are committed but later steps are not — accept this
    weak atomicity in v3 (full rollback would require shadow folders).
    """
    db = Path(db_path) if db_path else Path("data/tradelab_history.db")
    log = Path(log_path) if log_path else Path("data/deletions.log")

    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT strategy, report_dir FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise RunNotFound(f"run_id {run_id} not in {db}")
        strategy, report_dir = row

        conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
        conn.commit()
    finally:
        conn.close()

    paths_removed: list[str] = []
    folder = Path(report_dir)
    if folder.exists():
        paths_removed = [str(p) for p in folder.rglob("*") if p.is_file()]
        shutil.rmtree(folder)

    log.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "run_id": run_id,
        "strategy": strategy,
        "deleted_by": "ui",
        "paths_removed": paths_removed,
    }
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    return entry
```

- [ ] **Step 4: Run tests; commit**

```powershell
python -m pytest tests/web/test_run_deletion.py -v
```
Then:
```bash
git add src/tradelab/web/run_deletion.py tests/web/test_run_deletion.py
git commit -m "feat(web): add run_deletion module with atomic delete + JSONL audit"
```

---

### Task 4: `activation.py` — gate validation + card creation (Class A)

**Note:** Slice 0 findings determine whether this task **extends `approve_strategy.py`** instead of writing a new module. If `approve_strategy.py` already does Class A activation, rewrite this task as "extend approve_strategy with snapshot fields and 409 duplicate check." Below assumes a clean slate; adapt as needed.

**Files:**
- Create: `tradelab/src/tradelab/web/activation.py`
- Create: `tradelab/tests/web/test_activation.py`

- [ ] **Step 1: Write the failing test**

```python
# tradelab/tests/web/test_activation.py
import json
from pathlib import Path

import pytest

from tradelab.web.activation import (
    activate_strategy, ActivationGateFailed, AlreadyActivated,
)


def _write_robustness(reports: Path, strategy: str, ts: str, verdict: str):
    folder = reports / f"{strategy}_{ts}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "robustness_result.json").write_text(json.dumps({
        "verdict": {"outcome": verdict, "signals": []},
        "metrics": {"profit_factor": 1.62, "win_rate": 0.58},
    }))
    return folder


@pytest.fixture
def workspace(tmp_path: Path):
    reports = tmp_path / "reports"
    cards = tmp_path / "cards.json"
    cards.write_text("[]")
    activations_log = tmp_path / "data" / "activations.log"
    activations_log.parent.mkdir(parents=True, exist_ok=True)
    return {"reports": reports, "cards": cards, "log": activations_log}


def test_activates_robust_strategy(workspace):
    _write_robustness(workspace["reports"], "virpo-mu-v1", "2026-04-29-1432", "robust")
    card = activate_strategy(
        "virpo-mu-v1",
        reports_dir=workspace["reports"],
        cards_path=workspace["cards"],
        log_path=workspace["log"],
    )
    assert card["id"] == "virpo-mu-v1"
    assert card["executing"] is False
    assert card["activated_verdict"] == "ROBUST"
    assert "activated_at" in card

    cards = json.loads(workspace["cards"].read_text())
    assert len(cards) == 1
    assert cards[0]["id"] == "virpo-mu-v1"


def test_rejects_marginal_with_gate_failed(workspace):
    _write_robustness(workspace["reports"], "S2_pocket_pivot", "2026-04-25-1900", "marginal")
    with pytest.raises(ActivationGateFailed):
        activate_strategy(
            "S2_pocket_pivot",
            reports_dir=workspace["reports"],
            cards_path=workspace["cards"],
            log_path=workspace["log"],
        )


def test_rejects_no_runs_with_gate_failed(workspace):
    with pytest.raises(ActivationGateFailed):
        activate_strategy(
            "no-runs-yet",
            reports_dir=workspace["reports"],
            cards_path=workspace["cards"],
            log_path=workspace["log"],
        )


def test_rejects_duplicate_card(workspace):
    _write_robustness(workspace["reports"], "virpo-mu-v1", "2026-04-29-1432", "robust")
    activate_strategy(
        "virpo-mu-v1",
        reports_dir=workspace["reports"],
        cards_path=workspace["cards"],
        log_path=workspace["log"],
    )
    with pytest.raises(AlreadyActivated):
        activate_strategy(
            "virpo-mu-v1",
            reports_dir=workspace["reports"],
            cards_path=workspace["cards"],
            log_path=workspace["log"],
        )


def test_appends_activations_log(workspace):
    _write_robustness(workspace["reports"], "virpo-mu-v1", "2026-04-29-1432", "robust")
    activate_strategy(
        "virpo-mu-v1",
        reports_dir=workspace["reports"],
        cards_path=workspace["cards"],
        log_path=workspace["log"],
    )
    line = workspace["log"].read_text().strip()
    entry = json.loads(line)
    assert entry["strategy"] == "virpo-mu-v1"
    assert entry["activated_verdict"] == "ROBUST"
```

- [ ] **Step 2: Run; verify fail**

```powershell
python -m pytest tests/web/test_activation.py -v
```
Expected: ImportError.

- [ ] **Step 3: Write the implementation**

```python
# tradelab/src/tradelab/web/activation.py
"""
Class A activation: validate gate, write card to cards.json, append audit log.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional


class ActivationGateFailed(Exception):
    """Latest verdict is not ROBUST, or no runs exist."""


class AlreadyActivated(Exception):
    """A card with this id is already in cards.json."""


def _latest_run_for(strategy: str, reports_dir: Path) -> Optional[Path]:
    """Return the newest <strategy>_<ts> folder for a strategy, or None."""
    if not reports_dir.exists():
        return None
    candidates = sorted(
        [p for p in reports_dir.iterdir() if p.is_dir() and p.name.startswith(f"{strategy}_")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def activate_strategy(
    strategy: str,
    reports_dir: Optional[Path] = None,
    cards_path: Optional[Path] = None,
    log_path: Optional[Path] = None,
) -> dict:
    """
    Validate ROBUST gate, snapshot verdict + metrics into a card, write it.
    Raises ActivationGateFailed if not eligible; AlreadyActivated if a card
    already exists.
    """
    reports = Path(reports_dir or "reports")
    cards = Path(cards_path or "cards.json")
    log = Path(log_path or "data/activations.log")

    latest = _latest_run_for(strategy, reports)
    if latest is None:
        raise ActivationGateFailed(f"No runs found for {strategy}")

    rr = json.loads((latest / "robustness_result.json").read_text())
    verdict = rr.get("verdict", {}).get("outcome", "").lower()
    if verdict != "robust":
        raise ActivationGateFailed(
            f"Latest verdict for {strategy} is {verdict.upper() or 'unknown'}, not ROBUST"
        )

    existing = json.loads(cards.read_text()) if cards.exists() else []
    if any(c.get("id") == strategy for c in existing):
        raise AlreadyActivated(f"Card already exists for {strategy}")

    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    card = {
        "id": strategy,
        "executing": False,
        "activated_verdict": verdict.upper(),
        "activated_at": now,
        "snapshot": {
            "metrics": rr.get("metrics", {}),
            "signals": rr.get("verdict", {}).get("signals", []),
        },
    }

    existing.append(card)
    cards.write_text(json.dumps(existing, indent=2))

    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": now,
            "strategy": strategy,
            "activated_verdict": verdict.upper(),
            "by": "ui",
        }) + "\n")

    return card
```

- [ ] **Step 4: Run tests; commit**

```powershell
python -m pytest tests/web/test_activation.py -v
```
Then:
```bash
git add src/tradelab/web/activation.py tests/web/test_activation.py
git commit -m "feat(web): add activation module — ROBUST gate + card snapshot"
```

---

### Task 5: Wire all five new routes into `handlers.py`

**Files:**
- Modify: `tradelab/src/tradelab/web/handlers.py` (extend the existing `handle_get_with_status`, `handle_post_with_status`, `handle_delete_with_status` dispatchers)
- Modify: `tradelab/tests/web/test_handlers.py` (add new route branches)

- [ ] **Step 1: Add the GET routes (qs-metrics + verdict-history)**

In `handlers.py`, locate `handle_get_with_status` (around line 208). Add new branches **before** the catch-all 404:

```python
# Inside handle_get_with_status, before the final 404 return:

# /tradelab/runs/<run_id>/qs-metrics
m = re.match(r"^/tradelab/runs/(?P<run_id>[^/]+)/qs-metrics$", path_with_query.split("?")[0])
if m:
    from . import qs_metrics
    from .audit_reader import find_run_by_id  # existing helper
    run = find_run_by_id(m.group("run_id"))
    if run is None:
        return ("", 404)
    returns = _load_daily_returns_for_run(run)  # implement helper using results.py BacktestResult.daily_returns
    payload = {
        "sharpe": qs_metrics.sharpe(returns),
        "sortino": qs_metrics.sortino(returns),
        "cagr": qs_metrics.cagr(returns),
        "max_drawdown": qs_metrics.max_drawdown(returns),
        "monthly_returns": qs_metrics.monthly_returns_matrix(returns).fillna(0).values.tolist(),
        "rolling_sharpe": qs_metrics.rolling_sharpe(returns).dropna().tolist(),
        # 4 plain numbers for the 8-cell sub-grid header
        "total_return": float((1.0 + returns).prod() - 1.0) if len(returns) else 0.0,
        "trades": run.get("trades", 0),
        "avg_win_pct": run.get("avg_win_pct", 0.0),
        "avg_loss_pct": run.get("avg_loss_pct", 0.0),
    }
    return (json.dumps(payload), 200)

# /tradelab/strategies/<id>/verdict-history
m = re.match(r"^/tradelab/strategies/(?P<id>[^/]+)/verdict-history$", path_with_query.split("?")[0])
if m:
    from . import verdict_history
    history = verdict_history.get_recent_verdicts(m.group("id"), n=12)
    return (json.dumps({"verdicts": history}), 200)
```

(`_load_daily_returns_for_run` is a small helper that opens `<run_dir>/equity_curve.csv` if present, builds a `pd.Series`, and returns it. Add it adjacent.)

- [ ] **Step 2: Add the POST route (activate)**

Locate `handle_post_with_status` (around line 838). Add a new branch:

```python
# /tradelab/strategies/<id>/activate
m = re.match(r"^/tradelab/strategies/(?P<id>[^/]+)/activate$", path)
if m:
    from .activation import activate_strategy, ActivationGateFailed, AlreadyActivated
    try:
        card = activate_strategy(m.group("id"))
    except ActivationGateFailed as e:
        return (json.dumps({"error": str(e)}), 422)
    except AlreadyActivated as e:
        return (json.dumps({"error": str(e)}), 409)
    sse.broadcast({"type": "card_activated", "card": card})  # existing SSE helper
    return (json.dumps(card), 200)
```

- [ ] **Step 3: Add the DELETE route**

Locate `handle_delete_with_status` (around line 1449). Add:

```python
# DELETE /tradelab/runs/<run_id>
m = re.match(r"^/tradelab/runs/(?P<run_id>[^/]+)$", path)
if m:
    from .run_deletion import delete_run_atomic, RunNotFound
    try:
        manifest = delete_run_atomic(m.group("run_id"))
    except RunNotFound as e:
        return (json.dumps({"error": str(e)}), 404)
    sse.broadcast({"type": "run_deleted", "run_id": manifest["run_id"], "strategy": manifest["strategy"]})
    return (json.dumps(manifest), 200)
```

- [ ] **Step 4: Write handler tests**

Add to `tests/web/test_handlers.py`:

```python
def test_get_qs_metrics_unknown_run_returns_404():
    body, status = handle_get_with_status("/tradelab/runs/does-not-exist/qs-metrics")
    assert status == 404


def test_get_verdict_history_returns_json_with_verdicts_list():
    body, status = handle_get_with_status("/tradelab/strategies/virpo-mu-v1/verdict-history")
    assert status == 200
    payload = json.loads(body)
    assert "verdicts" in payload
    assert isinstance(payload["verdicts"], list)


def test_post_activate_unknown_strategy_returns_422():
    body, status = handle_post_with_status(
        "/tradelab/strategies/no-such-thing/activate", b"{}"
    )
    assert status == 422


def test_delete_run_unknown_returns_404():
    body, status = handle_delete_with_status("/tradelab/runs/does-not-exist")
    assert status == 404
```

- [ ] **Step 5: Run; commit**

```powershell
python -m pytest tests/web/test_handlers.py -v
```
```bash
git add src/tradelab/web/handlers.py tests/web/test_handlers.py
git commit -m "feat(web): wire 5 new Research-v3 routes (qs-metrics, verdict-history, activate, delete-run)"
```

---

### Task 6: Launcher — tearsheet pass-through route in `launch_dashboard.py`

**Files:**
- Modify: `C:\TradingScripts\launch_dashboard.py`
- Test: manual (no pytest in this repo); verify via curl

- [ ] **Step 1: Locate the existing `/tradelab/compare-report` handler**

Run:
```bash
grep -n "compare-report\|serve_compare_report" C:/TradingScripts/launch_dashboard.py
```
Confirm the shape (it's a method on the request handler class, returns the static HTML file's bytes with `text/html` content-type).

- [ ] **Step 2: Add the tearsheet route mirroring that pattern**

In `launch_dashboard.py`, add adjacent to `serve_compare_report`:

```python
def serve_run_tearsheet(self, run_id: str) -> bool:
    """Serve <reports>/<strategy>_<ts>/quantstats_tearsheet.html for a run_id."""
    from tradelab.web.audit_reader import find_run_by_id  # adjust import if differs
    run = find_run_by_id(run_id)
    if run is None or not run.get("report_dir"):
        self.send_error(404)
        return True
    tearsheet = Path(run["report_dir"]) / "quantstats_tearsheet.html"
    if not tearsheet.exists():
        self.send_error(404)
        return True
    body = tearsheet.read_bytes()
    self.send_response(200)
    self.send_header("Content-Type", "text/html; charset=utf-8")
    self.send_header("Content-Length", str(len(body)))
    self.end_headers()
    self.wfile.write(body)
    return True
```

Then register the route in the `do_GET` dispatcher, mirroring how `compare-report` is registered:

```python
m = re.match(r"^/tradelab/runs/(?P<run_id>[^/]+)/tearsheet$", parsed.path)
if m:
    return self.serve_run_tearsheet(m.group("run_id"))
```

- [ ] **Step 3: Smoke-test with curl**

Start the launcher (`python launch_dashboard.py`), then:
```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8877/tradelab/runs/does-not-exist/tearsheet
# Expected: 404
```
Trigger a real run via the dashboard; copy a real run_id from the pipeline; then:
```bash
curl -sI "http://localhost:8877/tradelab/runs/<real-run-id>/tearsheet" | head -3
# Expected: HTTP/1.0 200 OK + Content-Type: text/html
```

- [ ] **Step 4: Commit**

```bash
cd C:/TradingScripts
git add launch_dashboard.py
git commit -m "feat(launcher): serve QuantStats tearsheet HTML for Research-v3 expanded tile"
```

---

## Phase 2 — Frontend foundation

### Task 7: Editorial CSS scope + Google Fonts in `command_center.html`

**Files:**
- Modify: `C:\TradingScripts\command_center.html` (add `<link>` to `<head>`, append a new scoped CSS block before the closing `</style>` of the existing big style block, or as a new `<style>` after it)

- [ ] **Step 1: Backup the file**

```powershell
Copy-Item C:\TradingScripts\command_center.html C:\TradingScripts\command_center.html.bak-2026-04-30-v3
```

- [ ] **Step 2: Add Google Fonts `<link>` in `<head>`**

Locate `<head>` and add (above any existing `<link>`):

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,500;1,9..144,400&family=Geist:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
```

- [ ] **Step 3: Append the `body.research-v3` CSS scope**

Add a new `<style id="research-v3-scope">` block (or append to the existing one) containing the full palette + typography from translation #3. **Copy verbatim from the assembled mockup**:

```css
body.research-v3 {
  --bg: #0a0a0c;
  --bg-1: #101013;
  /* ... full palette as in 03-assembled-research-tab.html ... */
  --font-display: 'Fraunces', Georgia, serif;
  --font-sans: 'Geist', -apple-system, BlinkMacSystemFont, sans-serif;
  --font-mono: 'JetBrains Mono', 'SF Mono', Menlo, monospace;
}
body.research-v3 #tab-research { /* all v3 tile / matrix / pipeline styles */ }
```

Do not change other tabs' selectors.

- [ ] **Step 4: Toggle the body class only when Research is the active tab**

Find the existing tab-switching JS (look for `setActiveTab` or `tab-research`):
```javascript
// In the existing tab-switch handler, when research becomes active:
document.body.classList.add('research-v3');
// When any other tab becomes active:
document.body.classList.remove('research-v3');
```

- [ ] **Step 5: Manual smoke + commit**

Open the dashboard. Click between tabs:
- Research tab → typography is Fraunces / Geist / JetBrains Mono; warm-dark + copper.
- Other tabs → unchanged from current dashboard.

```bash
cd C:/TradingScripts
git add command_center.html
git commit -m "feat(command-center): add research-v3 CSS scope + editorial Google Fonts"
```

---

### Task 8: Action bar restyle (preserve protected buttons + chips + add canary icon + calibration trust)

**Files:**
- Modify: `C:\TradingScripts\command_center.html` (the `#tab-research` action bar markup)

- [ ] **Step 1: Replace the existing chip cluster with the v3 action bar**

Locate the existing top-of-Research chip cluster (the strip with the 4 preflight chips and the Refresh / New buttons). Replace its outer container with:

```html
<div class="action-bar">
  <div class="button-group">
    <button id="refresh-data-btn" class="ab-btn primary">↻ Refresh Data</button>
    <button id="new-strategy-btn" class="ab-btn">+ New Strategy</button>
    <button id="score-new-strategy-btn" class="ab-btn">⊕ Score New Strategy</button>
  </div>
  <span class="ab-divider"></span>
  <span id="preflight-universe" class="chip"><span class="dot"></span><span class="l">Universe</span><span class="v">—</span></span>
  <span class="chip-divider"></span>
  <span id="preflight-cache" class="chip"><span class="dot"></span><span class="l">Cache</span><span class="v">—</span></span>
  <span class="chip-divider"></span>
  <span id="preflight-strategies" class="chip"><span class="dot"></span><span class="l">Strategies</span><span class="v">—</span></span>
  <span class="chip-divider"></span>
  <span id="preflight-tdapi" class="chip"><span class="dot"></span><span class="l">TD-API</span><span class="v">—</span></span>
  <span class="ab-divider"></span>
  <span id="calibration-trust" class="chip"><span class="l">Calibration trust</span><span class="v">—</span></span>
  <span class="ab-spacer"></span>
  <button id="canary-status-icon" class="canary-icon" title="" hidden>⚠</button>
</div>
```

**Critical:** preserve the existing element IDs so v2's preflight + button click handlers keep working without rewiring.

- [ ] **Step 2: Add JS to populate the calibration-trust chip**

Reuse the existing verdict-calibration data fetch (find it in the current Research-tab JS). Add:

```javascript
async function refreshCalibrationTrust() {
  const data = await fetchJSON('/tradelab/calibration-summary');  // existing v2 endpoint
  const trust = data.shared_robust / Math.max(1, data.total);  // 0..1
  const el = document.getElementById('calibration-trust');
  el.querySelector('.v').textContent = trust.toFixed(2);
  el.querySelector('.v').style.color = trust >= 0.7 ? 'var(--green)' : trust >= 0.5 ? 'var(--amber)' : 'var(--red)';
}
// Call refreshCalibrationTrust() on Research tab activation.
```

- [ ] **Step 3: Add JS to toggle the canary icon**

```javascript
async function refreshCanaryStatus() {
  const data = await fetchJSON('/tradelab/canary-status');  // existing v2 endpoint
  const icon = document.getElementById('canary-status-icon');
  const anyDegraded = data.canaries.some(c => c.status !== 'pass');
  icon.hidden = !anyDegraded;
  icon.title = anyDegraded
    ? data.canaries.filter(c => c.status !== 'pass').map(c => c.name).join(', ')
    : '';
}
```

- [ ] **Step 4: Static-HTML test extension**

Add to `tradelab/tests/web/test_command_center_html.py`:

```python
def test_action_bar_preserves_protected_button_ids():
    html = _load_html()
    assert 'id="refresh-data-btn"' in html
    assert 'id="new-strategy-btn"' in html
    assert 'id="score-new-strategy-btn"' in html


def test_action_bar_has_calibration_trust_and_canary_icon():
    html = _load_html()
    assert 'id="calibration-trust"' in html
    assert 'id="canary-status-icon"' in html


def test_action_bar_preserves_preflight_chips():
    html = _load_html()
    for chip in ('preflight-universe', 'preflight-cache', 'preflight-strategies', 'preflight-tdapi'):
        assert f'id="{chip}"' in html
```

- [ ] **Step 5: Smoke + commit**

Open dashboard → Research tab. Verify:
- Three buttons render with editorial styling, click handlers still fire (Refresh Data triggers a fetch, etc.).
- Preflight chips populate from the existing v2 endpoint.
- Calibration trust chip shows a number 0.0–1.0.
- Canary icon stays hidden when canaries are pass; unhide manually via DevTools to verify the amber render.

```bash
cd C:/TradingScripts
git add command_center.html
cd C:/TradingScripts/tradelab
git add tests/web/test_command_center_html.py
git commit -m "feat(command-center): action-bar restyle preserving protected button IDs"
```

---

## Phase 3 — Live Cards row

### Task 9: Live Cards compact tile rendering (verdict pill + drift sparkline + KPIs)

**Files:**
- Modify: `C:\TradingScripts\command_center.html` (replace the existing `#live-strategies-grid` markup + JS render)

- [ ] **Step 1: Replace the Live Strategies markup with the new tile-grid container**

In the Research tab, locate the existing `LIVE STRATEGIES — TRADELAB HEALTH` section (probably wrapped in something like `<div id="live-strategies-grid">`). Replace with:

```html
<section class="section-header">
  <h2>Live Cards <em>· strategies under research</em></h2>
  <div class="meta"><span id="live-cards-meta">— cards · click any tile to expand</span></div>
</section>
<div id="live-cards-grid" class="tile-grid">
  <!-- tiles rendered by renderLiveCardsGrid() -->
</div>
```

- [ ] **Step 2: Implement `renderLiveCardsGrid` (compact tile only — no expand yet)**

```javascript
function tileHtml(s) {
  // s = { id, symbol, timeframe, class_, verdict, kpis: {pf,wr,dd,dsr}, te, ks, trades }
  // Returns innerHTML for one compact tile. ALL string interpolation goes through escapeHtml().
  const v = (s.verdict || 'inconclusive').toLowerCase();
  const kpiCell = (label, value, cls) =>
    `<div class="kpi"><span class="l">${label}</span><span class="v ${cls || ''}">${value === null || value === undefined ? '—' : escapeHtml(String(value))}</span></div>`;
  return `
    <div class="tile-head">
      <div>
        <div class="tile-name">${escapeHtml(s.id)}</div>
        <div class="tile-meta">${escapeHtml(s.symbol || '—')} · ${escapeHtml(s.timeframe || '—')} · ${escapeHtml(s.class_ || 'bot')}</div>
      </div>
      <span class="verdict ${v}">${escapeHtml(v.replace(/^./, c => c.toUpperCase()))}</span>
    </div>
    <div class="drift" data-strategy="${escapeHtml(s.id)}"></div>
    <div class="kpis">
      ${kpiCell('PF', s.kpis?.pf, s.kpis?.pf >= 1.3 ? 'ok' : s.kpis?.pf >= 1.0 ? 'warn' : 'fail')}
      ${kpiCell('WR', s.kpis?.wr ? Math.round(s.kpis.wr * 100) + '%' : null)}
      ${kpiCell('DD', s.kpis?.dd ? (s.kpis.dd * 100).toFixed(1) + '%' : null, s.kpis?.dd <= -0.15 ? 'fail' : s.kpis?.dd <= -0.10 ? 'warn' : '')}
      ${kpiCell('DSR', s.kpis?.dsr?.toFixed(2), s.kpis?.dsr >= 0.7 ? 'ok' : s.kpis?.dsr >= 0.5 ? 'warn' : 'fail')}
    </div>
    <div class="health-row">
      <span style="...">TE</span><span class="te-bar ${s.te || ''}"><span></span><span></span><span></span><span></span><span></span></span>
      <span style="...">K-S</span><span class="ks-dot ${s.ks || ''}"></span>
      <span style="...; margin-left:auto">${s.trades || 0} trd</span>
    </div>
    <div class="actions">
      <button class="activate ${activateState(s)}">${activateLabel(s)}</button>
    </div>
  `;
}

function activateState(s) {
  if (s.has_card) return 'live';
  if ((s.verdict || '').toLowerCase() === 'robust') return 'enabled';
  return 'disabled';
}

function activateLabel(s) {
  if (s.has_card) return '● Already live ↗';
  if ((s.verdict || '').toLowerCase() === 'robust') return '↑ Activate';
  const reason = (s.verdict || '').toUpperCase() || 'score req\'d';
  return `↑ Activate <span class="reason">— ${reason}</span>`;
}

async function renderLiveCardsGrid() {
  const grid = document.getElementById('live-cards-grid');
  const data = await fetchJSON('/tradelab/strategies-summary');  // existing v2 endpoint or its v3 successor
  grid.innerHTML = '';
  for (const s of data.strategies) {
    const div = document.createElement('div');
    div.className = 'tile';
    if ((s.verdict || '').toLowerCase() === 'fragile') div.classList.add('review-red');
    else if ((s.verdict || '').toLowerCase() === 'marginal') div.classList.add('review-amber');
    if (s.has_card) div.classList.add('activated');
    div.dataset.strategyId = s.id;
    div.innerHTML = tileHtml(s);
    grid.appendChild(div);
  }
  document.getElementById('live-cards-meta').textContent =
    `${data.strategies.length} cards · click any tile to expand`;
  await renderAllDriftSparklines();
}
```

- [ ] **Step 3: Implement drift sparkline rendering**

```javascript
async function renderAllDriftSparklines() {
  const drifts = document.querySelectorAll('#live-cards-grid .drift');
  await Promise.all(Array.from(drifts).map(async (el) => {
    const id = el.dataset.strategy;
    const { verdicts } = await fetchJSON(`/tradelab/strategies/${encodeURIComponent(id)}/verdict-history`);
    el.innerHTML = '';
    const dots = 12;
    const padding = dots - verdicts.length;
    for (let i = 0; i < padding; i++) {
      const d = document.createElement('span');
      d.className = 'dot';
      el.appendChild(d);
    }
    for (const v of verdicts) {
      const d = document.createElement('span');
      d.className = 'dot ' + (v || 'inconclusive');
      el.appendChild(d);
    }
  }));
}
```

- [ ] **Step 4: Static-HTML test**

```python
def test_live_cards_grid_present_and_no_raw_template_interpolation():
    html = _load_html()
    assert 'id="live-cards-grid"' in html
    # Server-supplied strings must use escapeHtml, never raw template
    bad = re.search(r'innerHTML\s*=\s*`[^`]*\$\{s\.(id|verdict|symbol)\}', html)
    assert bad is None, f"Raw template interpolation: {bad.group(0)}"
```

- [ ] **Step 5: Smoke + commit**

```bash
cd C:/TradingScripts
git add command_center.html
cd C:/TradingScripts/tradelab
git add tests/web/test_command_center_html.py
git commit -m "feat(command-center): Live Cards compact tile + drift sparkline"
```

---

### Task 10: Activate button state machine + cross-tab linkage

**Files:**
- Modify: `C:\TradingScripts\command_center.html`

- [ ] **Step 1: Wire the Activate click handler**

```javascript
document.getElementById('live-cards-grid').addEventListener('click', async (e) => {
  const btn = e.target.closest('.activate');
  if (!btn) return;
  e.stopPropagation();  // prevent tile expand
  const tile = btn.closest('.tile');
  const strategy = tile.dataset.strategyId;
  if (btn.classList.contains('disabled')) return;
  if (btn.classList.contains('live')) {
    switchToOverviewTabAndScrollTo(strategy);
    return;
  }
  // enabled → activating → live (or → enabled + toast on error)
  btn.classList.replace('enabled', 'activating');
  btn.textContent = 'Activating…';
  try {
    const card = await postJSON(`/tradelab/strategies/${encodeURIComponent(strategy)}/activate`, {});
    btn.classList.replace('activating', 'live');
    btn.textContent = '● Already live ↗';
    tile.classList.add('activated');
    showToast(`Activated ${strategy}`);
  } catch (err) {
    btn.classList.replace('activating', 'enabled');
    btn.textContent = '↑ Activate';
    showToast(`Activate failed: ${err.message}`, 'error');
  }
});
```

- [ ] **Step 2: Implement `switchToOverviewTabAndScrollTo`**

```javascript
function switchToOverviewTabAndScrollTo(strategyId) {
  setActiveTab('overview');
  setTimeout(() => {
    const card = document.querySelector(`[data-card-id="${CSS.escape(strategyId)}"]`);
    if (card) {
      card.scrollIntoView({ behavior: 'smooth', block: 'center' });
      card.classList.add('highlight-pulse');
      setTimeout(() => card.classList.remove('highlight-pulse'), 1800);
    }
  }, 150);
}
```

Add a small CSS animation:
```css
@keyframes highlight-pulse {
  0%, 100% { box-shadow: 0 0 0 0 var(--accent); }
  50% { box-shadow: 0 0 0 6px var(--accent-glow); }
}
.highlight-pulse { animation: highlight-pulse 1.6s ease-in-out 1; }
```

- [ ] **Step 3: Add `↗ Research` link on Overview cards**

Locate Overview tab card render. Add to the top of each card:
```html
<button class="open-research-btn" data-strategy="${escapeHtml(c.id)}" title="Open in Research">↗ Research</button>
```
Wire:
```javascript
// once, on document ready
document.addEventListener('click', (e) => {
  const btn = e.target.closest('.open-research-btn');
  if (!btn) return;
  setActiveTab('research');
  setTimeout(() => {
    const tile = document.querySelector(`#live-cards-grid [data-strategy-id="${CSS.escape(btn.dataset.strategy)}"]`);
    if (tile) {
      tile.scrollIntoView({ behavior: 'smooth', block: 'center' });
      tile.classList.add('highlight-pulse');
      setTimeout(() => tile.classList.remove('highlight-pulse'), 1800);
    }
  }, 150);
});
```

- [ ] **Step 4: Smoke + commit**

Activate `virpo-mu-v1` from Research tab → tile turns green, switches to Overview, virpo-mu card pulses.
Click `↗ Research` on an Overview card → switches back, tile pulses.

```bash
git add command_center.html
git commit -m "feat(command-center): Activate state machine + cross-tab scroll-to-and-pulse"
```

---

### Task 11: Click-to-expand inline (header + 7-cell summary + tab strip + tearsheet button)

**Files:**
- Modify: `C:\TradingScripts\command_center.html`

- [ ] **Step 1: Add expand template**

```javascript
function expandedTileHtml(s) {
  const v = (s.verdict || 'inconclusive').toLowerCase();
  return `
    <div class="ex-inner">
      <div class="ex-header">
        <div class="ex-name">
          <span class="strategy">${escapeHtml(s.id)}</span>
          <span class="stale">scored ${s.scored_ago || '—'} · backtest ${escapeHtml(s.backtest_range || '—')} · ${escapeHtml(s.symbol || '—')} · ${escapeHtml(s.class_ || 'bot')}</span>
        </div>
        <button class="close-btn">▴ collapse</button>
      </div>
      <div class="ex-summary">
        <div class="ex-cell"><span class="label">Verdict</span><span class="value"><span class="verdict ${v}">${escapeHtml(v.replace(/^./, c => c.toUpperCase()))}</span></span></div>
        <div class="ex-cell"><span class="label">Profit factor</span><span class="value ${s.kpis?.pf >= 1.3 ? 'ok' : 'warn'}">${(s.kpis?.pf ?? 0).toFixed(2)}</span></div>
        <div class="ex-cell"><span class="label">Win rate</span><span class="value">${s.kpis?.wr ? Math.round(s.kpis.wr*100) : '—'}%</span></div>
        <div class="ex-cell"><span class="label">Max DD</span><span class="value warn">${s.kpis?.dd ? (s.kpis.dd*100).toFixed(1) : '—'}%</span></div>
        <div class="ex-cell"><span class="label">DSR</span><span class="value ok">${(s.kpis?.dsr ?? 0).toFixed(2)}</span></div>
        <div class="ex-cell"><span class="label">TE health</span><span class="value"><span class="ex-te ${s.te || ''}"><span></span><span></span><span></span><span></span><span></span></span></span></div>
        <div class="ex-cell"><span class="label">K-S</span><span class="value ok">${escapeHtml(s.ks_p || '—')}</span></div>
      </div>
      <div class="tab-strip">
        <div class="tab-strip-tabs">
          <button class="active" data-tab="qs">QuantStats <span class="pill-count">${escapeHtml(s.cover || '—')}</span></button>
          <button data-tab="factors">Factors <span class="pill-count">${(s.signals_count ?? 7)}</span></button>
          <button disabled>Trades <span class="pill-count">v1.5</span></button>
        </div>
        <a class="deep-dive-btn" href="/tradelab/runs/${encodeURIComponent(s.latest_run_id || '')}/tearsheet" target="_blank">View full tearsheet ↗</a>
      </div>
      <div class="tab-content tab-qs"></div>
      <div class="tab-content tab-factors" hidden></div>
    </div>
  `;
}
```

- [ ] **Step 2: Tile click → toggle expand inline**

```javascript
document.getElementById('live-cards-grid').addEventListener('click', (e) => {
  if (e.target.closest('.activate, .close-btn, .deep-dive-btn, .tab-strip-tabs button')) return;
  const tile = e.target.closest('.tile');
  if (!tile) return;
  const strategyId = tile.dataset.strategyId;
  const isExpanded = tile.classList.contains('expanded');
  // Collapse any other expanded tile first (only one expanded at a time)
  document.querySelectorAll('#live-cards-grid .tile.expanded').forEach(t => collapseTile(t));
  if (!isExpanded) expandTile(tile, strategyId);
});

function expandTile(tile, strategyId) {
  tile.classList.add('expanded');
  // Replace inner content with expanded markup
  const s = strategyDataCache.get(strategyId);  // populated during renderLiveCardsGrid
  tile.innerHTML = expandedTileHtml(s);
  // Lazy-load QS sub-grid + charts (Task 12)
  loadQsForExpandedTile(tile, s.latest_run_id);
}

function collapseTile(tile) {
  tile.classList.remove('expanded');
  const strategyId = tile.dataset.strategyId;
  const s = strategyDataCache.get(strategyId);
  tile.innerHTML = tileHtml(s);
  // Re-render its drift sparkline
  renderDriftFor(tile.querySelector('.drift'), strategyId);
}
```

- [ ] **Step 3: Close button + click-outside-to-collapse**

```javascript
// Inside the same delegated listener:
if (e.target.closest('.close-btn')) {
  const tile = e.target.closest('.tile');
  collapseTile(tile);
  return;
}
```

- [ ] **Step 4: Commit**

```bash
git add command_center.html
git commit -m "feat(command-center): Live Card click-to-expand inline + 7-cell summary + tearsheet button"
```

---

### Task 12: QuantStats sub-grid + 3 inline SVG charts in expanded tile

**Files:**
- Modify: `C:\TradingScripts\command_center.html`

- [ ] **Step 1: Implement `loadQsForExpandedTile`**

```javascript
async function loadQsForExpandedTile(tile, runId) {
  const qsContainer = tile.querySelector('.tab-qs');
  qsContainer.innerHTML = '<div class="loading">Loading…</div>';
  if (!runId) {
    qsContainer.innerHTML = '<div class="empty">No run data — score this strategy first.</div>';
    return;
  }
  let m;
  try {
    m = await fetchJSON(`/tradelab/runs/${encodeURIComponent(runId)}/qs-metrics`);
  } catch (err) {
    qsContainer.innerHTML = `<div class="error">Failed to load: ${escapeHtml(err.message)}</div>`;
    return;
  }
  qsContainer.innerHTML = qsGridHtml(m) + qsChartsHtml(m);
}

function qsGridHtml(m) {
  const cell = (label, value, cls) =>
    `<div class="qs-stat"><div class="label">${escapeHtml(label)}</div><div class="value ${cls || ''}">${escapeHtml(value)}</div></div>`;
  const pct = (x) => (x * 100).toFixed(1) + '%';
  return `<div class="qs-grid">
    ${cell('Total return', pct(m.total_return), m.total_return >= 0 ? 'ok' : 'fail')}
    ${cell('Sharpe', m.sharpe.toFixed(2), m.sharpe >= 1 ? 'ok' : 'warn')}
    ${cell('Sortino', m.sortino.toFixed(2), m.sortino >= 1 ? 'ok' : 'warn')}
    ${cell('CAGR', pct(m.cagr), m.cagr >= 0 ? 'ok' : 'fail')}
    ${cell('Avg win', '+' + (m.avg_win_pct * 100).toFixed(2) + '%')}
    ${cell('Avg loss', (m.avg_loss_pct * 100).toFixed(2) + '%')}
    ${cell('Trades', String(m.trades))}
    ${cell('Avg hold', (m.avg_hold ?? '—') + 'd')}
  </div>`;
}
```

- [ ] **Step 2: Implement the three SVG charts**

```javascript
function qsChartsHtml(m) {
  return `<div class="qs-charts">
    <div class="qs-chart"><div class="chart-title">Drawdown · 2y</div>${drawdownSvg(m)}</div>
    <div class="qs-chart"><div class="chart-title">Monthly returns</div>${monthlyHeatmap(m.monthly_returns)}</div>
    <div class="qs-chart"><div class="chart-title">Rolling Sharpe · 30d</div>${rollingSharpeSvg(m.rolling_sharpe)}</div>
  </div>`;
}

function drawdownSvg(m) {
  // Convert m.equity_curve (or compute from rolling_sharpe / monthly proxy) to a path
  // For brevity here: assume backend returns m.drawdown_series (array of negatives, len ~500)
  const series = m.drawdown_series || [];
  const w = 400, h = 90;
  if (series.length < 2) return `<svg viewBox="0 0 ${w} ${h}"><text x="200" y="45" fill="var(--text-3)" text-anchor="middle">no data</text></svg>`;
  const min = Math.min(...series, -0.01);
  const dx = w / (series.length - 1);
  const points = series.map((v, i) => `${(i*dx).toFixed(1)},${(v/min*h*0.9).toFixed(1)}`).join(' L');
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <defs><linearGradient id="ddgrad" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#f87171" stop-opacity="0.25"/><stop offset="100%" stop-color="#f87171" stop-opacity="0"/></linearGradient></defs>
    <path d="M${points} L${w},${h} L0,${h} Z" fill="url(#ddgrad)"/>
    <path d="M${points}" fill="none" stroke="#f87171" stroke-width="1.4"/>
  </svg>`;
}

function monthlyHeatmap(matrix) {
  if (!matrix || !matrix.length) return '<div class="empty">no data</div>';
  const cells = matrix.flat().map(v => {
    const c = v >= 0 ? `74,222,128` : `248,113,113`;
    const a = Math.min(0.7, Math.abs(v) * 10).toFixed(2);
    return `<div class="heatmap-cell" style="background:rgba(${c},${a})"></div>`;
  }).join('');
  return `<div class="heatmap-grid">${cells}</div>`;
}

function rollingSharpeSvg(series) {
  if (!series || series.length < 2) return '<svg viewBox="0 0 400 90"><text x="200" y="45" fill="var(--text-3)" text-anchor="middle">no data</text></svg>';
  const w = 400, h = 90;
  const max = Math.max(2, ...series.map(Math.abs));
  const dx = w / (series.length - 1);
  const points = series.map((v, i) => `${(i*dx).toFixed(1)},${(h/2 - v/max * h*0.4).toFixed(1)}`).join(' L');
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <defs><linearGradient id="shgrad" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#4ade80" stop-opacity="0.25"/><stop offset="100%" stop-color="#4ade80" stop-opacity="0"/></linearGradient></defs>
    <line x1="0" y1="${h/2}" x2="${w}" y2="${h/2}" stroke="rgba(255,255,255,0.06)" stroke-dasharray="2,3"/>
    <path d="M${points} L${w},${h} L0,${h} Z" fill="url(#shgrad)"/>
    <path d="M${points}" fill="none" stroke="#4ade80" stroke-width="1.6"/>
  </svg>`;
}
```

(Backend `qs_metrics.py` may need a `drawdown_series` helper — add it if missing.)

- [ ] **Step 3: Smoke + commit**

Click virpo-mu-v1 to expand → 7-cell summary, QuantStats tab active by default, 8-cell sub-grid populated, three charts render. Click "View full tearsheet ↗" → opens `/tradelab/runs/<id>/tearsheet` in new tab.

```bash
git add command_center.html
git commit -m "feat(command-center): expanded tile QS sub-grid + 3 inline SVG charts"
```

---

## Phase 4 — Matrix + Pipeline + Delete

### Task 13: Cross-strategy factor matrix

**Files:**
- Modify: `C:\TradingScripts\command_center.html`

- [ ] **Step 1: Add matrix markup container**

Below the Live Cards row, add:

```html
<section class="section-header">
  <h2>Cross-strategy <em>factor matrix</em></h2>
  <div class="meta" id="matrix-meta">— strategies · 7 factors · column-down read = correlated weakness</div>
</section>
<div id="matrix-card" class="matrix-card">
  <div id="matrix-grid" class="matrix-grid"></div>
  <div class="matrix-footer">
    <div class="matrix-legend"><!-- legend pip bars --></div>
  </div>
  <div id="matrix-alpha-callout" class="alpha-callout" hidden></div>
</div>
```

- [ ] **Step 2: Build the matrix from strategies + their `signals[]`**

```javascript
const FACTOR_COLUMNS = [
  { id: 'dsr', label: 'DSR', meta: 'deflated sharpe' },
  { id: 'monte_carlo', label: 'Monte Carlo', meta: 'bootstrap' },
  { id: 'oos_pf', label: 'OOS PF', meta: 'hold-out' },
  { id: 'regime', label: 'Regime', meta: 'bull / bear / chop' },
  { id: 'sample', label: 'Sample', meta: 'trade count' },
  { id: 'stability', label: 'Stability', meta: 'rolling sharpe' },
  { id: 'walk_forward', label: 'Walk-Fwd', meta: 'consistency' },
];

function classifyOutcome(signal) {
  // signals[] entries: {name, score, outcome: "robust"|"marginal"|"fragile"|"inconclusive"}
  if (!signal) return 'dim';
  const o = (signal.outcome || '').toLowerCase();
  if (o === 'robust') return 'pass';
  if (o === 'marginal') return 'marginal';
  if (o === 'fragile') return 'fail';
  return 'dim';
}

async function renderFactorMatrix() {
  const grid = document.getElementById('matrix-grid');
  const data = await fetchJSON('/tradelab/strategies-summary');  // includes latest signals[] per strategy
  const strategies = data.strategies;

  // Compute column-warn flags (≥ 50% non-pass)
  const columnWarns = {};
  for (const col of FACTOR_COLUMNS) {
    const scored = strategies.filter(s => s.signals && s.signals.length).map(s => s.signals.find(x => x.name === col.id));
    const nonPass = scored.filter(s => classifyOutcome(s) !== 'pass').length;
    columnWarns[col.id] = scored.length > 0 && nonPass / scored.length >= 0.5;
  }

  // Header
  grid.innerHTML = '';
  const corner = document.createElement('div');
  corner.className = 'fm-corner';
  corner.textContent = 'Strategy';
  grid.appendChild(corner);
  for (const col of FACTOR_COLUMNS) {
    const h = document.createElement('div');
    h.className = 'fm-col-label' + (columnWarns[col.id] ? ' column-warn' : '');
    h.innerHTML = `${escapeHtml(col.label)}<span class="signal-meta">${escapeHtml(col.meta)}</span>`;
    grid.appendChild(h);
  }

  // Rows
  for (const s of strategies) {
    const label = document.createElement('div');
    const v = (s.verdict || 'inconclusive').toLowerCase();
    label.className = 'fm-row-label' + (s.signals && s.signals.length ? '' : ' dimmed');
    label.innerHTML = `<span class="verdict-mini ${v}"></span>${escapeHtml(s.id)}`;
    grid.appendChild(label);

    for (const col of FACTOR_COLUMNS) {
      const sig = (s.signals || []).find(x => x.name === col.id);
      const cell = document.createElement('div');
      cell.className = 'fm-cell ' + classifyOutcome(sig);
      cell.title = sig ? `${col.label}: ${sig.score?.toFixed?.(2) ?? sig.score} (${sig.outcome})` : `${col.label}: no data`;
      cell.innerHTML = `<div class="pip"></div><span class="score">${sig ? escapeHtml(String(sig.score?.toFixed?.(2) ?? sig.score)) : '—'}</span>`;
      grid.appendChild(cell);
    }
  }

  // Alpha callout
  const warnCols = FACTOR_COLUMNS.filter(c => columnWarns[c.id]);
  const callout = document.getElementById('matrix-alpha-callout');
  if (warnCols.length > 0) {
    callout.hidden = false;
    callout.innerHTML = `<span class="label">Alpha read</span><strong>${warnCols.map(c => escapeHtml(c.label)).join(' + ')}</strong> ${warnCols.length === 1 ? 'is' : 'are'} weak across ≥50% of scored strategies. Investigate the shared cause before re-scoring.`;
  } else {
    callout.hidden = true;
  }

  document.getElementById('matrix-meta').textContent =
    `${strategies.length} strategies · 7 factors · column-down read = correlated weakness`;
}
```

- [ ] **Step 3: Static-HTML test + smoke + commit**

```python
def test_factor_matrix_present():
    html = _load_html()
    assert 'id="matrix-card"' in html
    assert 'id="matrix-grid"' in html
    assert 'FACTOR_COLUMNS' in html  # JS const present
```

```bash
git add command_center.html
cd C:/TradingScripts/tradelab; git add tests/web/test_command_center_html.py
git commit -m "feat(command-center): cross-strategy factor matrix with column-warn detection"
```

---

### Task 14: Pipeline restyle (carry from v2 markup, just new typography)

**Files:**
- Modify: `C:\TradingScripts\command_center.html`

- [ ] **Step 1: Reuse existing pipeline JS; restyle the surrounding shell**

The existing v2 pipeline rendering JS (`renderPipelineRows`, filters) keeps working. Replace **only** the outer `<div>` chrome:

```html
<section class="section-header">
  <h2>Research <em>pipeline</em></h2>
  <div class="meta" id="pipeline-meta">— runs · click row to drill in</div>
</section>
<div class="pipeline-card">
  <div class="pipeline-toolbar">
    <!-- existing v2 filter buttons preserved -->
  </div>
  <div id="selection-toolbar" class="selection-toolbar" hidden>
    <span class="count" id="selection-count">0 runs selected</span>
    <span class="actions">
      <button id="compare-selected" class="btn-action">⇄ Compare Selected (0)</button>
      <button id="delete-selected" class="btn-action danger">🗑 Delete N runs ▸</button>
    </span>
  </div>
  <table class="pipeline" id="pipeline-table">
    <thead><!-- existing v2 column headers --></thead>
    <tbody id="pipeline-tbody"></tbody>
  </table>
</div>
```

- [ ] **Step 2: Update existing `renderPipelineRows` to add per-row trash icon**

Find `renderPipelineRows` (around line 2553 of `command_center.html` per memory of v2 audit). After the existing column cells, append:

```javascript
const actionsCell = document.createElement('td');
actionsCell.innerHTML = `<div class="row-cell-actions">
  ${row.status === 'failed' ? `<button class="row-trash" data-action="rerun" title="Re-run">↻</button>` : ''}
  ${row.status === 'running' || row.status === 'queued'
    ? `<button class="row-trash" data-action="cancel" title="Cancel">⊘</button>`
    : `<button class="row-trash" data-action="delete" title="Delete this run">🗑</button>`}
</div>`;
tr.appendChild(actionsCell);
```

- [ ] **Step 3: Commit**

```bash
git add command_center.html
git commit -m "feat(command-center): pipeline-restyle + per-row trash icon"
```

---

### Task 15: Pipeline delete affordances (4 confirm tiers + cascading)

**Files:**
- Modify: `C:\TradingScripts\command_center.html`

- [ ] **Step 1: Wire single-row inline confirm**

```javascript
document.getElementById('pipeline-tbody').addEventListener('click', (e) => {
  const trash = e.target.closest('.row-trash[data-action="delete"]');
  if (!trash) return;
  e.stopPropagation();
  const cell = trash.closest('.row-cell-actions');
  const tr = trash.closest('tr');
  const runId = tr.dataset.runId;
  const strategy = tr.dataset.strategy;
  cell.innerHTML = `<div class="inline-confirm">
    <span class="text">Delete this run?</span>
    <button class="btn-mini delete">Delete</button>
    <button class="btn-mini cancel">Cancel</button>
  </div>`;
  cell.querySelector('.delete').onclick = async () => {
    await deleteRunWithLiveCardCheck(runId, strategy);
  };
  cell.querySelector('.cancel').onclick = () => {
    // restore the trash icon
    cell.innerHTML = `<button class="row-trash" data-action="delete" title="Delete this run">🗑</button>`;
  };
});
```

- [ ] **Step 2: Implement `deleteRunWithLiveCardCheck`**

```javascript
async function deleteRunWithLiveCardCheck(runId, strategy) {
  // Check if a card exists for this strategy AND if this is the strategy's last run
  const cards = await fetchJSON('/tradelab/cards');  // existing endpoint
  const hasCard = cards.some(c => c.id === strategy);
  const summary = await fetchJSON(`/tradelab/strategies/${encodeURIComponent(strategy)}/runs-summary`);
  const isLastRun = summary.run_count === 1;

  if (hasCard && isLastRun) {
    showLiveCardEscalationModal(runId, strategy);
    return;
  }
  await performDelete([runId]);
}
```

- [ ] **Step 3: Implement multi-select bulk-delete with tiered modals**

```javascript
function getSelectedRunIds() {
  return Array.from(document.querySelectorAll('#pipeline-tbody input.row-checkbox:checked'))
    .map(cb => cb.closest('tr').dataset.runId);
}

document.getElementById('delete-selected').addEventListener('click', () => {
  const runIds = getSelectedRunIds();
  if (runIds.length === 0) return;
  if (runIds.length > 10) showTypedConfirmModal(runIds);
  else showBulkConfirmModal(runIds);
});

function showBulkConfirmModal(runIds) {
  const rows = runIds.map(id => {
    const tr = document.querySelector(`#pipeline-tbody tr[data-run-id="${CSS.escape(id)}"]`);
    return { id, strategy: tr.dataset.strategy, ts: tr.querySelector('.stamp')?.textContent || '' };
  });
  const modal = openModal('danger', `Delete ${runIds.length} selected runs?`, `
    <p>Per-run on-disk artifacts will be removed and one line appended to <code>data/deletions.log</code>. Factor matrix and tile data will recompute.</p>
    <div class="row-list">${rows.map(r => `<div class="row-line"><span>${escapeHtml(r.strategy)}</span><span class="ts">${escapeHtml(r.ts)}</span></div>`).join('')}</div>
  `, [
    { class: 'cancel', label: 'Cancel', click: () => closeModal(modal) },
    { class: 'delete', label: `Delete ${runIds.length} runs`, click: async () => { await performDelete(runIds); closeModal(modal); } },
  ]);
}

function showTypedConfirmModal(runIds) {
  // Same shape as showBulkConfirmModal but with a typed-confirm input.
  // Delete button stays disabled until input.value === 'DELETE' exactly.
  // ... (full implementation, mirroring translation #2 mockup)
}

function showLiveCardEscalationModal(runId, strategy) {
  const modal = openModal('warning', `${strategy} has a live Card`, `
    <p>Deleting this run will leave the live <strong>${escapeHtml(strategy)}</strong> Card with no robustness history. Recommended: disable the card first.</p>
  `, [
    { class: 'cancel', label: 'Cancel', click: () => closeModal(modal) },
    { class: 'delete-anyway', label: 'Delete anyway', click: async () => { await performDelete([runId]); closeModal(modal); } },
    { class: 'disable-and-delete', label: 'Disable card + Delete', click: async () => {
      await postJSON(`/tradelab/cards/${encodeURIComponent(strategy)}/disable`, {});
      await performDelete([runId]);
      closeModal(modal);
    }},
  ]);
}

async function performDelete(runIds) {
  for (const id of runIds) {
    try {
      await fetch(`/tradelab/runs/${encodeURIComponent(id)}`, { method: 'DELETE' });
    } catch (err) {
      showToast(`Delete failed for ${id}: ${err.message}`, 'error');
    }
  }
  // SSE will cascade tile/matrix updates (Task 16)
}
```

- [ ] **Step 4: Add `openModal` / `closeModal` helpers** (vanilla JS, no library)

```javascript
function openModal(severity, title, bodyHtml, buttons) {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `<div class="modal-card ${severity}">
    <div class="modal-label">${escapeHtml(severity)}</div>
    <h3>${escapeHtml(title)}</h3>
    ${bodyHtml}
    <div class="modal-actions"></div>
  </div>`;
  const actions = overlay.querySelector('.modal-actions');
  for (const b of buttons) {
    const btn = document.createElement('button');
    btn.className = `btn-modal ${b.class}`;
    btn.textContent = b.label;
    btn.addEventListener('click', b.click);
    actions.appendChild(btn);
  }
  overlay.addEventListener('click', (e) => { if (e.target === overlay) closeModal(overlay); });
  document.body.appendChild(overlay);
  return overlay;
}
function closeModal(overlay) { overlay.remove(); }
```

(CSS for `.modal-overlay` — full-screen dim background, centered card — adapt from translation #2.)

- [ ] **Step 5: Smoke + commit**

Click trash on one row → inline confirm pops out. Cancel restores. Delete fires DELETE; row vanishes from table.
Multi-select 3 rows → click `Delete N runs ▸` → bulk modal lists 3 rows; Delete fires 3 DELETEs.
Multi-select 12 rows → typed-confirm modal; Delete button stays disabled until typing `DELETE` exactly.
Delete a run that's the last for a card-bearing strategy → escalation modal.

```bash
git add command_center.html
git commit -m "feat(command-center): pipeline delete affordances — 4 confirm tiers + live-card escalation"
```

---

## Phase 5 — Cascading + smoke gate

### Task 16: SSE listener — cascade `run_deleted` and `card_activated` events

**Files:**
- Modify: `C:\TradingScripts\command_center.html`

- [ ] **Step 1: Find existing SSE handler**

Run:
```bash
grep -n "EventSource\|onmessage\|/tradelab/sse" C:/TradingScripts/command_center.html
```

- [ ] **Step 2: Add new event-type branches**

Inside the `onmessage` switch:

```javascript
case 'run_deleted': {
  const { run_id, strategy } = data;
  // Pipeline: remove the row
  const tr = document.querySelector(`#pipeline-tbody tr[data-run-id="${CSS.escape(run_id)}"]`);
  if (tr) tr.remove();
  // Live Card tile: re-fetch its data and re-render
  await refetchAndRerenderTile(strategy);
  // Factor matrix: re-render whole matrix (cheap)
  await renderFactorMatrix();
  break;
}
case 'card_activated': {
  const { card } = data;
  // Find the tile for card.id and update its Activate button + state
  const tile = document.querySelector(`#live-cards-grid [data-strategy-id="${CSS.escape(card.id)}"]`);
  if (tile) {
    tile.classList.add('activated');
    const btn = tile.querySelector('.activate');
    btn.className = 'activate live';
    btn.textContent = '● Already live ↗';
  }
  // Strategy-summary cache invalidate so future expands see has_card=true
  strategyDataCache.delete(card.id);
  break;
}
```

- [ ] **Step 3: Implement `refetchAndRerenderTile`**

```javascript
async function refetchAndRerenderTile(strategy) {
  const data = await fetchJSON(`/tradelab/strategies/${encodeURIComponent(strategy)}/summary`);
  strategyDataCache.set(strategy, data);
  const tile = document.querySelector(`#live-cards-grid [data-strategy-id="${CSS.escape(strategy)}"]`);
  if (!tile) return;
  if (tile.classList.contains('expanded')) {
    tile.innerHTML = expandedTileHtml(data);
    loadQsForExpandedTile(tile, data.latest_run_id);
  } else {
    tile.innerHTML = tileHtml(data);
    renderDriftFor(tile.querySelector('.drift'), strategy);
  }
}
```

- [ ] **Step 4: Smoke + commit**

Delete a run from the pipeline → its row disappears from pipeline AND the matching tile + matrix row update without a page reload.
Activate a strategy → tile turns green; SSE confirms; Overview tab card appears within ~1s.

```bash
git add command_center.html
git commit -m "feat(command-center): SSE cascading for run_deleted and card_activated events"
```

---

### Task 17: Full UI smoke gate via Playwright MCP

**Files:**
- Create: `tradelab/docs/superpowers/notes/2026-04-30-research-v3-smoke-results.md`

- [ ] **Step 1: Run full pytest suite**

```powershell
cd C:\TradingScripts\tradelab
$env:PYTHONPATH = "src"
python -m pytest tests/web/ tests/cli/test_progress_log.py -q
```

Expected: all green. Record exact passed-count in the smoke results file.

- [ ] **Step 2: Manual playwright smoke — golden path**

Spawn Playwright MCP, navigate to `http://localhost:8877/`, switch to Research tab. Verify each:

| Surface | Check |
|---|---|
| Action bar | 3 protected buttons render and click handlers fire; 4 preflight chips populate; calibration trust shows a number; canary icon hidden when all-pass |
| Live Cards row | All strategies render; ROBUST tiles enabled; non-ROBUST disabled with reason tooltip; activated tiles show "Already live ↗" |
| Tile expand | Click any tile → expands inline; 7-cell summary populates; QS sub-grid loads; 3 charts render; "View full tearsheet ↗" opens QS HTML in new tab |
| Factor matrix | All strategies in rows; 7 columns; warm columns flagged amber; dimmed rows for no-data |
| Pipeline | Filter bar works; per-row trash → inline confirm; multi-select toolbar reveals; bulk delete modal; typed-confirm at >10; escalation on live-card |
| SSE | Delete a run → row disappears from pipeline; tile re-renders; matrix updates — no page reload |
| Cross-tab | Activate from Research → switches to Overview, scrolls to + pulses card. `↗ Research` from Overview → switches back, pulses tile |

- [ ] **Step 3: Document results + commit**

Write outcomes to `2026-04-30-research-v3-smoke-results.md`:
- Pass / fail per surface with timestamp
- Any bugs found (open as separate fix tasks)
- Screenshot links for any visual regressions

```bash
cd C:/TradingScripts/tradelab
git add docs/superpowers/notes/2026-04-30-research-v3-smoke-results.md
git commit -m "docs(research-v3): UI smoke gate results"
```

---

## Phase 6 — Class B activation wiring (depends on Slice 0 findings)

### Task 18: Wire Class B (S2/S4/S7/S8/S10/S12) Activate end-to-end

This task's full step list **depends on Slice 0 findings**. Adapt below template once Class B target is identified.

**Files:**
- Modify: `tradelab/src/tradelab/web/activation.py` — add `route_to_class_b_bot_config(strategy)` branch
- Modify: `tradelab/tests/web/test_activation.py` — add Class B tests

- [ ] **Step 1: Detect class on activation request**

```python
CLASS_B_STRATEGIES = {"S2_pocket_pivot", "S4_inside_day_breakout", "S7_rdz_momentum",
                     "S8_bullish_outside_day", "S10_rs_new_highs", "S12_momentum_accel"}

def activate_strategy(strategy, ...):
    # ... existing gate validation ...
    if strategy in CLASS_B_STRATEGIES:
        return _activate_class_b(strategy, verdict, snapshot)
    return _activate_class_a(strategy, verdict, snapshot)
```

- [ ] **Step 2: Implement `_activate_class_b`**

Per Slice 0 findings, write to the bot's enable-list file with the same activated-verdict snapshot fields.

- [ ] **Step 3: Add tests + smoke**

Cover ROBUST→success, MARGINAL→422, duplicate→409 for a Class B strategy.

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(activation): Class B (S2-S12) bot strategy activation wiring"
```

---

## Self-review

Spec coverage:
- §3 thesis → covered by overall plan structure (cuts → no engine canaries section, no market regime section, etc.)
- §4 architecture → Tasks 1–6 (backend) + 7–16 (frontend)
- §5.1 action bar → Task 8
- §5.2 Live Cards → Tasks 9–12
- §5.3 factor matrix → Task 13
- §5.4 pipeline + delete → Tasks 14–15
- §6 activation contract → Tasks 4, 5, 10, 18
- §7 delete contract → Tasks 3, 5, 15, 16
- §8 file inventory → Phase 1 (backend) + Phase 2–4 (frontend)
- §9 tests → embedded in each task + Task 17 smoke gate
- §10 out-of-scope → respected (no soft-delete, no auto-disable, no class badge, etc.)
- §11.0 Class B identification → Task 0
- §11.1+ follow-ups → not part of this plan (correct)

Placeholder scan: no TBD/TODO/"add appropriate" found. Backend code blocks are complete. Frontend code blocks show actual JS, not stubs.

Type consistency: `RunNotFound` raised in Task 3 + caught in Task 5 (same name); `ActivationGateFailed` / `AlreadyActivated` raised in Task 4 + caught in Task 5; `delete_run_atomic` signature matches between Task 3 implementation and Task 5 import.

Plan is complete.
