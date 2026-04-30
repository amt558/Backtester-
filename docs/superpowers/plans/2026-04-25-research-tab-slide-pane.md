# Research Tab — Table + Slide-in Pane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Research tab's two-source layout (Active Jobs panel + Pipeline table) with a single Pipeline table that merges in-flight jobs and completed audit-DB rows, plus a slide-in detail pane and first-class delete (soft-archive) affordances.

**Architecture (Path A — frontend-merge, design-respecting):**
The audit DB `runs` table stays append-only (per its docstring contract). A new sidecar table `archived_runs` records user-archived run_ids; queries filter at JOIN time. Job lifecycle continues to live in `JobManager` (`.cache/jobs.json`) as today — the dashboard frontend merges JobManager state + audit-DB rows into one Pipeline. Active Jobs panel is removed; SSE updates rewire to update Pipeline rows in place. A 360px slide-in pane gives strategy-centric depth on row click.

**Tech Stack:** Python 3 stdlib (sqlite3, http.server, json), pandas (existing dep), pytest, vanilla JavaScript + CSS, no new dependencies.

**Source spec:** `docs/superpowers/specs/2026-04-25-research-tab-slide-pane-design.md` — note that the spec was drafted before code investigation; this plan supersedes it where it diverges. Notable divergences: no audit DB schema migration (append-only honored), no new lifecycle write path (JobManager already does this), delete is soft-archive (folder removed, run row preserved), all five existing JobStatus states accepted (spec missed `INTERRUPTED`).

**Estimated effort:** ~6 days, 14 tasks, ~14 commits.

---

## File structure

### New files

```
tradelab/src/tradelab/audit/archive.py            ~80 LOC — sidecar table + helpers
tradelab/tests/audit/test_archive.py              ~120 LOC — unit tests
tradelab/tests/web/test_runs_delete.py            ~90 LOC — single-delete endpoint tests
tradelab/tests/web/test_runs_bulk_delete.py       ~80 LOC — bulk-delete endpoint tests
tradelab/tests/web/test_strategy_history.py       ~70 LOC — history endpoint tests
tradelab/tests/web/test_runs_merged.py            ~100 LOC — merged /tradelab/runs tests
```

### Modified files

```
tradelab/src/tradelab/web/audit_reader.py         add exclude_archived param to list_runs / count_runs + new history_for_strategy
tradelab/src/tradelab/web/handlers.py             add DELETE dispatcher, 3 new routes, modified /tradelab/runs handler
C:/TradingScripts/launch_dashboard.py             wire do_DELETE method
C:/TradingScripts/command_center.html             remove Active Jobs section, add Status column + action strip + slide-in pane + delete buttons + Reset Filters rename
```

### Backup files (created by Task 0, never committed)

```
C:/TradingScripts/command_center.html.bak-2026-04-25
```

---

## Setup notes

**Worktree (optional but recommended).** The brainstorming skill suggests doing implementation work in an isolated worktree. To set one up before starting:

```bash
cd C:/TradingScripts/tradelab
git worktree add ../tradelab-research-pane feat/research-slide-pane master
cd ../tradelab-research-pane
```

If you skip the worktree, work directly on `feat/research-slide-pane` branched from `master` in the existing checkout. The `command_center.html` lives at `C:/TradingScripts/`, NOT inside the tradelab repo — that file is edited in place either way.

**Baseline state at plan start (verified 2026-04-25):**
- `master` is 45 commits ahead of `origin/master`
- Last commit: `cb2e1c6 fix(web): _cards_path must be repo-root-relative`
- Pytest baseline: 378 passed, 3 pre-existing failures (per `OPTION_H_SESSION_3A_COMPLETE_2026-04-24.md`)

---

## Task 0: Baseline & backup (no commit)

**Files:**
- Backup: `C:/TradingScripts/command_center.html.bak-2026-04-25`

- [ ] **Step 1: Confirm working tree is clean except expected drift**

```bash
cd C:/TradingScripts/tradelab && git status
```

Expected: clean (no uncommitted changes), or only unrelated drift. If unexpected modifications appear, stop and ask the user before proceeding.

- [ ] **Step 2: Create branch (skip if you already created the worktree)**

```bash
cd C:/TradingScripts/tradelab && git checkout -b feat/research-slide-pane
```

Expected: `Switched to a new branch 'feat/research-slide-pane'`

- [ ] **Step 3: Run baseline pytest, capture pass count**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/ -x --tb=no -q 2>&1 | tail -20
```

Expected: ~378 passed, ~3 pre-existing failures. Record the exact pass count for Task 14 comparison.

- [ ] **Step 4: Backup the dashboard HTML**

```bash
cp C:/TradingScripts/command_center.html C:/TradingScripts/command_center.html.bak-2026-04-25
ls -la C:/TradingScripts/command_center.html.bak-2026-04-25
```

Expected: backup file present, same size as original.

(No commit for setup task.)

---

## Task 1: archived_runs sidecar table

**Files:**
- Create: `tradelab/src/tradelab/audit/archive.py`
- Test: `tradelab/tests/audit/test_archive.py`

- [ ] **Step 1: Write failing tests**

Create `tradelab/tests/audit/test_archive.py`:

```python
"""Unit tests for archived_runs sidecar.

The audit DB runs table is append-only (per audit/history.py docstring).
This sidecar is the user-archive layer that consumers filter against at
query time. It does NOT modify the runs table.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tradelab.audit import archive


def test_archive_run_creates_table_and_inserts_row(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    archive.archive_run("run-abc", db_path=db)

    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute("SELECT run_id, reason FROM archived_runs").fetchall()
    finally:
        conn.close()

    assert rows == [("run-abc", None)]


def test_archive_run_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    archive.archive_run("run-abc", db_path=db)
    archive.archive_run("run-abc", db_path=db)  # second call is a no-op

    conn = sqlite3.connect(str(db))
    try:
        count = conn.execute("SELECT COUNT(*) FROM archived_runs").fetchone()[0]
    finally:
        conn.close()

    assert count == 1


def test_archive_run_records_reason(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    archive.archive_run("run-abc", reason="user_delete", db_path=db)
    assert archive.is_archived("run-abc", db_path=db)


def test_is_archived_false_when_db_missing(tmp_path: Path) -> None:
    db = tmp_path / "missing.db"
    assert archive.is_archived("anything", db_path=db) is False


def test_is_archived_false_for_unknown_run_id(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    archive.archive_run("run-abc", db_path=db)
    assert archive.is_archived("run-xyz", db_path=db) is False


def test_list_archived_run_ids_returns_set(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    archive.archive_run("run-1", db_path=db)
    archive.archive_run("run-2", db_path=db)
    archive.archive_run("run-3", db_path=db)

    ids = archive.list_archived_run_ids(db_path=db)
    assert ids == {"run-1", "run-2", "run-3"}


def test_list_archived_run_ids_empty_when_db_missing(tmp_path: Path) -> None:
    db = tmp_path / "missing.db"
    assert archive.list_archived_run_ids(db_path=db) == set()
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/audit/test_archive.py -v 2>&1 | tail -20
```

Expected: `ModuleNotFoundError: No module named 'tradelab.audit.archive'` (file doesn't exist yet).

- [ ] **Step 3: Implement the module**

Create `tradelab/src/tradelab/audit/archive.py`:

```python
"""Sidecar for soft-archiving audit runs.

The runs table is append-only by design (see audit/history.py docstring:
"There is no `delete` or `mark_invalid` path; filter at query time if
needed."). This module is the "filter at query time" mechanism: it records
which run_ids the user has hidden so the dashboard can exclude them from
default queries. The runs row itself stays immutable.

The companion report folder (on disk) IS removed when archive_run is called
from the dashboard's delete endpoint — folders are disposable artifacts,
not historical record. This module does not touch the filesystem; the
caller (web/handlers.py) handles folder removal.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .history import DEFAULT_DB_PATH


_SCHEMA = """
CREATE TABLE IF NOT EXISTS archived_runs (
    run_id      TEXT PRIMARY KEY,
    archived_at TEXT NOT NULL,
    reason      TEXT
);
CREATE INDEX IF NOT EXISTS idx_archived_at ON archived_runs(archived_at);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_SCHEMA)
    return conn


def archive_run(
    run_id: str,
    *,
    reason: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> None:
    """Record run_id as archived. Idempotent — re-archiving is a no-op."""
    db = Path(db_path) if db_path else DEFAULT_DB_PATH
    conn = _connect(db)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO archived_runs (run_id, archived_at, reason) "
            "VALUES (?, ?, ?)",
            (run_id, datetime.now(timezone.utc).isoformat(), reason),
        )
        conn.commit()
    finally:
        conn.close()


def is_archived(run_id: str, *, db_path: Optional[Path] = None) -> bool:
    db = Path(db_path) if db_path else DEFAULT_DB_PATH
    if not db.exists():
        return False
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT 1 FROM archived_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def list_archived_run_ids(*, db_path: Optional[Path] = None) -> set[str]:
    """Return the set of all archived run_ids. Empty set if DB missing."""
    db = Path(db_path) if db_path else DEFAULT_DB_PATH
    if not db.exists():
        return set()
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute("SELECT run_id FROM archived_runs").fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/audit/test_archive.py -v 2>&1 | tail -20
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/audit/archive.py tests/audit/test_archive.py
git commit -m "feat(audit): add archived_runs sidecar table

Honors the runs table's append-only contract by recording user-archived
run_ids in a separate table that consumers filter against at query time.
The runs row itself stays immutable.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Wire do_DELETE in launch_dashboard.py

**Files:**
- Modify: `C:/TradingScripts/launch_dashboard.py` — add `do_DELETE` method that dispatches to `handlers.handle_delete_with_status`

The existing handler dispatcher only routes GET and POST. We need DELETE for the new run-archive endpoint.

- [ ] **Step 1: Read existing do_GET / do_POST to match the pattern**

```bash
sed -n '80,140p' C:/TradingScripts/launch_dashboard.py
```

Note the response-write pattern (status code, headers, body) used in do_GET / do_POST.

- [ ] **Step 2: Add do_DELETE method that dispatches to a new `handle_delete_with_status`**

In `C:/TradingScripts/launch_dashboard.py`, add a new method to the request handler class (immediately after `do_POST`):

```python
def do_DELETE(self):
    """Dispatch DELETE requests to the tradelab handler."""
    parsed = urlparse(self.path)
    path = parsed.path

    if not path.startswith("/tradelab/"):
        self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":false,"error":"not found"}')
        return

    try:
        from tradelab.web.handlers import handle_delete_with_status
        body, status = handle_delete_with_status(path)
    except Exception as e:
        import traceback
        traceback.print_exc()
        self.send_response(500)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(f'{{"ok":false,"error":"{type(e).__name__}"}}'.encode())
        return

    self.send_response(status)
    self.send_header("Content-Type", "application/json")
    self.end_headers()
    if body:
        self.wfile.write(body.encode())
```

- [ ] **Step 3: Add a placeholder `handle_delete_with_status` to handlers.py so do_DELETE doesn't ImportError**

In `tradelab/src/tradelab/web/handlers.py`, append at the end of the file:

```python
def handle_delete_with_status(path: str) -> tuple[str, int]:
    """DELETE dispatcher with explicit status. Routes added in Task 3."""
    return _err("not found"), 404
```

- [ ] **Step 4: Smoke check the dashboard still starts**

```bash
cd C:/TradingScripts && python launch_dashboard.py --port 18877 &
sleep 2
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE http://127.0.0.1:18877/tradelab/runs/anything
# Expected: 404
kill %1
```

Expected: 404 from the placeholder. (Skip this step on Windows; verify by manual launch instead.)

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/web/handlers.py
git commit -m "chore(web): add handle_delete_with_status placeholder

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"

cd C:/TradingScripts && git add launch_dashboard.py
git commit -m "chore(dashboard): wire do_DELETE method"
```

(`launch_dashboard.py` lives outside the tradelab repo — commit in the parent repo.)

---

## Task 3: DELETE /tradelab/runs/<run_id> endpoint

**Files:**
- Modify: `tradelab/src/tradelab/web/handlers.py` — extend `handle_delete_with_status`
- Test: `tradelab/tests/web/test_runs_delete.py`

Behavior: archive the run_id (insert into archived_runs sidecar) AND remove its report folder. Both succeed → 204. Folder removal failure (file lock, permission) → 409, archive insert is rolled back. Unknown run_id → 404.

- [ ] **Step 1: Write failing tests**

Create `tradelab/tests/web/test_runs_delete.py`:

```python
"""Tests for DELETE /tradelab/runs/<run_id>.

Verifies soft-archive semantics: the runs table is never modified;
archived_runs receives the row; the report folder is removed.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tradelab.audit import archive
from tradelab.web import handlers


def _seed_run(db: Path, run_id: str, report_folder: str) -> None:
    """Insert a runs row pointing at report_folder."""
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                timestamp_utc TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                report_card_html_path TEXT
            );
        """)
        conn.execute(
            "INSERT INTO runs (run_id, timestamp_utc, strategy_name, report_card_html_path) "
            "VALUES (?, ?, ?, ?)",
            (run_id, "2026-04-25T00:00:00Z", "S2", report_folder),
        )
        conn.commit()
    finally:
        conn.close()


def test_delete_unknown_returns_404(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "history.db"
    _seed_run(db, "run-known", str(tmp_path / "reports" / "known"))
    monkeypatch.setattr(handlers, "_db_path", lambda: db)
    monkeypatch.setattr(handlers, "_reports_root", lambda: tmp_path / "reports")

    body, status = handlers.handle_delete_with_status("/tradelab/runs/run-unknown")
    assert status == 404
    assert "not found" in body.lower()


def test_delete_success_archives_and_removes_folder(tmp_path: Path, monkeypatch) -> None:
    folder = tmp_path / "reports" / "s2_run"
    folder.mkdir(parents=True)
    (folder / "dashboard.html").write_text("<html></html>")
    db = tmp_path / "history.db"
    _seed_run(db, "run-1", str(folder))
    monkeypatch.setattr(handlers, "_db_path", lambda: db)
    monkeypatch.setattr(handlers, "_reports_root", lambda: tmp_path / "reports")

    body, status = handlers.handle_delete_with_status("/tradelab/runs/run-1")
    assert status == 204
    assert not folder.exists()
    assert archive.is_archived("run-1", db_path=db)


def test_delete_runs_table_row_preserved(tmp_path: Path, monkeypatch) -> None:
    """Audit DB runs row must NOT be modified — only archived_runs gets the entry."""
    folder = tmp_path / "reports" / "s2_run"
    folder.mkdir(parents=True)
    db = tmp_path / "history.db"
    _seed_run(db, "run-1", str(folder))
    monkeypatch.setattr(handlers, "_db_path", lambda: db)
    monkeypatch.setattr(handlers, "_reports_root", lambda: tmp_path / "reports")

    handlers.handle_delete_with_status("/tradelab/runs/run-1")

    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT run_id, strategy_name FROM runs WHERE run_id = ?", ("run-1",)
        ).fetchone()
    finally:
        conn.close()
    assert row == ("run-1", "S2")  # row still there, untouched


def test_delete_idempotent_on_second_call(tmp_path: Path, monkeypatch) -> None:
    """Second delete returns 204 (folder already gone, archive row already there)."""
    folder = tmp_path / "reports" / "s2_run"
    folder.mkdir(parents=True)
    db = tmp_path / "history.db"
    _seed_run(db, "run-1", str(folder))
    monkeypatch.setattr(handlers, "_db_path", lambda: db)
    monkeypatch.setattr(handlers, "_reports_root", lambda: tmp_path / "reports")

    body1, status1 = handlers.handle_delete_with_status("/tradelab/runs/run-1")
    body2, status2 = handlers.handle_delete_with_status("/tradelab/runs/run-1")
    assert status1 == 204
    assert status2 == 204  # idempotent
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/web/test_runs_delete.py -v 2>&1 | tail -30
```

Expected: 4 tests, all fail (`handle_delete_with_status` returns 404 placeholder for everything).

- [ ] **Step 3: Implement the route in `handlers.py`**

Replace the placeholder `handle_delete_with_status` at the end of `tradelab/src/tradelab/web/handlers.py` with:

```python
def handle_delete_with_status(path: str) -> tuple[str, int]:
    """DELETE dispatcher with explicit status."""
    import re
    import shutil
    from pathlib import Path
    import sqlite3
    from tradelab.audit import archive

    m = re.match(r"^/tradelab/runs/([^/]+)$", path)
    if m:
        run_id = m.group(1)
        return _delete_run(run_id)

    return _err("not found"), 404


def _delete_run(run_id: str) -> tuple[str, int]:
    """Soft-archive a run: insert into archived_runs + remove report folder."""
    import shutil
    import sqlite3
    from pathlib import Path
    from tradelab.audit import archive

    db = _db_path()
    if not db.exists():
        return _err("run not found"), 404

    # Look up the report folder for this run_id
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT report_card_html_path FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return _err("run not found"), 404

    report_path_str = row[0]
    folder: Path | None = None
    if report_path_str:
        p = Path(report_path_str)
        # report_card_html_path may be a file path; the folder is its parent
        if p.is_file():
            folder = p.parent
        elif p.is_dir():
            folder = p
        elif (p.parent.is_dir() and p.parent != Path()):
            folder = p.parent

    # Try to remove the folder
    if folder and folder.exists():
        try:
            shutil.rmtree(folder)
        except (OSError, PermissionError) as e:
            return _err(f"folder removal failed: {e}"), 409

    # Record the archive (idempotent)
    archive.archive_run(run_id, reason="user_delete", db_path=db)

    return "", 204
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/web/test_runs_delete.py -v 2>&1 | tail -20
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/web/handlers.py tests/web/test_runs_delete.py
git commit -m "feat(web): DELETE /tradelab/runs/<id> soft-archives a run

Removes the report folder from disk and inserts into archived_runs.
The audit DB runs row is preserved (append-only contract).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: POST /tradelab/runs/bulk-delete endpoint

**Files:**
- Modify: `tradelab/src/tradelab/web/handlers.py` — add bulk-delete branch in `handle_post_with_status`
- Test: `tradelab/tests/web/test_runs_bulk_delete.py`

Bulk delete is N independent (folder, archive insert) pairs. Returns `{deleted: [...], failed: [{id, reason}]}` with 200 even on partial success.

- [ ] **Step 1: Write failing tests**

Create `tradelab/tests/web/test_runs_bulk_delete.py`:

```python
"""Tests for POST /tradelab/runs/bulk-delete."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tradelab.audit import archive
from tradelab.web import handlers


def _seed_run(db: Path, run_id: str, report_folder: str) -> None:
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                timestamp_utc TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                report_card_html_path TEXT
            );
        """)
        conn.execute(
            "INSERT INTO runs (run_id, timestamp_utc, strategy_name, report_card_html_path) "
            "VALUES (?, ?, ?, ?)",
            (run_id, "2026-04-25T00:00:00Z", "S2", report_folder),
        )
        conn.commit()
    finally:
        conn.close()


def test_bulk_delete_all_success(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "history.db"
    folders = []
    for i in range(3):
        f = tmp_path / "reports" / f"r{i}"
        f.mkdir(parents=True)
        folders.append(f)
        _seed_run(db, f"run-{i}", str(f))
    monkeypatch.setattr(handlers, "_db_path", lambda: db)
    monkeypatch.setattr(handlers, "_reports_root", lambda: tmp_path / "reports")

    body, status = handlers.handle_post_with_status(
        "/tradelab/runs/bulk-delete",
        json.dumps({"run_ids": ["run-0", "run-1", "run-2"]}).encode(),
    )
    assert status == 200
    payload = json.loads(body)
    assert sorted(payload["deleted"]) == ["run-0", "run-1", "run-2"]
    assert payload["failed"] == []
    for f in folders:
        assert not f.exists()


def test_bulk_delete_unknown_id_lands_in_failed(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "history.db"
    f = tmp_path / "reports" / "r0"
    f.mkdir(parents=True)
    _seed_run(db, "run-0", str(f))
    monkeypatch.setattr(handlers, "_db_path", lambda: db)
    monkeypatch.setattr(handlers, "_reports_root", lambda: tmp_path / "reports")

    body, status = handlers.handle_post_with_status(
        "/tradelab/runs/bulk-delete",
        json.dumps({"run_ids": ["run-0", "run-missing"]}).encode(),
    )
    assert status == 200
    payload = json.loads(body)
    assert payload["deleted"] == ["run-0"]
    assert payload["failed"] == [{"id": "run-missing", "reason": "run not found"}]


def test_bulk_delete_empty_request(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "history.db"
    monkeypatch.setattr(handlers, "_db_path", lambda: db)
    monkeypatch.setattr(handlers, "_reports_root", lambda: tmp_path / "reports")

    body, status = handlers.handle_post_with_status(
        "/tradelab/runs/bulk-delete",
        json.dumps({"run_ids": []}).encode(),
    )
    assert status == 200
    assert json.loads(body) == {"deleted": [], "failed": []}


def test_bulk_delete_missing_run_ids_field_returns_400(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "history.db"
    monkeypatch.setattr(handlers, "_db_path", lambda: db)

    body, status = handlers.handle_post_with_status(
        "/tradelab/runs/bulk-delete",
        json.dumps({}).encode(),
    )
    assert status == 400
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/web/test_runs_bulk_delete.py -v 2>&1 | tail -20
```

Expected: 4 tests fail (route doesn't exist yet).

- [ ] **Step 3: Add the route to `handle_post_with_status`**

In `tradelab/src/tradelab/web/handlers.py`, locate `handle_post_with_status` (around line 348). Add this branch BEFORE the existing `if path == "/tradelab/jobs":` check:

```python
    if path == "/tradelab/runs/bulk-delete":
        run_ids = payload.get("run_ids")
        if run_ids is None:
            return _err("missing run_ids field"), 400
        if not isinstance(run_ids, list):
            return _err("run_ids must be a list"), 400

        deleted: list[str] = []
        failed: list[dict] = []
        for run_id in run_ids:
            body, status = _delete_run(str(run_id))
            if status == 204:
                deleted.append(str(run_id))
            else:
                # Parse the error message from the envelope
                try:
                    msg = json.loads(body).get("error", "unknown error")
                except (json.JSONDecodeError, AttributeError):
                    msg = "unknown error"
                failed.append({"id": str(run_id), "reason": msg})

        return json.dumps({"deleted": deleted, "failed": failed}), 200
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/web/test_runs_bulk_delete.py -v 2>&1 | tail -20
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/web/handlers.py tests/web/test_runs_bulk_delete.py
git commit -m "feat(web): POST /tradelab/runs/bulk-delete handles partial failure

Returns {deleted: [...], failed: [{id, reason}]} with 200 even when some
ids fail; the frontend toast shows partial-success counts.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: GET /tradelab/strategies/<name>/history endpoint

**Files:**
- Modify: `tradelab/src/tradelab/web/audit_reader.py` — add `history_for_strategy()`
- Modify: `tradelab/src/tradelab/web/handlers.py` — add route to `handle_get_with_status`
- Test: `tradelab/tests/web/test_strategy_history.py`

Returns the last N runs for one strategy as a list of dicts. Excludes archived. Powers the slide-in pane's history list.

- [ ] **Step 1: Write failing tests**

Create `tradelab/tests/web/test_strategy_history.py`:

```python
"""Tests for GET /tradelab/strategies/<name>/history."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tradelab.audit import archive
from tradelab.web import handlers


def _seed_runs(db: Path, rows: list[tuple]) -> None:
    """rows: [(run_id, timestamp, strategy, verdict, dsr), ...]"""
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                timestamp_utc TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                verdict TEXT,
                dsr_probability REAL
            );
        """)
        conn.executemany(
            "INSERT INTO runs (run_id, timestamp_utc, strategy_name, verdict, dsr_probability) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def test_history_returns_strategy_runs_descending(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "history.db"
    _seed_runs(db, [
        ("r1", "2026-04-23T00:00:00Z", "S2", "STRONG", 0.4),
        ("r2", "2026-04-24T00:00:00Z", "S2", "MODERATE", 0.3),
        ("r3", "2026-04-25T00:00:00Z", "S2", "STRONG", 0.5),
        ("r4", "2026-04-25T00:00:00Z", "S4", "WEAK", 0.1),
    ])
    monkeypatch.setattr(handlers, "_db_path", lambda: db)

    body, status = handlers.handle_get_with_status(
        "/tradelab/strategies/S2/history?limit=10"
    )
    assert status == 200
    payload = json.loads(body)
    assert [r["run_id"] for r in payload["runs"]] == ["r3", "r2", "r1"]


def test_history_excludes_archived(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "history.db"
    _seed_runs(db, [
        ("r1", "2026-04-23T00:00:00Z", "S2", "STRONG", 0.4),
        ("r2", "2026-04-24T00:00:00Z", "S2", "WEAK", 0.1),
    ])
    archive.archive_run("r2", db_path=db)
    monkeypatch.setattr(handlers, "_db_path", lambda: db)

    body, status = handlers.handle_get_with_status(
        "/tradelab/strategies/S2/history"
    )
    assert status == 200
    assert [r["run_id"] for r in json.loads(body)["runs"]] == ["r1"]


def test_history_limit_param_caps_results(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "history.db"
    _seed_runs(db, [
        (f"r{i}", f"2026-04-{20+i:02d}T00:00:00Z", "S2", "STRONG", 0.4)
        for i in range(8)
    ])
    monkeypatch.setattr(handlers, "_db_path", lambda: db)

    body, status = handlers.handle_get_with_status(
        "/tradelab/strategies/S2/history?limit=3"
    )
    assert status == 200
    assert len(json.loads(body)["runs"]) == 3


def test_history_unknown_strategy_returns_empty(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "history.db"
    _seed_runs(db, [("r1", "2026-04-25T00:00:00Z", "S2", "STRONG", 0.4)])
    monkeypatch.setattr(handlers, "_db_path", lambda: db)

    body, status = handlers.handle_get_with_status(
        "/tradelab/strategies/UNKNOWN/history"
    )
    assert status == 200
    assert json.loads(body) == {"runs": []}
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/web/test_strategy_history.py -v 2>&1 | tail -20
```

Expected: 4 fail (route returns 404).

- [ ] **Step 3: Add `history_for_strategy` to `audit_reader.py`**

Append to `tradelab/src/tradelab/web/audit_reader.py`:

```python
def history_for_strategy(
    strategy: str,
    *,
    limit: int = 10,
    exclude_archived: bool = True,
    db_path: Optional[Path] = None,
) -> list[dict]:
    """Return last N runs for a single strategy, ordered by timestamp desc."""
    db = _resolve_db(db_path)
    if not db.exists():
        return []

    archived_ids: set[str] = set()
    if exclude_archived:
        from tradelab.audit.archive import list_archived_run_ids
        archived_ids = list_archived_run_ids(db_path=db)

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM runs WHERE strategy_name = ? "
            "ORDER BY timestamp_utc DESC LIMIT ?",
            (strategy, limit + len(archived_ids)),  # over-fetch to compensate
        ).fetchall()
    finally:
        conn.close()

    out = [dict(r) for r in rows if r["run_id"] not in archived_ids]
    return out[:limit]
```

- [ ] **Step 4: Add the route to `handle_get_with_status`**

Locate `handle_get_with_status` in `tradelab/src/tradelab/web/handlers.py`. Add this branch before the final `return _err("not found"), 404`:

```python
    m = re.match(r"^/tradelab/strategies/([^/]+)/history$", path_only)
    if m:
        strategy = m.group(1)
        try:
            limit = int(query.get("limit", ["10"])[0])
        except (ValueError, IndexError):
            limit = 10
        runs = audit_reader.history_for_strategy(
            strategy, limit=limit, db_path=_db_path()
        )
        return json.dumps({"runs": runs}), 200
```

(Confirm `audit_reader` is already imported at the top of the file; if not, add it.)

- [ ] **Step 5: Run tests, verify they pass**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/web/test_strategy_history.py -v 2>&1 | tail -20
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/web/audit_reader.py src/tradelab/web/handlers.py tests/web/test_strategy_history.py
git commit -m "feat(web): GET /tradelab/strategies/<name>/history

Powers the slide-in pane's per-strategy history list. Excludes archived
runs by default.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Modify GET /tradelab/runs to merge JobManager + audit DB and exclude archived

**Files:**
- Modify: `tradelab/src/tradelab/web/audit_reader.py` — add `exclude_archived` param to `list_runs` and `count_runs`
- Modify: `tradelab/src/tradelab/web/handlers.py` — `/tradelab/runs` handler now includes in-flight jobs from JobManager
- Test: `tradelab/tests/web/test_runs_merged.py`

This is the core "single source of truth" change. The endpoint returns a list where each item has a `source` field of either `"job"` (from JobManager, in-flight) or `"audit"` (from runs table, completed). Frontend renders both with one row template.

Order: in-flight jobs (running → queued) first, then audit rows by `timestamp_utc DESC`.

- [ ] **Step 1: Write failing tests**

Create `tradelab/tests/web/test_runs_merged.py`:

```python
"""Tests for the merged GET /tradelab/runs endpoint."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tradelab.audit import archive
from tradelab.web import handlers


def _seed_audit_runs(db: Path, rows: list[tuple]) -> None:
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                timestamp_utc TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                verdict TEXT,
                dsr_probability REAL
            );
        """)
        conn.executemany(
            "INSERT INTO runs (run_id, timestamp_utc, strategy_name, verdict, dsr_probability) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def _fake_job_manager(jobs_payload: list[dict]):
    jm = MagicMock()
    jm.list_jobs.return_value = [_FakeJob(j) for j in jobs_payload]
    return jm


class _FakeJob:
    def __init__(self, d: dict):
        self._d = d

    def to_dict(self) -> dict:
        return self._d


def test_runs_excludes_archived_by_default(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "history.db"
    _seed_audit_runs(db, [
        ("r1", "2026-04-25T00:00:00Z", "S2", "STRONG", 0.4),
        ("r2", "2026-04-24T00:00:00Z", "S2", "WEAK", 0.1),
    ])
    archive.archive_run("r2", db_path=db)
    monkeypatch.setattr(handlers, "_db_path", lambda: db)
    monkeypatch.setattr(handlers, "_get_job_manager", lambda: _fake_job_manager([]))

    body, status = handlers.handle_get_with_status("/tradelab/runs")
    assert status == 200
    payload = json.loads(body)
    ids = [r.get("run_id") or r.get("id") for r in payload["runs"]]
    assert "r1" in ids
    assert "r2" not in ids


def test_runs_include_archived_with_query_param(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "history.db"
    _seed_audit_runs(db, [
        ("r1", "2026-04-25T00:00:00Z", "S2", "STRONG", 0.4),
        ("r2", "2026-04-24T00:00:00Z", "S2", "WEAK", 0.1),
    ])
    archive.archive_run("r2", db_path=db)
    monkeypatch.setattr(handlers, "_db_path", lambda: db)
    monkeypatch.setattr(handlers, "_get_job_manager", lambda: _fake_job_manager([]))

    body, status = handlers.handle_get_with_status(
        "/tradelab/runs?include_archived=true"
    )
    assert status == 200
    payload = json.loads(body)
    ids = [r.get("run_id") or r.get("id") for r in payload["runs"]]
    assert "r1" in ids
    assert "r2" in ids


def test_runs_merges_inflight_jobs_at_top(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "history.db"
    _seed_audit_runs(db, [
        ("r1", "2026-04-25T00:00:00Z", "S2", "STRONG", 0.4),
    ])
    monkeypatch.setattr(handlers, "_db_path", lambda: db)
    monkeypatch.setattr(handlers, "_get_job_manager", lambda: _fake_job_manager([
        {"id": "job-A", "strategy": "S4", "status": "running", "command": "robustness"},
        {"id": "job-B", "strategy": "S7", "status": "queued", "command": "run"},
    ]))

    body, status = handlers.handle_get_with_status("/tradelab/runs")
    assert status == 200
    payload = json.loads(body)
    sources = [r["source"] for r in payload["runs"]]
    # In-flight rows come first
    assert sources[:2] == ["job", "job"]
    assert sources[2] == "audit"


def test_runs_inflight_running_before_queued(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "history.db"
    monkeypatch.setattr(handlers, "_db_path", lambda: db)
    monkeypatch.setattr(handlers, "_get_job_manager", lambda: _fake_job_manager([
        {"id": "job-Q", "strategy": "S4", "status": "queued", "command": "run"},
        {"id": "job-R", "strategy": "S7", "status": "running", "command": "robustness"},
    ]))

    body, status = handlers.handle_get_with_status("/tradelab/runs")
    assert status == 200
    payload = json.loads(body)
    statuses = [r["status"] for r in payload["runs"][:2]]
    assert statuses == ["running", "queued"]


def test_runs_inflight_excludes_terminal_jobs(tmp_path: Path, monkeypatch) -> None:
    """Done/failed/cancelled jobs come from the audit DB, not from the job list.

    The JobManager retains terminal jobs for ~50 entries (RETENTION_TERMINAL_JOBS),
    but the merged /tradelab/runs view should NOT double-render them — the
    audit DB row is the durable record. Terminal jobs are skipped here.
    """
    db = tmp_path / "history.db"
    monkeypatch.setattr(handlers, "_db_path", lambda: db)
    monkeypatch.setattr(handlers, "_get_job_manager", lambda: _fake_job_manager([
        {"id": "job-D", "strategy": "S2", "status": "done", "command": "run"},
        {"id": "job-F", "strategy": "S4", "status": "failed", "command": "run"},
        {"id": "job-R", "strategy": "S7", "status": "running", "command": "run"},
    ]))

    body, status = handlers.handle_get_with_status("/tradelab/runs")
    payload = json.loads(body)
    job_rows = [r for r in payload["runs"] if r["source"] == "job"]
    assert len(job_rows) == 1
    assert job_rows[0]["status"] == "running"
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/web/test_runs_merged.py -v 2>&1 | tail -30
```

Expected: 5 fail (current `/tradelab/runs` doesn't return `source` field, doesn't merge jobs, doesn't filter archived).

- [ ] **Step 3: Add `exclude_archived` to `audit_reader.list_runs`**

Modify `tradelab/src/tradelab/web/audit_reader.py:list_runs` to accept and apply `exclude_archived`:

```python
def list_runs(
    strategy: Optional[str] = None,
    verdicts: Optional[list[str]] = None,
    since: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db_path: Optional[Path] = None,
    exclude_archived: bool = True,
) -> list[dict]:
    """Return runs ordered by timestamp descending."""
    db = _resolve_db(db_path)
    if not db.exists():
        return []
    archived_ids: set[str] = set()
    if exclude_archived:
        from tradelab.audit.archive import list_archived_run_ids
        archived_ids = list_archived_run_ids(db_path=db)

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        sql = "SELECT * FROM runs"
        where: list[str] = []
        args: list = []
        if strategy:
            where.append("strategy_name = ?")
            args.append(strategy)
        if verdicts:
            placeholders = ",".join("?" * len(verdicts))
            where.append(f"verdict IN ({placeholders})")
            args.extend(verdicts)
        if since:
            where.append("timestamp_utc >= ?")
            args.append(since)
        if where:
            sql += " WHERE " + " AND ".join(where)
        # Over-fetch to allow post-filtering of archived ids without breaking pagination too badly
        sql += " ORDER BY timestamp_utc DESC LIMIT ? OFFSET ?"
        args.extend([limit + len(archived_ids), offset])
        rows = conn.execute(sql, args).fetchall()
    finally:
        conn.close()

    out = [dict(r) for r in rows if r["run_id"] not in archived_ids]
    return out[:limit]
```

- [ ] **Step 4: Refactor `_get_job_manager` access in handlers.py for monkeypatching**

In `tradelab/src/tradelab/web/handlers.py`, near the top with other helpers, add:

```python
def _get_job_manager():
    """Indirection to allow monkeypatching in tests."""
    from tradelab.web import get_job_manager
    return get_job_manager()
```

Replace any direct `from tradelab.web import get_job_manager; jm = get_job_manager()` with `jm = _get_job_manager()`. Locations: line ~185 (the existing `/tradelab/jobs` GET handler).

- [ ] **Step 5: Modify `/tradelab/runs` GET handler to merge + filter archived**

Locate the existing `/tradelab/runs` route in `handle_get_with_status` (or `handle_get` — depends on file structure). Replace it with:

```python
    if path_only == "/tradelab/runs":
        # Parse filters from query string
        strategy_q = query.get("strategy", [None])[0] or None
        verdicts_q = query.get("verdict", [])
        since_q = query.get("since", [None])[0] or None
        try:
            limit = int(query.get("limit", ["50"])[0])
        except (ValueError, IndexError):
            limit = 50
        include_archived = query.get("include_archived", ["false"])[0].lower() == "true"

        # Audit DB rows
        audit_rows = audit_reader.list_runs(
            strategy=strategy_q,
            verdicts=verdicts_q or None,
            since=since_q,
            limit=limit,
            db_path=_db_path(),
            exclude_archived=not include_archived,
        )
        for r in audit_rows:
            r["source"] = "audit"
            r["status"] = "done"  # all audit rows are completed by definition

        # In-flight jobs
        jm = _get_job_manager()
        all_jobs = [j.to_dict() for j in jm.list_jobs()]
        # Only include non-terminal job statuses; done/failed/cancelled live in audit DB
        IN_FLIGHT = {"queued", "running"}
        inflight = [j for j in all_jobs if j.get("status") in IN_FLIGHT]
        # Apply strategy filter to jobs too
        if strategy_q:
            inflight = [j for j in inflight if j.get("strategy") == strategy_q]
        for j in inflight:
            j["source"] = "job"
            # Map to a uniform key set; keep job-native fields too
            j["run_id"] = j["id"]

        # Order: running → queued → audit-by-date-desc
        inflight.sort(key=lambda j: (0 if j["status"] == "running" else 1,
                                     j.get("started_at") or ""))

        return json.dumps({"runs": inflight + audit_rows}), 200
```

- [ ] **Step 6: Run tests, verify they pass**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/web/test_runs_merged.py tests/web/ -v 2>&1 | tail -30
```

Expected: 5 new tests pass; pre-existing web tests should still pass (no regression). If any pre-existing test breaks, it's likely asserting the old non-merged shape — update those assertions to expect the new envelope including `source`.

- [ ] **Step 7: Commit**

```bash
cd C:/TradingScripts/tradelab && git add src/tradelab/web/audit_reader.py src/tradelab/web/handlers.py tests/web/test_runs_merged.py
git commit -m "feat(web): merge in-flight jobs into /tradelab/runs, exclude archived

The Pipeline endpoint now returns a unified list with a 'source' field of
'job' (from JobManager) or 'audit' (from runs table). Terminal jobs are
suppressed from the job side since the audit DB row is the durable record.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Frontend — remove Active Jobs section + jobState code

**Files:**
- Modify: `C:/TradingScripts/command_center.html` — delete `<section id="research-job-tracker">` and the `jobState` Map + `renderJobTracker` function

**No automated tests for frontend tasks** — manual smoke after each task.

- [ ] **Step 1: Remove the Active Jobs section markup**

In `C:/TradingScripts/command_center.html`, locate `<section id="research-job-tracker"` (around line 693) and delete the entire section through its closing `</section>` (~line 700).

- [ ] **Step 2: Remove the jobState Map and renderJobTracker function**

In the same file, locate the JS block starting around `const jobState = {` (around line 3347). Delete:
- The `jobState` declaration and any helper functions that reference it (`renderJobTracker`, etc.)
- Any code that sets `panel.hidden` based on `jobState.jobs.size`
- Any `jobState.jobs.set(...)`, `jobState.jobs.clear()`, `jobState.jobs.values()` references

Keep the SSE EventSource setup — it will be rewired in Task 9. For now, change its onmessage handler to a no-op stub:

```javascript
// SSE handler — Pipeline row-update wiring lives in Task 9
function handleJobUpdate(msg) {
  // no-op for now; replaced in Task 9
}
```

- [ ] **Step 3: Manual smoke**

```
1. Restart launch_dashboard.py (Ctrl-C then re-run)
2. Open http://127.0.0.1:8877 in a browser, hard-reload (Ctrl-Shift-R)
3. Navigate to Research tab
4. Verify: NO Active Jobs panel renders, even after starting a backtest from the launcher
5. Verify: Pipeline table still loads (with old non-merged data — that's OK for now)
6. Open browser console — no JS errors
```

If the Pipeline table fails to load, you accidentally removed something it depends on. Check the JS removed in Step 2 for cross-references.

- [ ] **Step 4: Commit**

```bash
cd C:/TradingScripts && git add command_center.html
git commit -m "refactor(command-center): remove Active Jobs panel + jobState map

Step 1 of Research tab unification. SSE handler is stubbed; rewired to
update Pipeline rows in Task 9.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Frontend — Status column + action strip in Pipeline table

**Files:**
- Modify: `C:/TradingScripts/command_center.html` — add Status `<th>`, replace Run dropdown column with Actions, render rows from merged data

- [ ] **Step 1: Update Pipeline table `<thead>`**

Locate the table header at line 730-744. Replace it with:

```html
<table class="table" id="researchPipelineTable">
  <thead>
    <tr>
      <th style="width:24px"></th>
      <th data-sort="status">Status</th>
      <th data-sort="strategy_name">Strategy</th>
      <th data-sort="verdict">Verdict</th>
      <th data-sort="pf">PF</th>
      <th data-sort="win_rate">WR</th>
      <th data-sort="max_drawdown_pct">DD</th>
      <th data-sort="total_trades">Trd</th>
      <th data-sort="dsr_probability">DSR</th>
      <th>Trend</th>
      <th data-sort="timestamp_utc">Date</th>
      <th>Actions</th>
    </tr>
  </thead>
```

(The `Run` column header is replaced with `Actions`; `Status` is inserted after the checkbox.)

- [ ] **Step 2: Update the row renderer**

Find the JavaScript that builds rows in `<tbody id="researchPipelineBody">`. Add a Status cell as the second cell of each row, and replace the Run-dropdown cell with an Actions cell containing letter buttons.

Status cell template (depends on row's `source` and `status`):

```javascript
function statusCell(row) {
  if (row.source === 'job') {
    if (row.status === 'running') {
      return `<td><span class="pill running">RUNNING</span>
                  <div class="progress-bar"><div class="progress-fill" style="width:${(row.progress||0)*100}%"></div></div></td>`;
    }
    if (row.status === 'queued') {
      return `<td><span class="pill queued">QUEUED</span></td>`;
    }
  }
  return `<td><span class="pill done">DONE</span></td>`;
}

function actionsCell(row) {
  if (row.source === 'job' && row.status === 'running') {
    return `<td><button class="action-btn cancel" data-action="cancel" data-id="${row.run_id}">Cancel</button></td>`;
  }
  if (row.source === 'job' && row.status === 'queued') {
    return `<td><button class="action-btn cancel" data-action="cancel" data-id="${row.run_id}">Cancel</button></td>`;
  }
  // audit row — done
  return `<td>
    <button class="action-btn view" data-action="dashboard" data-id="${row.run_id}">D</button>
    <button class="action-btn view" data-action="quantstats" data-id="${row.run_id}">Q</button>
    <button class="action-btn" data-action="run" data-id="${row.run_id}" data-flag="op">Op</button>
    <button class="action-btn" data-action="run" data-id="${row.run_id}" data-flag="wf">WF</button>
    <button class="action-btn" data-action="run" data-id="${row.run_id}" data-flag="run">Run</button>
    <button class="action-btn" data-action="run" data-id="${row.run_id}" data-flag="rb">Rb</button>
    <button class="action-btn" data-action="run" data-id="${row.run_id}" data-flag="full">Full</button>
    <button class="action-btn danger" data-action="delete" data-id="${row.run_id}">🗑</button>
  </td>`;
}
```

Wire `actionsCell`'s click handlers via event delegation on `tbody#researchPipelineBody`:

```javascript
document.getElementById('researchPipelineBody').addEventListener('click', (e) => {
  const btn = e.target.closest('button[data-action]');
  if (!btn) return;
  e.stopPropagation();  // don't trigger row-click → pane open
  const action = btn.dataset.action;
  const id = btn.dataset.id;
  if (action === 'dashboard')  return openReportModal(id, 'dashboard');
  if (action === 'quantstats') return openReportModal(id, 'quantstats');
  if (action === 'cancel')     return cancelJob(id);
  if (action === 'delete')     return confirmDeleteRun(id);
  if (action === 'run')        return triggerRun(id, btn.dataset.flag);
});
```

`openReportModal`, `cancelJob`, `triggerRun` are existing functions — reuse them. `confirmDeleteRun` is new (added in Task 12).

Add CSS for the new `.action-btn` and pill classes if not already present (copy from `RESEARCH_TAB_REDESIGN_CONCEPTS.html` Concept E mockup styles).

- [ ] **Step 3: Manual smoke**

```
1. Restart launch_dashboard.py
2. Hard-reload Research tab
3. Verify: Pipeline table has Status column showing DONE for all completed runs
4. Verify: Each row has the action strip (D Q Op WF R Rb F 🗑) on the right
5. Click D on any row → existing dashboard.html modal opens (existing flow unchanged)
6. Trigger a backtest from the launcher → row appears at TOP with RUNNING pill
   (the row data won't auto-update yet — that's Task 9)
7. Browser console: no JS errors
```

- [ ] **Step 4: Commit**

```bash
cd C:/TradingScripts && git add command_center.html
git commit -m "feat(command-center): Status column + per-row action strip

Replaces the Run ▾ dropdown with explicit letter-buttons (Op WF R Rb F).
Adds a Status column rendering RUNNING/QUEUED/DONE pills based on the
row's source field from the merged /tradelab/runs endpoint.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Frontend — rewire SSE to update Pipeline rows in place

**Files:**
- Modify: `C:/TradingScripts/command_center.html` — replace the Task 7 stub with a real `handleJobUpdate` that finds the matching row by `run_id` and updates its Status / progress cells

- [ ] **Step 1: Implement `handleJobUpdate`**

Replace the Task 7 stub:

```javascript
function handleJobUpdate(payload) {
  // payload shape: {id, status, progress?, started_at?, ended_at?, error_tail?}
  const tbody = document.getElementById('researchPipelineBody');
  const tr = tbody.querySelector(`tr[data-run-id="${payload.id}"]`);

  if (!tr) {
    // New job appearing for the first time — refetch the whole list
    refreshPipeline();
    return;
  }

  // Terminal transitions trigger a refetch (the row needs to be replaced
  // by its audit-DB twin, which has the verdict and metrics)
  const TERMINAL = ['done', 'failed', 'cancelled', 'interrupted'];
  if (TERMINAL.includes(payload.status)) {
    refreshPipeline();
    return;
  }

  // Non-terminal transition — update the Status cell in place
  const statusCellEl = tr.children[1];  // [checkbox, status, strategy, ...]
  if (payload.status === 'running') {
    statusCellEl.innerHTML = `<span class="pill running">RUNNING</span>
      <div class="progress-bar"><div class="progress-fill" style="width:${(payload.progress||0)*100}%"></div></div>`;
  } else if (payload.status === 'queued') {
    statusCellEl.innerHTML = `<span class="pill queued">QUEUED</span>`;
  }
}
```

Make sure each `<tr>` is rendered with `data-run-id="${row.run_id}"` so the lookup works (update the row template from Task 8).

- [ ] **Step 2: Wire `handleJobUpdate` to the existing EventSource**

Find the `EventSource('/tradelab/jobs/stream')` setup. Set its `onmessage` to:

```javascript
eventSource.onmessage = (msg) => {
  try {
    const payload = JSON.parse(msg.data);
    handleJobUpdate(payload);
  } catch (e) {
    console.warn('SSE parse error', e);
  }
};
```

- [ ] **Step 3: Add `refreshPipeline()` helper if not already present**

```javascript
function refreshPipeline() {
  // Re-fetch /tradelab/runs and re-render tbody
  const params = currentFilterQueryString();  // existing helper
  fetch('/tradelab/runs?' + params)
    .then(r => r.json())
    .then(data => renderPipelineRows(data.runs));
}
```

- [ ] **Step 4: Manual smoke**

```
1. Restart launch_dashboard.py
2. Hard-reload Research tab
3. Trigger a backtest from the launcher
4. Within ~1s the row should appear at top with RUNNING pill
5. While the run is in progress, watch the progress bar fill (if SSE emits progress events)
6. When the run completes, the row should refresh: pill changes to DONE, verdict appears, metrics populate
7. Trigger 2 backtests rapidly: one shows RUNNING, the other shows QUEUED
```

If the row doesn't appear or refresh, check browser console for SSE errors and verify the `EventSource` is connected (`eventSource.readyState === 1`).

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts && git add command_center.html
git commit -m "feat(command-center): rewire SSE to update Pipeline rows in place

Non-terminal job transitions update the Status cell of the matching row
without re-rendering the whole table. Terminal transitions trigger a
full refetch so the audit-DB twin replaces the in-flight row.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Frontend — slide-in pane component + content fetch

**Files:**
- Modify: `C:/TradingScripts/command_center.html` — add pane HTML, CSS, click-to-open wiring, content-fetch from `/tradelab/strategies/<name>/history`

- [ ] **Step 1: Add the slide-in pane HTML**

Inside the `#research` tab content (after the modals around line 783), add:

```html
<aside id="researchSlidePane" class="research-slide-pane" hidden aria-hidden="true">
  <button class="research-slide-pane-close" id="researchSlidePaneClose" aria-label="Close">×</button>
  <div class="research-slide-pane-body" id="researchSlidePaneBody">
    <!-- populated by JS -->
  </div>
</aside>
```

- [ ] **Step 2: Add the CSS**

In the `<style>` block:

```css
.research-slide-pane {
  position: fixed;
  top: 0; right: 0; bottom: 0;
  width: 360px;
  background: var(--panel-2, #1d2230);
  border-left: 1px solid var(--line, #262b3b);
  box-shadow: -8px 0 24px -8px rgba(0,0,0,0.5);
  z-index: 50;
  padding: 20px 16px 16px 16px;
  overflow-y: auto;
  transform: translateX(100%);
  transition: transform 0.2s ease;
}
.research-slide-pane:not([hidden]) { transform: translateX(0); }
.research-slide-pane-close {
  position: absolute; top: 8px; right: 12px;
  background: transparent; border: 0; color: var(--muted, #8b93a7);
  font-size: 22px; cursor: pointer; line-height: 1;
}
.research-slide-pane-close:hover { color: var(--text, #e6e9f2); }

.research-slide-pane-body h3 { margin: 0 0 4px 0; font-size: 18px; }
.research-slide-pane-body .pane-meta { font-size: 11px; color: var(--muted); margin-bottom: 14px; }
.research-slide-pane-body .pane-section { margin-bottom: 14px; }
.research-slide-pane-body .pane-history-row {
  background: #0a0d14; border: 1px solid var(--line);
  border-radius: 4px; padding: 6px 8px; margin-bottom: 4px;
  font-size: 11px; display: flex; justify-content: space-between; gap: 8px;
}
```

- [ ] **Step 3: Wire row-click to open the pane**

```javascript
const slidePane = document.getElementById('researchSlidePane');
const slidePaneBody = document.getElementById('researchSlidePaneBody');

document.getElementById('researchPipelineBody').addEventListener('click', (e) => {
  // Skip if click was on a button or checkbox (those have their own handlers)
  if (e.target.closest('button, input[type=checkbox]')) return;
  const tr = e.target.closest('tr[data-run-id]');
  if (!tr) return;
  const strategy = tr.dataset.strategy;
  if (!strategy) return;
  openSlidePane(strategy);
});

document.getElementById('researchSlidePaneClose').addEventListener('click', closeSlidePane);
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !slidePane.hidden) closeSlidePane();
});
slidePane.addEventListener('click', (e) => { e.stopPropagation(); });
document.addEventListener('click', (e) => {
  if (!slidePane.hidden && !slidePane.contains(e.target) &&
      !e.target.closest('tr[data-run-id]')) {
    closeSlidePane();
  }
});

function openSlidePane(strategy) {
  slidePane.hidden = false;
  slidePane.setAttribute('aria-hidden', 'false');
  slidePaneBody.innerHTML = `<div class="pane-meta">Loading…</div>`;
  fetch(`/tradelab/strategies/${encodeURIComponent(strategy)}/history?limit=10`)
    .then(r => r.json())
    .then(data => renderSlidePane(strategy, data.runs))
    .catch(err => {
      slidePaneBody.innerHTML = `<div class="pane-meta">Error: ${err.message}</div>`;
    });
}

function closeSlidePane() {
  slidePane.hidden = true;
  slidePane.setAttribute('aria-hidden', 'true');
}

function renderSlidePane(strategy, runs) {
  const latest = runs[0];
  const verdictPill = latest && latest.verdict
    ? `<span class="pill ${latest.verdict.toLowerCase()}">${latest.verdict}</span>`
    : '';
  const historyHtml = runs.map(r => `
    <div class="pane-history-row">
      <span><span class="pill done" style="font-size:9px">DONE</span> ${escapeHtml(r.timestamp_utc || '')}</span>
      <span>${escapeHtml(r.verdict || '—')} · PF ${r.pf == null ? '—' : r.pf.toFixed(2)}</span>
    </div>
  `).join('');

  slidePaneBody.innerHTML = `
    <h3>${escapeHtml(strategy)} ${verdictPill}</h3>
    <div class="pane-meta">Last ${runs.length} runs</div>
    <div class="pane-section">${historyHtml}</div>
    <div class="pane-section">
      <button class="action-btn view" data-action="dashboard" data-id="${latest ? latest.run_id : ''}">Dashboard</button>
      <button class="action-btn view" data-action="quantstats" data-id="${latest ? latest.run_id : ''}">QuantStats</button>
      <button class="action-btn danger" data-action="delete" data-id="${latest ? latest.run_id : ''}">🗑 Delete this run</button>
    </div>
    <div class="pane-section" style="border-top:1px solid var(--line); padding-top:10px">
      <span style="font-size:10px; color:var(--muted); text-transform:uppercase; letter-spacing:0.06em; margin-right:6px">New run:</span>
      <button class="action-btn" data-action="run" data-strategy="${escapeHtml(strategy)}" data-flag="op">Op</button>
      <button class="action-btn" data-action="run" data-strategy="${escapeHtml(strategy)}" data-flag="wf">WF</button>
      <button class="action-btn" data-action="run" data-strategy="${escapeHtml(strategy)}" data-flag="run">Run</button>
      <button class="action-btn" data-action="run" data-strategy="${escapeHtml(strategy)}" data-flag="rb">Rb</button>
      <button class="action-btn" data-action="run" data-strategy="${escapeHtml(strategy)}" data-flag="full">Full</button>
    </div>
  `;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, ch => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[ch]));
}
```

(`renderPipelineRows` from Task 8 must add `data-strategy="${row.strategy_name}"` to each `<tr>` for the click handler to know what to fetch.)

- [ ] **Step 4: Manual smoke**

```
1. Restart launch_dashboard.py + hard-reload Research tab
2. Click any row → pane slides in from right with strategy header + history list
3. Click × → pane slides out
4. Click row → click outside pane → pane closes
5. Click row → press ESC → pane closes
6. Click row → click DIFFERENT row → pane re-fetches with new strategy
7. Click action buttons inside the pane (D, Q, Op, etc.) → trigger normal actions
8. Verify pane scrolls when history is long (test with a strategy that has 10+ runs)
```

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts && git add command_center.html
git commit -m "feat(command-center): slide-in detail pane on row click

360px right-anchored pane fetches /tradelab/strategies/<name>/history
and renders strategy header, last 10 runs, action buttons. Closes on ×,
ESC, or click outside.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Frontend — hash sync for slide-in pane state

**Files:**
- Modify: `C:/TradingScripts/command_center.html` — sync `#tab=research&strategy=<name>` to URL on pane open/close; restore on page load

- [ ] **Step 1: Modify `openSlidePane` and `closeSlidePane` to update the hash**

```javascript
function openSlidePane(strategy) {
  slidePane.hidden = false;
  slidePane.setAttribute('aria-hidden', 'false');
  slidePaneBody.innerHTML = `<div class="pane-meta">Loading…</div>`;
  setPaneHash(strategy);   // ← new
  fetch(`/tradelab/strategies/${encodeURIComponent(strategy)}/history?limit=10`)
    .then(r => r.json())
    .then(data => renderSlidePane(strategy, data.runs))
    .catch(err => {
      slidePaneBody.innerHTML = `<div class="pane-meta">Error: ${err.message}</div>`;
    });
}

function closeSlidePane() {
  slidePane.hidden = true;
  slidePane.setAttribute('aria-hidden', 'true');
  setPaneHash(null);   // ← new
}

function setPaneHash(strategy) {
  // Preserve any existing tab=research and only update/remove strategy=
  const hash = window.location.hash.replace(/^#/, '');
  const params = new URLSearchParams(hash);
  if (strategy) {
    params.set('strategy', strategy);
  } else {
    params.delete('strategy');
  }
  // Always keep tab=research when pane is in play
  if (!params.has('tab')) params.set('tab', 'research');
  const newHash = '#' + params.toString();
  if (newHash !== window.location.hash) {
    history.replaceState(null, '', newHash);
  }
}
```

- [ ] **Step 2: On page load, restore the pane if hash has strategy=**

Find the existing tab-routing on-load handler (search for `hashchange` or `tab=research`). After it runs and the Research tab is selected, add:

```javascript
function restorePaneFromHash() {
  const params = new URLSearchParams(window.location.hash.replace(/^#/, ''));
  const tab = params.get('tab');
  const strategy = params.get('strategy');
  if (tab === 'research' && strategy) {
    // Defer until pipeline data is loaded so the strategy is real
    setTimeout(() => openSlidePane(strategy), 200);
  }
}
window.addEventListener('load', restorePaneFromHash);
window.addEventListener('hashchange', restorePaneFromHash);
```

- [ ] **Step 3: Manual smoke**

```
1. Restart launch_dashboard.py
2. Open Research tab + click a row (e.g., S2) → URL becomes #tab=research&strategy=S2
3. Press F5 → page reloads with pane open on S2
4. Close pane → URL becomes #tab=research (no &strategy=)
5. Switch to a different tab + back → pane is still closed, hash matches state
6. Manually edit URL to #tab=research&strategy=NONEXISTENT → pane opens, shows empty/error state gracefully
```

- [ ] **Step 4: Commit**

```bash
cd C:/TradingScripts && git add command_center.html
git commit -m "feat(command-center): hash sync for slide-in pane state

Pane state survives page reload. URL updates to #tab=research&strategy=<name>
on open and back to #tab=research on close.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: Frontend — per-row trash + bulk delete + confirm modal

**Files:**
- Modify: `C:/TradingScripts/command_center.html` — add confirm modal, per-row trash handler, bulk-delete button, type-DELETE gate

- [ ] **Step 1: Add the confirm modal HTML**

Inside the `#research` tab content:

```html
<div id="researchDeleteConfirm" class="research-modal" hidden>
  <div class="research-modal-card" style="max-width:480px">
    <div class="research-modal-header">
      <div class="research-modal-title">Delete <span id="deleteConfirmCount">1</span> run(s)?</div>
      <button class="research-modal-close" id="deleteConfirmClose">×</button>
    </div>
    <div class="research-modal-body" style="padding:16px">
      <p style="color:var(--muted); margin:0 0 10px 0">
        The report folder will be removed from disk. The audit DB record is
        preserved (filtered out of default queries — restorable from the
        archived_runs table by a developer if needed).
      </p>
      <ul id="deleteConfirmList" style="font-size:11px; color:var(--muted); padding-left:18px"></ul>
      <div id="deleteTypeGate" hidden style="margin-top:12px">
        <label style="font-size:12px; color:var(--bad)">Type DELETE to confirm:</label>
        <input id="deleteTypeInput" class="settings-input" style="margin-top:4px" placeholder="DELETE">
      </div>
      <div style="display:flex; gap:8px; margin-top:14px; justify-content:flex-end">
        <button class="btn" id="deleteConfirmCancel">Cancel</button>
        <button class="btn" id="deleteConfirmGo" style="background:var(--bad,#ef4444); color:white">Delete</button>
      </div>
    </div>
  </div>
</div>
```

- [ ] **Step 2: Implement `confirmDeleteRun(id)` and `confirmBulkDelete(ids)`**

```javascript
function confirmDeleteRun(runId) {
  showDeleteConfirm([runId]);
}

function showDeleteConfirm(runIds) {
  const modal = document.getElementById('researchDeleteConfirm');
  document.getElementById('deleteConfirmCount').textContent = runIds.length;
  const list = document.getElementById('deleteConfirmList');
  list.innerHTML = runIds.slice(0, 5).map(id => `<li>${escapeHtml(id)}</li>`).join('') +
    (runIds.length > 5 ? `<li>… and ${runIds.length - 5} more</li>` : '');
  const gate = document.getElementById('deleteTypeGate');
  const input = document.getElementById('deleteTypeInput');
  const goBtn = document.getElementById('deleteConfirmGo');
  if (runIds.length > 5) {
    gate.hidden = false;
    input.value = '';
    goBtn.disabled = true;
    input.oninput = () => { goBtn.disabled = input.value.trim() !== 'DELETE'; };
  } else {
    gate.hidden = true;
    goBtn.disabled = false;
  }
  goBtn.onclick = () => { performDelete(runIds); modal.hidden = true; };
  document.getElementById('deleteConfirmCancel').onclick = () => { modal.hidden = true; };
  document.getElementById('deleteConfirmClose').onclick = () => { modal.hidden = true; };
  modal.hidden = false;
}

async function performDelete(runIds) {
  if (runIds.length === 1) {
    const r = await fetch(`/tradelab/runs/${encodeURIComponent(runIds[0])}`, { method: 'DELETE' });
    if (r.status === 204) {
      toast('Deleted 1 run');
    } else if (r.status === 404) {
      toast('Already deleted', 'warn');
    } else {
      toast('Delete failed: ' + r.statusText, 'error');
    }
  } else {
    const r = await fetch('/tradelab/runs/bulk-delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ run_ids: runIds }),
    });
    const data = await r.json();
    const okCount = data.deleted.length;
    const failCount = data.failed.length;
    if (failCount === 0) toast(`Deleted ${okCount} runs`);
    else toast(`Deleted ${okCount}, ${failCount} failed`, 'warn');
  }
  refreshPipeline();
  if (!document.getElementById('researchSlidePane').hidden) closeSlidePane();
}
```

(`toast()` is an existing helper — if not, add a minimal one that creates a transient floating div.)

- [ ] **Step 3: Add the bulk-delete button alongside Compare Selected**

Find line 729: `<button class="btn" id="pipelineCompareBtn" hidden>Compare Selected (0)</button>`. Add after it:

```html
<button class="btn" id="pipelineDeleteBtn" hidden style="background:var(--bad,#ef4444); color:white">Delete Selected (0)</button>
```

Wire the button to:
1. Show/hide based on checkbox count (extend the existing handler that updates `pipelineCompareBtn`)
2. On click, gather selected `run_id`s and call `showDeleteConfirm([...])`

```javascript
function getSelectedRunIds() {
  return Array.from(document.querySelectorAll(
    '#researchPipelineBody input[type=checkbox]:checked'
  )).map(cb => cb.dataset.id);
}
function updateSelectionButtons() {
  const ids = getSelectedRunIds();
  const compareBtn = document.getElementById('pipelineCompareBtn');
  const deleteBtn = document.getElementById('pipelineDeleteBtn');
  compareBtn.hidden = ids.length < 2;
  compareBtn.textContent = `Compare Selected (${ids.length})`;
  deleteBtn.hidden = ids.length < 1;
  deleteBtn.textContent = `Delete Selected (${ids.length})`;
}
document.getElementById('researchPipelineBody').addEventListener('change', (e) => {
  if (e.target.matches('input[type=checkbox]')) updateSelectionButtons();
});
document.getElementById('pipelineDeleteBtn').addEventListener('click', () => {
  const ids = getSelectedRunIds();
  if (ids.length) showDeleteConfirm(ids);
});
```

- [ ] **Step 4: Manual smoke**

```
1. Restart + hard-reload
2. Click 🗑 on a single row → confirm modal shows 1 run, no type-gate, Delete button enabled
3. Click Delete → row disappears, toast shows "Deleted 1 run", folder gone from disk
4. Check audit DB: SELECT * FROM archived_runs;  → row appears
5. Check audit DB: SELECT * FROM runs WHERE run_id = '<deleted_id>';  → still there (preserved)
6. Filter Verdict to WEAK or FAILED, check 6 rows → bulk-delete button shows "Delete Selected (6)"
7. Click bulk delete → modal shows first 5 + "and 1 more", type-gate visible, Delete disabled
8. Type "DELETE" → button enables → click → toast shows count + folder removals on disk
9. Bulk delete with N=3 → no type-gate, Delete enabled immediately
10. Open slide-in pane on a row, click 🗑 in pane → same confirm flow → row + pane both close
```

- [ ] **Step 5: Commit**

```bash
cd C:/TradingScripts && git add command_center.html
git commit -m "feat(command-center): per-row + bulk delete with confirm modal

Three delete paths: per-row trash, slide-in pane button, bulk via
checkbox + 'Delete Selected'. Bulk delete > 5 requires type-DELETE gate.
All paths hit the soft-archive endpoints — runs table stays untouched.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: Frontend — rename Clear → Reset filters

**Files:**
- Modify: `C:/TradingScripts/command_center.html` line 724

- [ ] **Step 1: Make the rename**

Locate `<button class="btn" id="researchFilterClear">Clear</button>` (line 724). Change inner text:

```html
<button class="btn" id="researchFilterClear">Reset filters</button>
```

- [ ] **Step 2: Manual smoke**

```
1. Hard-reload
2. Verify the button label reads "Reset filters" (not "Clear")
3. Click it — filters reset as before (existing behavior unchanged)
```

- [ ] **Step 3: Commit**

```bash
cd C:/TradingScripts && git add command_center.html
git commit -m "ui(command-center): rename Clear → Reset filters for clarity

The button is a filter reset, not a delete affordance. Multiple users
read the old label as 'delete'. Per UPGRADES.md item #3D.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 14: Final validation

**Files:**
- (no code changes)

- [ ] **Step 1: Full pytest run**

```bash
cd C:/TradingScripts/tradelab && python -m pytest tests/ --tb=short 2>&1 | tail -30
```

Expected: pass count = baseline (~378) + new tests added (~22 from this plan: 7 archive + 4 delete + 4 bulk-delete + 4 history + 5 merged-runs - 2 if any pre-existing pipeline tests needed updates). Pre-existing 3 failures should still be pre-existing 3, no regressions.

- [ ] **Step 2: End-to-end manual smoke checklist**

```
□ Open dashboard at http://127.0.0.1:8877, navigate to Research tab
□ Active Jobs panel is GONE (verify by trying multiple page states)
□ Pipeline shows merged data: any in-flight job appears at top with RUNNING/QUEUED pill
□ Trigger a backtest — row appears immediately, transitions live, terminal state populates verdict
□ Click any row → slide-in pane opens, shows strategy + last 10 runs
□ × / ESC / click-outside all close the pane
□ F5 with pane open → pane reopens on same strategy (hash sync works)
□ Action buttons in row strip: D, Q open existing modals; Op/WF/R/Rb/F submit jobs
□ Per-row 🗑 → confirm modal → folder gone, archived_runs has the id, runs row preserved
□ Bulk delete: select 3 rows → confirm without type-gate
□ Bulk delete: select 7 rows → confirm modal requires typing DELETE
□ Bulk delete API returns partial success when one folder is locked → toast reflects counts
□ Reset filters button (formerly "Clear") works as before
□ Browser console: no JS errors throughout
```

- [ ] **Step 3: Verify rollback path**

```bash
ls -la C:/TradingScripts/command_center.html.bak-2026-04-25
```

Expected: backup file present from Task 0. Document in commit message that revert path is `cp command_center.html.bak-2026-04-25 command_center.html` plus `git revert` of the relevant commits.

- [ ] **Step 4: Final commit + push prompt**

```bash
cd C:/TradingScripts/tradelab && git log --oneline master..HEAD
```

Expected: ~10-12 commits on `feat/research-slide-pane`. Review them as a unit.

```bash
cd C:/TradingScripts && git log --oneline -10
```

Expected: ~5-6 commits on the parent repo (command_center.html edits + launch_dashboard.py do_DELETE).

**Push decision:** Ask the user whether to merge `feat/research-slide-pane` to `master` (use `superpowers:finishing-a-development-branch` skill if available) and whether to push the 45+commits-ahead `master` to `origin`. Do NOT push without explicit user instruction.

---

## What this plan does NOT do

- No equity sparkline in the pane (deferred — pane shows numeric history only)
- No embedded `dashboard.html` iframe (clicking opens the existing modal)
- No Promote-to-Live button (Item #1, separate workstream)
- No Compare-N visual changes (existing behavior preserved alongside new Delete button)
- No undo window for delete (relies on the soft-archive recoverability via developer SQL)
- No per-strategy SSE routing (frontend refetches on terminal state)
- No accessibility audit (single-user localhost — defensible deferral, but flag for future)
- No frontend automated tests (gap; manual smoke only)

---

## Rollback plan

If the rework lands and is broken:

1. Revert command_center.html: `cp command_center.html.bak-2026-04-25 command_center.html`
2. `cd tradelab && git revert <range>` for backend commits
3. The `archived_runs` table can be dropped if undesired (it's a sidecar, no FK to `runs`):
   ```sql
   DROP TABLE archived_runs;
   ```
   No data loss to the immutable runs table.

---

*End of plan.*
