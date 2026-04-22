# Command Center Research Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Research tab to `C:\TradingScripts\command_center.html` that surfaces tradelab audit data, embeds existing per-run dashboards and QuantStats tearsheets, offers Claude-recommended slider what-if analysis, and accepts paste-to-test new strategies — all inside the existing 8877 server, reusing the existing dark theme.

**Architecture:** One Python process (`C:\TradingScripts\launch_dashboard.py`) gains new `/tradelab/*` endpoints that import tradelab as a library and read the audit DB + per-run backtest JSON. The HTML gets a new `data-tab="research"` tab with all JS/CSS inline per existing convention. Tradelab is a soft dependency — if import fails, command_center live-trading tabs still work.

**Tech Stack:** Python 3.12, stdlib http.server, sqlite3 (tradelab.audit.history), pandas (tradelab engines), vanilla JS fetch(), Chart.js (already bundled at `chart.min.js`), pytest.

---

## Repo layout notes (read first)

This feature touches two codebases:

| Path | Git? | Notes |
|------|------|-------|
| `C:\TradingScripts\tradelab\` | ✓ | Primary — all new Python code, endpoints, tests commit here |
| `C:\TradingScripts\` | ✗ | Hosts `launch_dashboard.py` and `command_center.html` — edits are in-place with manual backups before each task that touches them |

**Before starting Task 0, verify working directory:** all commands assume shell is in `C:\TradingScripts\tradelab` unless a command explicitly `cd`s elsewhere. Git commits all go to the tradelab repo. Edits to `C:\TradingScripts\launch_dashboard.py` and `C:\TradingScripts\command_center.html` are made in-place; Task 0 creates timestamped backups of both.

**Python env:** venv at `C:\TradingScripts\.venv-vectorbt\`. Activate with `source /c/TradingScripts/.venv-vectorbt/Scripts/activate` in Git Bash before running tests or the server.

---

## File structure

### New files in `C:\TradingScripts\tradelab\`

| Path | Responsibility |
|------|----------------|
| `src/tradelab/web/__init__.py` | Empty package marker |
| `src/tradelab/web/audit_reader.py` | Read `tradelab_history.db` + join `backtest_result.json` per run |
| `src/tradelab/web/freshness.py` | Compute parquet cache age for data-freshness banner |
| `src/tradelab/web/ranges.py` | Read `claude_ranges.json` sidecar for What-If sliders |
| `src/tradelab/web/whatif.py` | Run single-symbol backtest with param overrides |
| `src/tradelab/web/new_strategy.py` | Paste → stage → validate → register pipeline |
| `src/tradelab/web/handlers.py` | Request dispatch used by launch_dashboard.py |
| `tests/web/__init__.py` | Empty marker |
| `tests/web/conftest.py` | Pytest fixtures (fake audit DB, fake run folder, fake parquet) |
| `tests/web/test_audit_reader.py` | Unit tests for audit_reader |
| `tests/web/test_freshness.py` | Unit tests for freshness |
| `tests/web/test_ranges.py` | Unit tests for ranges |
| `tests/web/test_whatif.py` | Unit tests for whatif |
| `tests/web/test_new_strategy.py` | Unit tests for new_strategy pipeline |
| `tests/web/test_handlers.py` | Integration tests (exercise handler dispatch end-to-end) |
| `docs/superpowers/plans/2026-04-22-command-center-research-tab.md` | This file |

### New files in `C:\TradingScripts\`

| Path | Responsibility |
|------|----------------|
| `research_dashboard.bat` | One-click desktop launcher (opens directly to Research tab) |
| `command_center.html.bak-2026-04-22` | Backup created in Task 0 |
| `launch_dashboard.py.bak-2026-04-22` | Backup created in Task 0 |

### Files modified

| Path | Nature of change |
|------|------------------|
| `C:\TradingScripts\launch_dashboard.py` | Import tradelab.web.handlers; dispatch `/tradelab/*` routes to it |
| `C:\TradingScripts\command_center.html` | Add 5th tab + tab-content div + CSS for `.research-*` classes + JS module for Research tab and modal |

---

## Task 0: Setup — backups and scaffold

**Files:**
- Create: `C:\TradingScripts\command_center.html.bak-2026-04-22`
- Create: `C:\TradingScripts\launch_dashboard.py.bak-2026-04-22`
- Create: `C:\TradingScripts\tradelab\src\tradelab\web\__init__.py`
- Create: `C:\TradingScripts\tradelab\tests\web\__init__.py`

- [ ] **Step 1: Back up the files that will be edited in-place**

```bash
cp "C:/TradingScripts/command_center.html" "C:/TradingScripts/command_center.html.bak-2026-04-22"
cp "C:/TradingScripts/launch_dashboard.py" "C:/TradingScripts/launch_dashboard.py.bak-2026-04-22"
ls -la "C:/TradingScripts/" | grep bak-2026-04-22
```

Expected: both backup files listed.

- [ ] **Step 2: Create the tradelab web package directories**

```bash
mkdir -p "C:/TradingScripts/tradelab/src/tradelab/web"
mkdir -p "C:/TradingScripts/tradelab/tests/web"
```

- [ ] **Step 3: Create empty `__init__.py` markers**

Create `C:/TradingScripts/tradelab/src/tradelab/web/__init__.py` with contents:

```python
"""Web layer — HTTP endpoint handlers for the command_center Research tab."""
```

Create `C:/TradingScripts/tradelab/tests/web/__init__.py` as empty file.

- [ ] **Step 4: Verify pytest discovers the new directory**

```bash
cd C:/TradingScripts/tradelab
source /c/TradingScripts/.venv-vectorbt/Scripts/activate
pytest tests/web --collect-only 2>&1 | head
```

Expected: "no tests ran in X.XXs" or "collected 0 items" — confirms discovery works.

- [ ] **Step 5: Commit scaffold**

```bash
cd C:/TradingScripts/tradelab
git add src/tradelab/web/__init__.py tests/web/__init__.py
git commit -m "scaffold: tradelab.web package for Research tab endpoints"
```

---

## Task 1: Pytest fixtures

**Files:**
- Create: `C:\TradingScripts\tradelab\tests\web\conftest.py`

- [ ] **Step 1: Write the complete conftest.py**

Create `C:/TradingScripts/tradelab/tests/web/conftest.py`:

```python
"""Shared fixtures for web-layer tests."""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest


@pytest.fixture
def fake_tradelab_root(tmp_path: Path) -> Path:
    """Scaffolded tradelab root with data/, reports/, src/ subdirs."""
    (tmp_path / "data").mkdir()
    (tmp_path / "reports").mkdir()
    (tmp_path / "src" / "tradelab" / "strategies").mkdir(parents=True)
    (tmp_path / ".cache" / "ohlcv" / "1D").mkdir(parents=True)
    (tmp_path / ".cache" / "new_strategy_staging").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def fake_audit_db(fake_tradelab_root: Path) -> Path:
    """Audit DB pre-populated with 3 runs across 2 strategies."""
    db_path = fake_tradelab_root / "data" / "tradelab_history.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY,
            timestamp_utc TEXT NOT NULL,
            strategy_name TEXT NOT NULL,
            strategy_version TEXT,
            tradelab_version TEXT,
            tradelab_git_commit TEXT,
            input_data_hash TEXT,
            config_hash TEXT,
            verdict TEXT,
            dsr_probability REAL,
            report_card_markdown TEXT,
            report_card_html_path TEXT
        );
    """)
    now = datetime.now(timezone.utc)
    rows = [
        ("run-001", (now - timedelta(days=3)).isoformat(timespec="seconds"),
         "s2_pocket_pivot", None, None, None, None, None, "FRAGILE", 0.31, "# fragile", None),
        ("run-002", (now - timedelta(days=2)).isoformat(timespec="seconds"),
         "s4_inside_day_breakout", None, None, None, None, None, "ROBUST", 0.78, "# robust", None),
        ("run-003", (now - timedelta(days=1)).isoformat(timespec="seconds"),
         "s4_inside_day_breakout", None, None, None, None, None, "ROBUST", 0.81, "# robust2", None),
    ]
    conn.executemany(
        "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def fake_run_folder(fake_tradelab_root: Path) -> Path:
    """One run folder with backtest_result.json + placeholder HTML artifacts."""
    folder = fake_tradelab_root / "reports" / "s4_inside_day_breakout_2026-04-20_120000"
    folder.mkdir()
    metrics = {
        "strategy": "s4_inside_day_breakout",
        "metrics": {
            "total_trades": 44,
            "wins": 26,
            "losses": 18,
            "win_rate": 59.09,
            "profit_factor": 1.42,
            "net_pnl": 6340.12,
            "pct_return": 6.34,
            "annual_return": 3.12,
            "max_drawdown_pct": -6.8,
            "sharpe_ratio": 1.08,
        },
        "equity_curve": [
            {"date": "2024-01-01", "equity": 100000.0},
            {"date": "2026-04-20", "equity": 106340.12},
        ],
    }
    (folder / "backtest_result.json").write_text(json.dumps(metrics))
    (folder / "dashboard.html").write_text("<html>fake dashboard</html>")
    (folder / "quantstats_tearsheet.html").write_text("<html>fake qs</html>")
    (folder / "executive_report.md").write_text("# Verdict: ROBUST\n\nAll checks passed.\n")
    return folder


@pytest.fixture
def fake_parquet_cache(fake_tradelab_root: Path) -> Path:
    """Parquet cache dir with 3 fake symbol files with known mtimes."""
    cache = fake_tradelab_root / ".cache" / "ohlcv" / "1D"
    for sym in ("AAPL", "NVDA", "SPY"):
        p = cache / f"{sym}.parquet"
        p.write_bytes(b"fake")
    # Set mtimes: AAPL 2h old, NVDA 1h old, SPY just now
    now = time.time()
    (cache / "AAPL.parquet").touch()  # default = now
    import os
    os.utime(cache / "AAPL.parquet", (now - 7200, now - 7200))
    os.utime(cache / "NVDA.parquet", (now - 3600, now - 3600))
    return cache


@pytest.fixture
def fake_strategies_dir(fake_tradelab_root: Path) -> Path:
    """Empty tradelab strategies src dir."""
    return fake_tradelab_root / "src" / "tradelab" / "strategies"
```

- [ ] **Step 2: Run pytest to confirm fixtures import cleanly**

```bash
cd C:/TradingScripts/tradelab
pytest tests/web --collect-only -v 2>&1 | head -20
```

Expected: no collection errors; still 0 tests.

- [ ] **Step 3: Commit**

```bash
git add tests/web/conftest.py
git commit -m "test: add web-layer fixtures (fake audit DB, run folder, parquet cache)"
```

---

## Task 2: Audit DB reader

**Files:**
- Create: `C:\TradingScripts\tradelab\src\tradelab\web\audit_reader.py`
- Create: `C:\TradingScripts\tradelab\tests\web\test_audit_reader.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/web/test_audit_reader.py`:

```python
"""Tests for audit DB reader."""
from __future__ import annotations

from pathlib import Path

import pytest

from tradelab.web import audit_reader


def test_list_runs_returns_all_rows(fake_audit_db: Path):
    rows = audit_reader.list_runs(db_path=fake_audit_db)
    assert len(rows) == 3
    # Newest first
    assert rows[0]["run_id"] == "run-003"
    assert rows[-1]["run_id"] == "run-001"


def test_list_runs_filters_by_strategy(fake_audit_db: Path):
    rows = audit_reader.list_runs(strategy="s4_inside_day_breakout", db_path=fake_audit_db)
    assert len(rows) == 2
    assert all(r["strategy_name"] == "s4_inside_day_breakout" for r in rows)


def test_list_runs_filters_by_verdict(fake_audit_db: Path):
    rows = audit_reader.list_runs(verdicts=["FRAGILE"], db_path=fake_audit_db)
    assert len(rows) == 1
    assert rows[0]["verdict"] == "FRAGILE"


def test_list_runs_limit_and_offset(fake_audit_db: Path):
    rows = audit_reader.list_runs(limit=2, db_path=fake_audit_db)
    assert len(rows) == 2
    rows_page2 = audit_reader.list_runs(limit=2, offset=2, db_path=fake_audit_db)
    assert len(rows_page2) == 1


def test_list_runs_returns_empty_when_db_missing(tmp_path: Path):
    missing = tmp_path / "nope.db"
    rows = audit_reader.list_runs(db_path=missing)
    assert rows == []


def test_get_run_metrics_joins_backtest_json(fake_audit_db: Path, fake_run_folder: Path):
    # Point the audit row to the fake run folder
    import sqlite3
    conn = sqlite3.connect(str(fake_audit_db))
    conn.execute(
        "UPDATE runs SET report_card_html_path = ? WHERE run_id = 'run-003'",
        (str(fake_run_folder),),
    )
    conn.commit()
    conn.close()

    metrics = audit_reader.get_run_metrics(
        "run-003", db_path=fake_audit_db
    )
    assert metrics["profit_factor"] == 1.42
    assert metrics["total_trades"] == 44
    assert metrics["max_drawdown_pct"] == -6.8


def test_get_run_metrics_returns_empty_when_run_missing(fake_audit_db: Path):
    metrics = audit_reader.get_run_metrics(
        "does-not-exist", db_path=fake_audit_db
    )
    assert metrics == {}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd C:/TradingScripts/tradelab
pytest tests/web/test_audit_reader.py -v 2>&1 | tail -20
```

Expected: ImportError or ModuleNotFoundError ("No module named 'tradelab.web.audit_reader'").

- [ ] **Step 3: Implement audit_reader**

Create `src/tradelab/web/audit_reader.py`:

```python
"""Read tradelab_history.db and join per-run backtest_result.json metrics.

Audit DB schema lives in tradelab.audit.history — this module is a
read-only view for the web layer with filtering and pagination.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

_DEFAULT_DB = Path("data") / "tradelab_history.db"


def _resolve_db(db_path: Optional[Path]) -> Path:
    return Path(db_path) if db_path else _DEFAULT_DB


def list_runs(
    strategy: Optional[str] = None,
    verdicts: Optional[list[str]] = None,
    since: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db_path: Optional[Path] = None,
) -> list[dict]:
    """Return runs ordered by timestamp descending."""
    db = _resolve_db(db_path)
    if not db.exists():
        return []
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
        sql += " ORDER BY timestamp_utc DESC LIMIT ? OFFSET ?"
        args.extend([limit, offset])
        rows = conn.execute(sql, args).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def count_runs(
    strategy: Optional[str] = None,
    verdicts: Optional[list[str]] = None,
    since: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """Return total count matching filter — used for pagination UI."""
    db = _resolve_db(db_path)
    if not db.exists():
        return 0
    conn = sqlite3.connect(str(db))
    try:
        sql = "SELECT COUNT(*) FROM runs"
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
        (n,) = conn.execute(sql, args).fetchone()
    finally:
        conn.close()
    return int(n)


def get_run_metrics(run_id: str, db_path: Optional[Path] = None) -> dict:
    """Return the metrics dict from backtest_result.json for a given run.

    Looks up report_card_html_path from the audit DB, reads the JSON sibling.
    Returns {} if the run or the JSON is missing.
    """
    db = _resolve_db(db_path)
    if not db.exists():
        return {}
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT report_card_html_path FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row or not row[0]:
        return {}

    folder = Path(row[0])
    # report_card_html_path may point at the dashboard.html file or the folder
    if folder.is_file():
        folder = folder.parent
    json_path = folder / "backtest_result.json"
    if not json_path.exists():
        return {}
    try:
        data = json.loads(json_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return data.get("metrics", {}) or {}


def get_run_folder(run_id: str, db_path: Optional[Path] = None) -> Optional[Path]:
    """Return the run's reports folder (for iframe src construction)."""
    db = _resolve_db(db_path)
    if not db.exists():
        return None
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT report_card_html_path FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row or not row[0]:
        return None
    p = Path(row[0])
    return p if p.is_dir() else p.parent
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd C:/TradingScripts/tradelab
pytest tests/web/test_audit_reader.py -v 2>&1 | tail -20
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tradelab/web/audit_reader.py tests/web/test_audit_reader.py
git commit -m "feat(web): audit DB reader with strategy/verdict/date filters and backtest-json join"
```

---

## Task 3: Freshness reader

**Files:**
- Create: `C:\TradingScripts\tradelab\src\tradelab\web\freshness.py`
- Create: `C:\TradingScripts\tradelab\tests\web\test_freshness.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/web/test_freshness.py`:

```python
"""Tests for parquet cache freshness reader."""
from __future__ import annotations

from pathlib import Path

from tradelab.web import freshness


def test_freshness_reports_oldest_and_newest(fake_parquet_cache: Path):
    f = freshness.get_freshness(cache_root=fake_parquet_cache)
    assert f["symbol_count"] == 3
    # AAPL was set to 7200s old, NVDA 3600s, SPY ~now
    assert f["oldest_age_hours"] >= 1.9  # AAPL ~2h
    assert f["newest_age_hours"] < 0.1   # SPY < 6 min
    assert f["status"] == "fresh"  # <24h


def test_freshness_missing_cache_returns_unknown(tmp_path: Path):
    missing = tmp_path / "no-such-cache"
    f = freshness.get_freshness(cache_root=missing)
    assert f["status"] == "unknown"
    assert f["symbol_count"] == 0


def test_freshness_status_buckets(fake_parquet_cache: Path):
    # Backdate AAPL by 100 hours -> status should flip to "red"
    import os, time
    old_ts = time.time() - (100 * 3600)
    os.utime(fake_parquet_cache / "AAPL.parquet", (old_ts, old_ts))
    f = freshness.get_freshness(cache_root=fake_parquet_cache)
    assert f["status"] == "stale"  # >72h
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/web/test_freshness.py -v 2>&1 | tail -10
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement freshness**

Create `src/tradelab/web/freshness.py`:

```python
"""Parquet cache freshness — age of oldest/newest symbol file.

Reported values drive the color-coded banner at the top of the Research tab.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

_DEFAULT_CACHE = Path(".cache") / "ohlcv" / "1D"


def get_freshness(cache_root: Optional[Path] = None) -> dict:
    """Return age summary for parquet cache.

    Returned dict:
        symbol_count       -- number of *.parquet files found
        oldest_age_hours   -- age of the oldest file (None if empty)
        newest_age_hours   -- age of the newest file (None if empty)
        status             -- "fresh" (<24h) | "aging" (24-72h) | "stale" (>72h) | "unknown"
    """
    root = Path(cache_root) if cache_root else _DEFAULT_CACHE
    if not root.exists() or not root.is_dir():
        return {
            "symbol_count": 0,
            "oldest_age_hours": None,
            "newest_age_hours": None,
            "status": "unknown",
        }

    now = time.time()
    ages: list[float] = []
    for p in root.glob("*.parquet"):
        try:
            ages.append((now - p.stat().st_mtime) / 3600.0)
        except OSError:
            continue

    if not ages:
        return {
            "symbol_count": 0,
            "oldest_age_hours": None,
            "newest_age_hours": None,
            "status": "unknown",
        }

    oldest = max(ages)
    newest = min(ages)
    if oldest < 24.0:
        status = "fresh"
    elif oldest < 72.0:
        status = "aging"
    else:
        status = "stale"

    return {
        "symbol_count": len(ages),
        "oldest_age_hours": round(oldest, 2),
        "newest_age_hours": round(newest, 2),
        "status": status,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/web/test_freshness.py -v 2>&1 | tail -10
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/tradelab/web/freshness.py tests/web/test_freshness.py
git commit -m "feat(web): parquet cache freshness reader with 24h/72h status buckets"
```

---

## Task 4: Ranges reader (Claude's recommended slider ranges)

**Files:**
- Create: `C:\TradingScripts\tradelab\src\tradelab\web\ranges.py`
- Create: `C:\TradingScripts\tradelab\tests\web\test_ranges.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/web/test_ranges.py`:

```python
"""Tests for claude_ranges.json reader."""
from __future__ import annotations

import json
from pathlib import Path

from tradelab.web import ranges


def test_ranges_returns_none_when_missing(fake_strategies_dir: Path):
    result = ranges.get_ranges("does_not_exist", src_root=fake_strategies_dir.parent.parent.parent)
    assert result is None


def test_ranges_reads_sidecar_json(fake_strategies_dir: Path):
    strat_dir = fake_strategies_dir / "my_strategy"
    strat_dir.mkdir()
    sidecar = {
        "atr_period": {"min": 10, "max": 20, "default": 14, "step": 1, "claude_note": "stable"},
        "rsi_threshold": {"min": 25, "max": 45, "default": 30, "step": 1, "claude_note": "cliff <28"},
    }
    (strat_dir / "claude_ranges.json").write_text(json.dumps(sidecar))
    result = ranges.get_ranges("my_strategy", src_root=fake_strategies_dir.parent.parent.parent)
    assert result is not None
    assert result["atr_period"]["default"] == 14
    assert result["rsi_threshold"]["claude_note"] == "cliff <28"


def test_ranges_returns_none_on_invalid_json(fake_strategies_dir: Path):
    strat_dir = fake_strategies_dir / "broken"
    strat_dir.mkdir()
    (strat_dir / "claude_ranges.json").write_text("{ not valid json")
    result = ranges.get_ranges("broken", src_root=fake_strategies_dir.parent.parent.parent)
    assert result is None
```

- [ ] **Step 2: Implement ranges**

Create `src/tradelab/web/ranges.py`:

```python
"""Read Claude-recommended parameter ranges for What-If sliders.

Sidecar lives at src/tradelab/strategies/<name>/claude_ranges.json.
Schema per param: {min, max, default, step, claude_note}.

Presence of this file enables the What-If tab in the modal. Absence hides it.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

_DEFAULT_SRC = Path("src")


def get_ranges(strategy_name: str, src_root: Optional[Path] = None) -> Optional[dict]:
    """Return the parsed sidecar, or None if missing or malformed."""
    root = Path(src_root) if src_root else _DEFAULT_SRC
    path = root / "tradelab" / "strategies" / strategy_name / "claude_ranges.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/web/test_ranges.py -v 2>&1 | tail -10
```

Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git add src/tradelab/web/ranges.py tests/web/test_ranges.py
git commit -m "feat(web): claude_ranges.json sidecar reader for What-If sliders"
```

---

## Task 5: What-If single-symbol runner

**Files:**
- Create: `C:\TradingScripts\tradelab\src\tradelab\web\whatif.py`
- Create: `C:\TradingScripts\tradelab\tests\web\test_whatif.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/web/test_whatif.py`:

```python
"""Tests for What-If single-symbol backtest runner."""
from __future__ import annotations

import pytest

from tradelab.web import whatif


def test_whatif_rejects_unknown_strategy():
    with pytest.raises(whatif.WhatIfError) as exc:
        whatif.run_whatif(strategy_name="does_not_exist", symbol="AAPL", params={})
    assert "not registered" in str(exc.value).lower()


def test_whatif_returns_metrics_and_equity_curve(monkeypatch):
    """Integration test — uses a registered strategy against real Twelve Data cache.

    Skipped if the cache doesn't have AAPL (e.g. fresh dev checkout).
    """
    from pathlib import Path
    cache = Path(".cache") / "ohlcv" / "1D" / "AAPL.parquet"
    if not cache.exists():
        pytest.skip("AAPL parquet missing — run tradelab refresh first")
    result = whatif.run_whatif(
        strategy_name="s4_inside_day_breakout",
        symbol="AAPL",
        params={},
    )
    assert "metrics" in result
    assert "equity_curve" in result
    assert "profit_factor" in result["metrics"]
```

- [ ] **Step 2: Implement whatif**

Create `src/tradelab/web/whatif.py`:

```python
"""Single-symbol What-If backtest runner.

Loads a registered strategy, overrides params, runs one-symbol backtest
against the parquet cache, returns metrics + equity curve. Designed for
interactive slider debouncing on the Research tab modal.

Not for universe backtests — those go through `tradelab run` CLI.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from tradelab.engines.backtest import run_backtest
from tradelab.marketdata import cache
from tradelab.registry import instantiate_strategy, StrategyNotRegistered


class WhatIfError(Exception):
    pass


def _load_cached(symbols: list[str], timeframe: str) -> dict:
    """Read parquet cache for each symbol. Returns {symbol: df} (missing symbols omitted)."""
    data = {}
    for sym in symbols:
        df = cache.read(sym, timeframe)
        if df is not None and not df.empty:
            data[sym] = df
    return data


def run_whatif(
    strategy_name: str,
    symbol: str,
    params: dict,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> dict:
    """Run one-symbol backtest with param overrides.

    Args:
        strategy_name: registered strategy id
        symbol: single ticker, must be in parquet cache
        params: slider values; merged on top of strategy defaults
        start, end: optional date overrides; default to config window

    Returns:
        {metrics: {...}, equity_curve: [{date, equity}, ...]}

    Raises:
        WhatIfError on unknown strategy, missing data, or backtest failure.
    """
    try:
        strategy = instantiate_strategy(strategy_name, param_overrides=params)
    except StrategyNotRegistered as e:
        raise WhatIfError(f"strategy not registered: {e}") from e

    ticker_data = _load_cached([symbol], strategy.timeframe)
    if symbol not in ticker_data:
        raise WhatIfError(f"no data for {symbol} in parquet cache")

    spy_close = None
    if strategy.requires_benchmark:
        spy_data = _load_cached(["SPY"], strategy.timeframe)
        if "SPY" in spy_data:
            spy_close = spy_data["SPY"].set_index("Date")["Close"]

    try:
        result = run_backtest(
            strategy,
            ticker_data,
            start=start,
            end=end,
            spy_close=spy_close,
        )
    except Exception as e:
        raise WhatIfError(f"backtest failed: {e}") from e

    return {
        "metrics": _extract_metrics(result),
        "equity_curve": _extract_equity_curve(result),
        "params_used": dict(strategy.params),
    }


def _extract_metrics(result) -> dict:
    """Pull a stable subset of metrics from BacktestResult for the UI."""
    m = result.metrics if hasattr(result, "metrics") else {}
    if isinstance(m, dict):
        return {
            "profit_factor": m.get("profit_factor"),
            "win_rate": m.get("win_rate"),
            "max_drawdown_pct": m.get("max_drawdown_pct"),
            "total_trades": m.get("total_trades"),
            "net_pnl": m.get("net_pnl"),
            "sharpe_ratio": m.get("sharpe_ratio"),
            "annual_return": m.get("annual_return"),
        }
    return {}


def _extract_equity_curve(result) -> list[dict]:
    """Return equity curve as JSON-safe list of {date, equity} points."""
    curve = getattr(result, "equity_curve", None)
    if curve is None:
        return []
    if isinstance(curve, list) and curve and isinstance(curve[0], dict):
        return curve
    if isinstance(curve, pd.DataFrame):
        return [
            {"date": str(r["date"]), "equity": float(r["equity"])}
            for _, r in curve.iterrows()
        ]
    return []
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/web/test_whatif.py -v 2>&1 | tail -15
```

Expected: `test_whatif_rejects_unknown_strategy` passes. `test_whatif_returns_metrics_and_equity_curve` either passes (if AAPL parquet exists) or is skipped.

- [ ] **Step 4: Commit**

```bash
git add src/tradelab/web/whatif.py tests/web/test_whatif.py
git commit -m "feat(web): What-If single-symbol backtest runner for slider debouncing"
```

---

## Task 6: New Strategy paste/validate/register pipeline

**Files:**
- Create: `C:\TradingScripts\tradelab\src\tradelab\web\new_strategy.py`
- Create: `C:\TradingScripts\tradelab\tests\web\test_new_strategy.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/web/test_new_strategy.py`:

```python
"""Tests for paste-a-strategy flow."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from tradelab.web import new_strategy


MINIMAL_VALID_CODE = '''
from tradelab.strategies.base import Strategy
import pandas as pd

class MyTest(Strategy):
    default_params = {"lookback": 10}
    def generate_signals(self, data, spy_close=None):
        out = {}
        for sym, df in data.items():
            df = df.copy()
            df["buy_signal"] = False
            out[sym] = df
        return out
'''


def test_validate_rejects_bad_name_format(fake_tradelab_root: Path):
    result = new_strategy.validate_and_stage(
        name="Bad-Name!",
        code=MINIMAL_VALID_CODE,
        staging_root=fake_tradelab_root / ".cache" / "new_strategy_staging",
        src_root=fake_tradelab_root / "src",
    )
    assert result["error"]
    assert result["stage"] == "name"


def test_validate_rejects_name_collision(fake_tradelab_root: Path, monkeypatch):
    # Pretend s4_inside_day_breakout is already registered
    monkeypatch.setattr(
        new_strategy,
        "_is_registered",
        lambda n: n == "taken_name",
    )
    result = new_strategy.validate_and_stage(
        name="taken_name",
        code=MINIMAL_VALID_CODE,
        staging_root=fake_tradelab_root / ".cache" / "new_strategy_staging",
        src_root=fake_tradelab_root / "src",
    )
    assert result["error"]
    assert "already" in result["error"].lower()
    assert result["stage"] == "name"


def test_validate_rejects_syntax_error(fake_tradelab_root: Path, monkeypatch):
    monkeypatch.setattr(new_strategy, "_is_registered", lambda n: False)
    result = new_strategy.validate_and_stage(
        name="my_test",
        code="this is not valid python :::",
        staging_root=fake_tradelab_root / ".cache" / "new_strategy_staging",
        src_root=fake_tradelab_root / "src",
    )
    assert result["error"]
    assert result["stage"] == "import"


def test_validate_rejects_no_strategy_class(fake_tradelab_root: Path, monkeypatch):
    monkeypatch.setattr(new_strategy, "_is_registered", lambda n: False)
    result = new_strategy.validate_and_stage(
        name="my_test",
        code="x = 1\n",
        staging_root=fake_tradelab_root / ".cache" / "new_strategy_staging",
        src_root=fake_tradelab_root / "src",
    )
    assert result["error"]
    assert result["stage"] == "discover"


def test_discard_removes_staging_file(fake_tradelab_root: Path):
    staging = fake_tradelab_root / ".cache" / "new_strategy_staging"
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "my_test.py").write_text("pass")
    new_strategy.discard_staging("my_test", staging_root=staging)
    assert not (staging / "my_test.py").exists()


def test_cleanup_removes_old_files(fake_tradelab_root: Path):
    staging = fake_tradelab_root / ".cache" / "new_strategy_staging"
    staging.mkdir(parents=True, exist_ok=True)
    old = staging / "old.py"
    old.write_text("pass")
    import os, time
    old_ts = time.time() - (48 * 3600)  # 48h old
    os.utime(old, (old_ts, old_ts))
    fresh = staging / "fresh.py"
    fresh.write_text("pass")
    removed = new_strategy.cleanup_old_staging(staging_root=staging, max_age_hours=24)
    assert removed == 1
    assert not old.exists()
    assert fresh.exists()
```

- [ ] **Step 2: Implement new_strategy**

Create `src/tradelab/web/new_strategy.py`:

```python
"""Paste → stage → validate → register flow for the New Strategy modal.

Stages:
    1. name    — regex + collision check
    2. import  — write staged .py, run importlib, catch SyntaxError
    3. discover — require exactly one Strategy subclass
    4. instantiate — construct with defaults
    5. backtest — smoke_5 universe through run_backtest

Register does an atomic move to src/tradelab/strategies/ and appends to
tradelab.yaml's strategies: block.
"""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import sys
import time
import traceback
from pathlib import Path
from typing import Optional

from tradelab.registry import list_registered_strategies
from tradelab.strategies.base import Strategy


NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]+$")


def _is_registered(name: str) -> bool:
    """Separate function so tests can monkeypatch config access."""
    try:
        return name in list_registered_strategies()
    except Exception:
        return False


def validate_and_stage(
    name: str,
    code: str,
    staging_root: Path,
    src_root: Path,
) -> dict:
    """Run the full validation pipeline. Returns result dict.

    Success:   {error: None, stage: "complete", metrics, equity_curves_by_symbol}
    Failure:   {error: "<msg>", stage: "name"|"import"|"discover"|"instantiate"|"backtest"}

    Side effect on success: staged file at staging_root/<name>.py.
    Side effect on failure: staged file is removed.
    """
    staging_root.mkdir(parents=True, exist_ok=True)
    staging_file = staging_root / f"{name}.py"

    # Stage 1: name
    if not NAME_PATTERN.match(name):
        return {"error": f"name must match {NAME_PATTERN.pattern}", "stage": "name"}
    if _is_registered(name):
        return {"error": f"name '{name}' is already registered", "stage": "name"}

    # Stage 2: import
    staging_file.write_text(code)
    try:
        mod = _import_file(name, staging_file)
    except Exception as e:
        staging_file.unlink(missing_ok=True)
        return {
            "error": f"import failed: {e}",
            "stage": "import",
            "traceback": traceback.format_exc(),
        }

    # Stage 3: discover
    strategy_classes = [
        v for v in vars(mod).values()
        if isinstance(v, type) and issubclass(v, Strategy) and v is not Strategy
    ]
    if len(strategy_classes) != 1:
        staging_file.unlink(missing_ok=True)
        names = [c.__name__ for c in strategy_classes] or "(none)"
        return {
            "error": f"expected exactly one Strategy subclass, found: {names}",
            "stage": "discover",
        }
    StrategyClass = strategy_classes[0]

    # Stage 4: instantiate
    try:
        instance = StrategyClass(name=name)
    except Exception as e:
        staging_file.unlink(missing_ok=True)
        return {
            "error": f"constructor failed: {e}",
            "stage": "instantiate",
            "traceback": traceback.format_exc(),
        }

    # Stage 5: smoke_5 backtest
    try:
        metrics, equity_by_sym = _run_smoke_backtest(instance)
    except Exception as e:
        staging_file.unlink(missing_ok=True)
        return {
            "error": f"smoke_5 backtest failed: {e}",
            "stage": "backtest",
            "traceback": traceback.format_exc(),
        }

    return {
        "error": None,
        "stage": "complete",
        "metrics": metrics,
        "equity_curves_by_symbol": equity_by_sym,
        "class_name": StrategyClass.__name__,
    }


def register_strategy(
    name: str,
    class_name: str,
    staging_root: Path,
    src_root: Path,
    yaml_path: Optional[Path] = None,
) -> dict:
    """Move staged file into src/tradelab/strategies/ and append to tradelab.yaml.

    Returns {error, final_path} on result.
    """
    from tradelab.registry import list_registered_strategies
    # Re-check collision — could have been created while user viewed results
    if _is_registered(name):
        return {"error": f"name '{name}' is now taken (register blocked)", "final_path": None}

    staging_file = staging_root / f"{name}.py"
    if not staging_file.exists():
        return {"error": "staging file missing", "final_path": None}

    dest_dir = src_root / "tradelab" / "strategies"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / f"{name}.py"
    if dest_file.exists():
        return {"error": f"destination {dest_file} already exists", "final_path": None}

    # Atomic move
    shutil.move(str(staging_file), str(dest_file))

    # Append to tradelab.yaml strategies block
    if yaml_path is None:
        yaml_path = Path("tradelab.yaml")
    _append_strategy_to_yaml(yaml_path, name, class_name)

    return {"error": None, "final_path": str(dest_file)}


def discard_staging(name: str, staging_root: Path) -> None:
    """Delete staged file if present. No error if missing."""
    path = staging_root / f"{name}.py"
    path.unlink(missing_ok=True)


def cleanup_old_staging(staging_root: Path, max_age_hours: float = 24.0) -> int:
    """Remove staged files older than max_age_hours. Returns count removed."""
    if not staging_root.exists():
        return 0
    cutoff = time.time() - (max_age_hours * 3600)
    removed = 0
    for p in staging_root.glob("*.py"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                removed += 1
        except OSError:
            continue
    return removed


# ─── Internal helpers ─────────────────────────────────────────────────


def _import_file(name: str, path: Path):
    """Import a .py file as a module, isolated from normal import path."""
    mod_name = f"_tradelab_staged_{name}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not spec file {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(mod_name, None)
        raise
    return module


def _run_smoke_backtest(strategy) -> tuple[dict, dict]:
    """Run strategy against smoke_5 universe. Returns (metrics, equity_by_symbol)."""
    from tradelab.engines.backtest import run_backtest
    from tradelab.marketdata import cache
    from tradelab.config import get_config

    cfg = get_config()
    smoke_universe = cfg.universes.get("smoke_5", ["SPY", "NVDA", "MSFT", "AAPL", "META"])
    ticker_data = {}
    for sym in smoke_universe:
        df = cache.read(sym, strategy.timeframe)
        if df is not None and not df.empty:
            ticker_data[sym] = df
    if not ticker_data:
        raise RuntimeError(
            f"no smoke_5 data in cache for {smoke_universe} "
            f"at timeframe {strategy.timeframe} — refresh data first"
        )
    spy_close = None
    if strategy.requires_benchmark and "SPY" in ticker_data:
        spy_close = ticker_data["SPY"].set_index("Date")["Close"]

    result = run_backtest(strategy, ticker_data, spy_close=spy_close)
    metrics = getattr(result, "metrics", {}) or {}
    # Build per-symbol equity curves from the strategy's signals for visual overlay
    equity_by_sym: dict[str, list] = {}
    curve = getattr(result, "equity_curve", None)
    if curve is not None and not isinstance(curve, list):
        # Fallback: flatten into a single curve keyed as "portfolio"
        try:
            import pandas as pd
            if isinstance(curve, pd.DataFrame):
                equity_by_sym["portfolio"] = [
                    {"date": str(r["date"]), "equity": float(r["equity"])}
                    for _, r in curve.iterrows()
                ]
        except Exception:
            pass
    elif isinstance(curve, list):
        equity_by_sym["portfolio"] = curve
    return dict(metrics), equity_by_sym


def _append_strategy_to_yaml(yaml_path: Path, name: str, class_name: str) -> None:
    """Append a strategy entry to tradelab.yaml under strategies:.

    Naive line-append — avoids introducing a YAML round-trip library dep.
    tradelab.yaml is small and user-maintained; this is low risk.
    """
    if not yaml_path.exists():
        raise FileNotFoundError(f"tradelab.yaml not found at {yaml_path}")

    entry = (
        f"\n  {name}:\n"
        f"    module: tradelab.strategies.{name}\n"
        f"    class_name: {class_name}\n"
        f"    params: {{}}\n"
    )
    text = yaml_path.read_text()
    if f"  {name}:" in text:
        return  # already present — idempotent
    # Find "strategies:" block and append at the end of it
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    in_strategies = False
    inserted = False
    for i, line in enumerate(lines):
        out.append(line)
        if line.rstrip() == "strategies:":
            in_strategies = True
            continue
        if in_strategies and not inserted:
            # Check if next line is at top level (no indent) — end of block
            is_last = i == len(lines) - 1
            next_line = lines[i + 1] if not is_last else ""
            next_is_top_level = bool(next_line) and not next_line.startswith((" ", "\t"))
            if is_last or next_is_top_level:
                out.append(entry)
                inserted = True
    if not inserted:
        # Defensive: no strategies block found; append to end
        out.append("\nstrategies:" + entry)
    yaml_path.write_text("".join(out))
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/web/test_new_strategy.py -v 2>&1 | tail -15
```

Expected: 6 passed.

- [ ] **Step 4: Commit**

```bash
git add src/tradelab/web/new_strategy.py tests/web/test_new_strategy.py
git commit -m "feat(web): paste-to-test new strategy pipeline with smoke_5 validation"
```

---

## Task 7: Request handlers (dispatch layer)

**Files:**
- Create: `C:\TradingScripts\tradelab\src\tradelab\web\handlers.py`
- Create: `C:\TradingScripts\tradelab\tests\web\test_handlers.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/web/test_handlers.py`:

```python
"""Integration tests for request handlers (dispatch layer)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tradelab.web import handlers


def test_handle_runs_list(fake_audit_db: Path, monkeypatch):
    monkeypatch.setattr(handlers, "_db_path", lambda: fake_audit_db)
    monkeypatch.setattr(handlers, "_cache_root", lambda: Path("."))
    monkeypatch.setattr(handlers, "_src_root", lambda: Path("src"))

    body = handlers.handle_get("/tradelab/runs")
    data = json.loads(body)
    assert data["error"] is None
    assert len(data["data"]["runs"]) == 3
    assert data["data"]["total"] == 3


def test_handle_runs_list_with_query(fake_audit_db: Path, monkeypatch):
    monkeypatch.setattr(handlers, "_db_path", lambda: fake_audit_db)
    monkeypatch.setattr(handlers, "_cache_root", lambda: Path("."))
    monkeypatch.setattr(handlers, "_src_root", lambda: Path("src"))

    body = handlers.handle_get("/tradelab/runs?strategy=s4_inside_day_breakout&limit=10")
    data = json.loads(body)
    assert len(data["data"]["runs"]) == 2


def test_handle_data_freshness(fake_parquet_cache: Path, monkeypatch):
    monkeypatch.setattr(handlers, "_cache_root", lambda: fake_parquet_cache)
    monkeypatch.setattr(handlers, "_db_path", lambda: Path("nope.db"))
    monkeypatch.setattr(handlers, "_src_root", lambda: Path("src"))

    body = handlers.handle_get("/tradelab/data-freshness")
    data = json.loads(body)
    assert data["error"] is None
    assert data["data"]["symbol_count"] == 3


def test_handle_unknown_route_returns_404_shape():
    body, status = handlers.handle_get_with_status("/tradelab/nope")
    assert status == 404
    data = json.loads(body)
    assert data["error"] == "not found"


def test_handle_new_strategy_test_action(fake_tradelab_root: Path, monkeypatch):
    monkeypatch.setattr(handlers, "_db_path", lambda: Path("nope.db"))
    monkeypatch.setattr(handlers, "_cache_root", lambda: Path("."))
    monkeypatch.setattr(handlers, "_src_root", lambda: fake_tradelab_root / "src")
    monkeypatch.setattr(handlers, "_staging_root", lambda: fake_tradelab_root / ".cache" / "new_strategy_staging")

    from tradelab.web import new_strategy
    monkeypatch.setattr(new_strategy, "_is_registered", lambda n: False)

    payload = {
        "action": "discard",
        "name": "ghost_strat",
    }
    body = handlers.handle_post("/tradelab/new-strategy", json.dumps(payload).encode())
    data = json.loads(body)
    # Discard of non-existent staging is idempotent — error is None
    assert data["error"] is None
```

- [ ] **Step 2: Implement handlers**

Create `src/tradelab/web/handlers.py`:

```python
"""HTTP request handlers for /tradelab/* routes.

Pure dispatch — no HTTP server framework. launch_dashboard.py's
SimpleHTTPRequestHandler calls into these functions and writes the
returned JSON body with the returned status code.

Response envelope: {"error": null|str, "data": <payload>}.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import parse_qs, urlparse

from tradelab.web import audit_reader, freshness, new_strategy, ranges, whatif


# ─── Configurable roots (monkeypatched in tests) ─────────────────────


def _db_path() -> Path:
    return Path("data") / "tradelab_history.db"


def _cache_root() -> Path:
    return Path(".cache") / "ohlcv" / "1D"


def _src_root() -> Path:
    return Path("src")


def _staging_root() -> Path:
    return Path(".cache") / "new_strategy_staging"


def _reports_root() -> Path:
    return Path("reports")


def _yaml_path() -> Path:
    return Path("tradelab.yaml")


# ─── Public entry points ─────────────────────────────────────────────


def handle_get(path_with_query: str) -> str:
    """GET dispatcher. Returns JSON body. Status is 200 except 404s (see _with_status)."""
    body, _ = handle_get_with_status(path_with_query)
    return body


def handle_get_with_status(path_with_query: str) -> Tuple[str, int]:
    """GET dispatcher with explicit status code."""
    parsed = urlparse(path_with_query)
    path = parsed.path
    q = {k: v[0] for k, v in parse_qs(parsed.query).items()}

    if path == "/tradelab/runs":
        return _ok({
            "runs": audit_reader.list_runs(
                strategy=q.get("strategy") or None,
                verdicts=[v for v in q.get("verdict", "").split(",") if v] or None,
                since=q.get("since") or None,
                limit=int(q.get("limit", 50)),
                offset=int(q.get("offset", 0)),
                db_path=_db_path(),
            ),
            "total": audit_reader.count_runs(
                strategy=q.get("strategy") or None,
                verdicts=[v for v in q.get("verdict", "").split(",") if v] or None,
                since=q.get("since") or None,
                db_path=_db_path(),
            ),
        }), 200

    m = re.match(r"^/tradelab/runs/([^/]+)/metrics$", path)
    if m:
        return _ok(audit_reader.get_run_metrics(m.group(1), db_path=_db_path())), 200

    if path == "/tradelab/data-freshness":
        return _ok(freshness.get_freshness(cache_root=_cache_root())), 200

    m = re.match(r"^/tradelab/ranges/([^/]+)$", path)
    if m:
        r = ranges.get_ranges(m.group(1), src_root=_src_root())
        if r is None:
            return _ok({"ranges": None}), 200
        return _ok({"ranges": r}), 200

    if path == "/tradelab/strategies":
        from tradelab.registry import list_registered_strategies
        try:
            strategies = list(list_registered_strategies().keys())
        except Exception as e:
            return _err(f"registry error: {e}"), 200
        return _ok({"strategies": strategies}), 200

    return _err("not found"), 404


def handle_post(path: str, body: bytes) -> str:
    """POST dispatcher. All POSTs return 200 with envelope (error may be set)."""
    try:
        payload = json.loads(body.decode()) if body else {}
    except json.JSONDecodeError:
        return _err("invalid JSON body")

    if path == "/tradelab/whatif":
        try:
            result = whatif.run_whatif(
                strategy_name=payload["strategy"],
                symbol=payload["symbol"],
                params=payload.get("params") or {},
                start=payload.get("start"),
                end=payload.get("end"),
            )
            return _ok(result)
        except whatif.WhatIfError as e:
            return _err(str(e))
        except KeyError as e:
            return _err(f"missing required field: {e}")

    if path == "/tradelab/new-strategy":
        action = payload.get("action", "test")
        name = payload.get("name", "")

        if action == "test":
            code = payload.get("code", "")
            result = new_strategy.validate_and_stage(
                name=name,
                code=code,
                staging_root=_staging_root(),
                src_root=_src_root(),
            )
            # result already contains error/stage or success metrics
            if result.get("error"):
                return _err(result["error"], data={"stage": result.get("stage"), "traceback": result.get("traceback")})
            return _ok({
                "metrics": result.get("metrics", {}),
                "equity_curves_by_symbol": result.get("equity_curves_by_symbol", {}),
                "class_name": result.get("class_name"),
            })

        if action == "register":
            class_name = payload.get("class_name", "")
            reg = new_strategy.register_strategy(
                name=name,
                class_name=class_name,
                staging_root=_staging_root(),
                src_root=_src_root(),
                yaml_path=_yaml_path(),
            )
            if reg.get("error"):
                return _err(reg["error"])
            # Kick off background robustness run; don't wait
            subprocess.Popen(
                [sys.executable, "-m", "tradelab.cli", "run", name, "--robustness"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return _ok({"final_path": reg["final_path"], "robustness_started": True})

        if action == "discard":
            new_strategy.discard_staging(name, staging_root=_staging_root())
            return _ok({"discarded": name})

        return _err(f"unknown action: {action}")

    if path == "/tradelab/refresh-data":
        # Fire-and-forget: launcher polls /tradelab/data-freshness afterward
        try:
            from tradelab.marketdata import download_symbols
            from tradelab.config import get_config
            cfg = get_config()
            universe_name = payload.get("universe") or cfg.defaults.universe
            symbols = cfg.universes[universe_name]
            download_symbols(symbols)
            return _ok({"refreshed": len(symbols), "universe": universe_name})
        except Exception as e:
            return _err(f"refresh failed: {e}")

    return _err("not found")


# ─── Envelope helpers ────────────────────────────────────────────────


def _ok(data) -> str:
    return json.dumps({"error": None, "data": data})


def _err(msg: str, data=None) -> str:
    return json.dumps({"error": msg, "data": data})
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/web/test_handlers.py -v 2>&1 | tail -15
```

Expected: 5 passed.

- [ ] **Step 4: Commit**

```bash
git add src/tradelab/web/handlers.py tests/web/test_handlers.py
git commit -m "feat(web): HTTP route dispatcher for /tradelab/* endpoints"
```

---

## Task 8: Wire handlers into launch_dashboard.py

**Files:**
- Modify: `C:\TradingScripts\launch_dashboard.py` (entire file — small enough to rewrite)

- [ ] **Step 1: Verify the backup exists**

```bash
ls -la "C:/TradingScripts/launch_dashboard.py.bak-2026-04-22"
```

Expected: backup file present. If missing, re-run Task 0 Step 1.

- [ ] **Step 2: Rewrite launch_dashboard.py with the new routes**

Replace `C:\TradingScripts\launch_dashboard.py` with:

```python
#!/usr/bin/env python3
"""
AlgoTrade Dashboard Launcher
Starts a local HTTP server that serves the dashboard, proxies Alpaca API calls,
and dispatches /tradelab/* requests to the tradelab.web handlers.
Usage: python launch_dashboard.py
"""
import json
import os
import sys
import threading
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.error import HTTPError
from urllib.request import Request, urlopen

PORT = 8877
DIR = os.path.dirname(os.path.abspath(__file__))

# Make tradelab importable (add its src/ to sys.path)
TRADELAB_SRC = os.path.join(DIR, "tradelab", "src")
if os.path.isdir(TRADELAB_SRC) and TRADELAB_SRC not in sys.path:
    sys.path.insert(0, TRADELAB_SRC)

# Change working directory to tradelab root so relative paths (data/, reports/,
# .cache/, tradelab.yaml) resolve correctly for the handler helpers.
TRADELAB_ROOT = os.path.join(DIR, "tradelab")
if os.path.isdir(TRADELAB_ROOT):
    os.chdir(TRADELAB_ROOT)

# Try to import tradelab.web.handlers. Soft dependency — Research tab is disabled
# if import fails, but live-trading tabs keep working.
_handlers = None
_handlers_error = None
try:
    from tradelab.web import handlers as _handlers  # type: ignore
    # Run a startup-time cleanup of old staging files
    try:
        from tradelab.web.new_strategy import cleanup_old_staging
        cleanup_old_staging(_handlers._staging_root(), max_age_hours=24)
    except Exception as e:
        print(f"[startup] staging cleanup skipped: {e}", file=sys.stderr)
except Exception as e:
    _handlers_error = str(e)
    print(f"[startup] tradelab.web not available: {e}", file=sys.stderr)

# Load Alpaca config (from the parent TradingScripts dir, not the tradelab cwd)
with open(os.path.join(DIR, "alpaca_config.json")) as f:
    cfg = json.load(f)

ALPACA_BASE = cfg["alpaca"]["base_url"]
ALPACA_KEY = cfg["alpaca"]["api_key"]
ALPACA_SECRET = cfg["alpaca"]["secret_key"]


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIR, **kwargs)

    # ─── GET ────────────────────────────────────────────────────────

    def do_GET(self):
        try:
            if self.path.startswith("/api/"):
                self.proxy_alpaca()
            elif self.path.startswith("/tradelab/") and not self.path.startswith("/tradelab/reports/"):
                self.dispatch_tradelab_get()
            elif self.path.startswith("/tradelab/reports/"):
                # Serve static files from tradelab/reports/
                self.serve_tradelab_static()
            elif self.path == "/config":
                self.serve_config()
            elif self.path == "/" or self.path == "":
                self.path = "/command_center.html"
                super().do_GET()
            else:
                super().do_GET()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass

    def do_POST(self):
        try:
            if self.path.startswith("/tradelab/"):
                self.dispatch_tradelab_post()
            elif self.path == "/config":
                self.write_config()
            else:
                self.send_error(404)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass

    # ─── Alpaca proxy (unchanged from prior version) ────────────────

    def proxy_alpaca(self):
        alpaca_path = self.path[4:]  # strip /api
        url = ALPACA_BASE + alpaca_path
        try:
            req = Request(url)
            req.add_header("APCA-API-KEY-ID", ALPACA_KEY)
            req.add_header("APCA-API-SECRET-KEY", ALPACA_SECRET)
            resp = urlopen(req, timeout=10)
            self._write_json(200, resp.read())
        except HTTPError as e:
            self._write_json(e.code, json.dumps({"error": str(e)}).encode())
        except Exception as e:
            self._write_json(500, json.dumps({"error": str(e)}).encode())

    # ─── /tradelab/* dispatch ───────────────────────────────────────

    def dispatch_tradelab_get(self):
        if _handlers is None:
            self._write_json(503, json.dumps(
                {"error": f"research offline: {_handlers_error}", "data": None}
            ).encode())
            return
        body, status = _handlers.handle_get_with_status(self.path)
        self._write_json(status, body.encode())

    def dispatch_tradelab_post(self):
        if _handlers is None:
            self._write_json(503, json.dumps(
                {"error": f"research offline: {_handlers_error}", "data": None}
            ).encode())
            return
        length = int(self.headers.get("Content-Length", 0))
        body_in = self.rfile.read(length) if length else b""
        body_out = _handlers.handle_post(self.path, body_in)
        self._write_json(200, body_out.encode())

    def serve_tradelab_static(self):
        """Serve files under /tradelab/reports/ from tradelab/reports/."""
        # self.path is like /tradelab/reports/s4_.../dashboard.html
        rel = self.path[len("/tradelab/"):]  # -> reports/...
        full = os.path.join(TRADELAB_ROOT, rel)
        if not os.path.isfile(full):
            self.send_error(404)
            return
        # Temporarily adjust directory handling
        ext = os.path.splitext(full)[1].lower()
        ctype = {"html": "text/html", "json": "application/json", "css": "text/css",
                 "js": "application/javascript"}.get(ext.lstrip("."), "application/octet-stream")
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ─── Config (unchanged) ─────────────────────────────────────────

    def serve_config(self):
        try:
            with open(os.path.join(DIR, "alpaca_config.json")) as f:
                c = json.load(f)
            trading = c.get("trading", {})
            payload = {
                "daily_loss_limit": trading.get("daily_loss_limit", -5000),
                "max_portfolio_exposure": trading.get("max_portfolio_exposure", 0.95),
                "kill_switch": trading.get("kill_switch", False),
                "disabled_strategies": c.get("disabled_strategies", []),
            }
            self._write_json(200, json.dumps(payload).encode())
        except Exception as e:
            self._write_json(500, json.dumps({"error": str(e)}).encode())

    def write_config(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
            path = os.path.join(DIR, "alpaca_config.json")
            with open(path) as f:
                c = json.load(f)
            # Only these two fields are writable from the UI
            if "disabled_strategies" in payload:
                c["disabled_strategies"] = payload["disabled_strategies"]
            if "kill_switch" in payload:
                c.setdefault("trading", {})["kill_switch"] = bool(payload["kill_switch"])
            with open(path, "w") as f:
                json.dump(c, f, indent=2)
            self._write_json(200, json.dumps({"ok": True}).encode())
        except Exception as e:
            self._write_json(500, json.dumps({"error": str(e)}).encode())

    # ─── Helpers ─────────────────────────────────────────────────────

    def _write_json(self, status: int, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        if "404" in str(args) or "500" in str(args) or "503" in str(args):
            super().log_message(format, *args)


def main():
    server = HTTPServer(("127.0.0.1", PORT), DashboardHandler)
    url = f"http://localhost:{PORT}/"
    print("╔══════════════════════════════════════════════════╗")
    print("║  AlgoTrade Command Center + Research — LIVE     ║")
    print(f"║  Dashboard: {url:<37s}║")
    print(f"║  Alpaca:    {ALPACA_BASE:<37s}║")
    print(f"║  Research:  {'ONLINE' if _handlers else 'OFFLINE':<37s}║")
    print("║  Ctrl+C to stop                                 ║")
    print("╚══════════════════════════════════════════════════╝")

    threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down dashboard server...")
        server.shutdown()


if __name__ == "__main__":
    main()
```

> **Note:** existing `launch_dashboard.py` preserved `disabled_strategies` behavior via the `/config` route; the rewrite preserves it. If the original had other writable fields, diff against the backup before committing.

- [ ] **Step 3: Manual smoke — start the server and verify it boots**

```bash
cd C:/TradingScripts
python launch_dashboard.py
```

Expected: banner shows "Research: ONLINE" and the browser opens. Close with Ctrl+C.

If "Research: OFFLINE" appears, stop and read the `[startup] tradelab.web not available:` message; fix the import path issue before continuing.

- [ ] **Step 4: Hit the new endpoints manually**

While server is running, in a second terminal:

```bash
curl -s http://localhost:8877/tradelab/data-freshness
curl -s "http://localhost:8877/tradelab/runs?limit=5"
curl -s http://localhost:8877/tradelab/strategies
```

Expected: JSON responses with `"error": null` envelope. Runs may be empty if audit DB has no rows on this machine — that's fine, the response shape is what matters.

- [ ] **Step 5: Commit (no git commit — this file is outside the repo; note in change log instead)**

Since `C:\TradingScripts\` is not a git repo, there is no commit step. Record this change manually:

```bash
echo "2026-04-22 — launch_dashboard.py updated to dispatch /tradelab/* to tradelab.web.handlers. Backup: launch_dashboard.py.bak-2026-04-22" >> "C:/TradingScripts/CHANGELOG-research-tab.txt"
```

---

## Task 9: command_center.html — register Research tab + CSS

**Files:**
- Modify: `C:\TradingScripts\command_center.html`

- [ ] **Step 1: Verify backup exists**

```bash
ls -la "C:/TradingScripts/command_center.html.bak-2026-04-22"
```

- [ ] **Step 2: Register the tab in the tab bar**

In `C:\TradingScripts\command_center.html`, find the line:

```html
    <div class="tab" data-tab="settings">Settings</div>
```

Add immediately after it (before `</div>` closing the `.tabs` container):

```html
    <div class="tab" data-tab="research">Research</div>
```

- [ ] **Step 3: Add the Research tab-content block**

Find the closing `</div>` of the Settings tab-content (search the file for `id="tab-settings"` and find its matching close). After it, before the `</div>` that closes `.main`, insert:

```html
    <!-- RESEARCH TAB -->
    <div id="tab-research" class="tab-content">
      <div class="research-banner" id="researchFreshnessBanner">
        <div class="research-banner-text" id="researchFreshnessText">Loading data freshness...</div>
        <div class="research-banner-actions">
          <button class="btn" id="researchRefreshDataBtn">↻ Refresh Data</button>
          <button class="btn primary" id="researchNewStrategyBtn">+ New Strategy</button>
        </div>
      </div>

      <h3 class="research-section-title">Live Strategies — tradelab health</h3>
      <div class="research-cards-grid" id="researchLiveCards">
        <div class="research-skeleton" style="height:180px"></div>
        <div class="research-skeleton" style="height:180px"></div>
        <div class="research-skeleton" style="height:180px"></div>
      </div>

      <h3 class="research-section-title">Research Pipeline</h3>
      <div class="research-filters">
        <select id="researchFilterStrategy" class="settings-input"><option value="">All strategies</option></select>
        <select id="researchFilterVerdict" class="settings-input">
          <option value="">All verdicts</option>
          <option value="ROBUST">ROBUST</option>
          <option value="MARGINAL">MARGINAL</option>
          <option value="FRAGILE">FRAGILE</option>
          <option value="INCONCLUSIVE">INCONCLUSIVE</option>
        </select>
        <select id="researchFilterSince" class="settings-input">
          <option value="7">Last 7 days</option>
          <option value="30" selected>Last 30 days</option>
          <option value="90">Last 90 days</option>
          <option value="">All time</option>
        </select>
        <button class="btn" id="researchFilterClear">Clear</button>
      </div>

      <div class="table-wrapper">
        <div class="table-title">Runs <span id="researchPipelineCount" class="kpi-sublabel"></span></div>
        <table class="table" id="researchPipelineTable">
          <thead>
            <tr>
              <th data-sort="strategy_name">Strategy</th>
              <th data-sort="verdict">Verdict</th>
              <th data-sort="pf">PF</th>
              <th data-sort="win_rate">WR</th>
              <th data-sort="max_drawdown_pct">DD</th>
              <th data-sort="total_trades">Trd</th>
              <th data-sort="dsr_probability">DSR</th>
              <th data-sort="timestamp_utc">Date</th>
            </tr>
          </thead>
          <tbody id="researchPipelineBody">
            <tr><td colspan="8" class="research-skeleton-row">Loading...</td></tr>
          </tbody>
        </table>
        <div class="research-pagination">
          <button class="btn" id="researchLoadMoreBtn" style="display:none">Show 50 more</button>
        </div>
      </div>

      <!-- Modal overlay (hidden by default) -->
      <div class="research-modal" id="researchModal">
        <div class="research-modal-box">
          <div class="research-modal-header">
            <div class="research-modal-title" id="researchModalTitle">Strategy · Verdict · Date</div>
            <button class="research-modal-close" id="researchModalClose">×</button>
          </div>
          <div class="research-modal-tabs" id="researchModalTabs">
            <div class="tab active" data-modal-tab="dashboard">Dashboard</div>
            <div class="tab" data-modal-tab="quantstats">QuantStats</div>
            <div class="tab" data-modal-tab="whatif">What-If</div>
          </div>
          <div class="research-modal-body" id="researchModalBody">
            <iframe id="researchModalIframe" style="display:none"></iframe>
            <div id="researchModalWhatif" style="display:none"></div>
          </div>
        </div>
      </div>

      <!-- New Strategy modal -->
      <div class="research-modal" id="researchNewStrategyModal">
        <div class="research-modal-box">
          <div class="research-modal-header">
            <div class="research-modal-title">New Strategy</div>
            <button class="research-modal-close" id="researchNewStrategyClose">×</button>
          </div>
          <div class="research-modal-body" id="researchNewStrategyBody">
            <div style="padding:20px">
              <div class="settings-field" style="margin-bottom:12px">
                <label class="settings-label">Strategy name (snake_case)</label>
                <input id="nsName" class="settings-input" placeholder="my_momentum_breakout">
              </div>
              <div class="settings-field" style="margin-bottom:12px">
                <label class="settings-label">Paste Python strategy code</label>
                <textarea id="nsCode" class="export-textarea" style="height:340px;font-family:'Consolas','Monaco',monospace"></textarea>
              </div>
              <div id="nsResults"></div>
              <div style="display:flex;gap:12px;justify-content:flex-end">
                <button class="btn" id="nsCancel">Cancel</button>
                <button class="btn primary" id="nsTest">Test (smoke_5, ~15s)</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
```

- [ ] **Step 4: Add the Research-tab CSS block**

Find the closing `</style>` tag at the end of the `<style>` block near the top of the file. Before it, insert:

```css
    /* ═══ Research tab ═══ */
    .research-banner{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:14px 18px;margin-bottom:20px;display:flex;justify-content:space-between;align-items:center;gap:16px}
    .research-banner.fresh{background:var(--green-bg);border-color:var(--green-border)}
    .research-banner.aging{background:var(--amber-bg);border-color:var(--amber-border)}
    .research-banner.stale{background:var(--red-bg);border-color:var(--red-border)}
    .research-banner-text{font-size:14px;color:var(--text);font-weight:500}
    .research-banner-actions{display:flex;gap:10px}

    .research-section-title{font-size:14px;text-transform:uppercase;letter-spacing:.5px;color:var(--text2);margin:24px 0 12px;font-weight:600}

    .research-cards-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:var(--gap);margin-bottom:20px}
    .research-card{background:var(--card);border:1px solid var(--border);border-left:4px solid var(--border);border-radius:var(--radius);padding:16px;transition:all .3s}
    .research-card:hover{border-color:var(--text3);transform:translateY(-2px)}
    .research-card.verdict-robust{border-left-color:var(--green)}
    .research-card.verdict-marginal{border-left-color:var(--amber)}
    .research-card.verdict-fragile{border-left-color:var(--red)}
    .research-card.degraded{animation:pulse-amber 2.5s ease-in-out infinite}
    @keyframes pulse-amber{0%,100%{box-shadow:0 0 0 1px var(--amber-border),0 0 14px rgba(234,179,8,.15)}50%{box-shadow:0 0 0 1px var(--amber-border),0 0 22px rgba(234,179,8,.35)}}
    .research-card-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
    .research-card-name{font-weight:600;color:var(--text)}
    .research-card-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;font-size:12px;margin:10px 0}
    .research-card-stat{background:var(--surface);padding:6px 8px;border-radius:4px}
    .research-card-stat-label{color:var(--text3);font-size:10px;text-transform:uppercase}
    .research-card-stat-value{color:var(--text);font-weight:600;font-size:14px}
    .research-card-trend{font-size:11px;color:var(--text3);margin:6px 0;letter-spacing:2px;font-family:monospace}
    .research-card-actions{display:flex;gap:8px;margin-top:10px}
    .research-card-actions .btn{font-size:12px;padding:6px 10px}

    .verdict-pill{display:inline-block;padding:3px 10px;border-radius:4px;font-size:11px;font-weight:700;letter-spacing:.5px;text-transform:uppercase}
    .verdict-pill.verdict-robust{background:var(--green-bg);color:var(--green);border:1px solid var(--green-border)}
    .verdict-pill.verdict-marginal{background:var(--amber-bg);color:var(--amber);border:1px solid var(--amber-border)}
    .verdict-pill.verdict-fragile{background:var(--red-bg);color:var(--red);border:1px solid var(--red-border)}
    .verdict-pill.verdict-inconclusive{background:var(--border);color:var(--text2)}

    .research-filters{display:flex;gap:10px;margin-bottom:12px;align-items:center;flex-wrap:wrap}
    .research-filters select, .research-filters button{font-size:13px}

    .research-pagination{padding:14px;text-align:center;border-top:1px solid var(--border)}

    .research-skeleton{background:linear-gradient(90deg,var(--surface) 0%,var(--card) 50%,var(--surface) 100%);background-size:200% 100%;animation:shimmer 1.6s infinite;border-radius:var(--radius)}
    .research-skeleton-row{padding:20px;text-align:center;color:var(--text3)}
    @keyframes shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}

    /* Modal */
    .research-modal{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.75);z-index:2000;justify-content:center;align-items:center;padding:5vh 5vw}
    .research-modal.show{display:flex}
    .research-modal-box{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);width:90vw;max-width:1800px;height:90vh;display:flex;flex-direction:column;box-shadow:0 20px 60px rgba(0,0,0,.6)}
    .research-modal-header{padding:14px 18px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center}
    .research-modal-title{font-weight:600;color:var(--text);font-size:16px}
    .research-modal-close{background:transparent;border:none;color:var(--text2);font-size:28px;cursor:pointer;line-height:1;padding:0 8px}
    .research-modal-close:hover{color:var(--text)}
    .research-modal-tabs{display:flex;gap:20px;padding:0 18px;border-bottom:1px solid var(--border);background:var(--surface)}
    .research-modal-body{flex:1;overflow:hidden;position:relative}
    .research-modal-body iframe{width:100%;height:100%;border:0;background:var(--card)}

    /* What-If panel */
    .whatif-panel{padding:20px;height:100%;overflow:auto;color:var(--text)}
    .whatif-controls{display:flex;gap:12px;margin-bottom:16px;align-items:center;flex-wrap:wrap}
    .whatif-sliders{display:flex;flex-direction:column;gap:14px;margin-bottom:20px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:16px}
    .whatif-slider-row{display:grid;grid-template-columns:180px 1fr 80px 160px;gap:12px;align-items:center}
    .whatif-slider-row input[type=range]{accent-color:var(--green)}
    .whatif-slider-row .claude-note{font-size:11px;color:var(--text3);font-style:italic}
    .whatif-result{display:grid;grid-template-columns:260px 1fr;gap:16px}
    .whatif-metrics{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:14px}
    .whatif-metric-row{display:flex;justify-content:space-between;padding:6px 0;font-size:14px;border-bottom:1px solid var(--border)}
    .whatif-metric-row:last-child{border-bottom:0}
    .whatif-chart{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:14px;min-height:280px;position:relative}
    .whatif-loading{opacity:.5;pointer-events:none}
```

- [ ] **Step 5: Manual smoke — open the tab, confirm empty structure renders**

Start the server (`python C:/TradingScripts/launch_dashboard.py`), open http://localhost:8877, click the new "Research" tab.

Expected: freshness banner placeholder, two section titles, skeleton placeholder cards, skeleton table row, no JS errors in DevTools console.

- [ ] **Step 6: Record change (no git commit)**

```bash
echo "2026-04-22 — command_center.html: added Research tab HTML + CSS. Backup: command_center.html.bak-2026-04-22" >> "C:/TradingScripts/CHANGELOG-research-tab.txt"
```

---

## Task 10: command_center.html — Research tab JS module

**Files:**
- Modify: `C:\TradingScripts\command_center.html`

- [ ] **Step 1: Add the Research JS module**

Find the closing `</script>` tag at the end of the HTML file's last `<script>` block. Before it, insert:

```javascript
    // ═══ Research tab ═══════════════════════════════════════════════

    const LIVE_STRATS = ['S2_PocketPivot','S4_InsideDayBreakout','S7_RDZ_Momentum',
                         'S8_BullishOutsideDay','S10_RSNewHighs','S12_MomentumAccel'];
    const LIVE_TO_TRADELAB = {
      // Map live strategy ids → tradelab strategy names. Tweak as registrations grow.
      'S2_PocketPivot':'s2_pocket_pivot',
      'S4_InsideDayBreakout':'s4_inside_day_breakout',
      'S7_RDZ_Momentum':'s7_rdz_momentum',
      'S8_BullishOutsideDay':'s8_bullish_outside_day',
      'S10_RSNewHighs':'s10_rs_new_highs',
      'S12_MomentumAccel':'s12_momentum_acceleration',
    };

    let researchState = {
      filters: { strategy:'', verdict:'', since:'30' },
      limit: 50,
      offset: 0,
      total: 0,
      loaded: false,
      robustnessInFlight: false,
    };

    async function fetchJSON(path, opts={}) {
      const r = await fetch(path, opts);
      const body = await r.json().catch(()=>({error:'invalid JSON response',data:null}));
      return body;
    }

    async function researchLoadAll() {
      await Promise.all([
        researchLoadFreshness(),
        researchLoadStrategies(),
        researchLoadLiveCards(),
        researchLoadPipeline(),
      ]);
      researchState.loaded = true;
    }

    async function researchLoadFreshness() {
      const body = await fetchJSON('/tradelab/data-freshness');
      const banner = document.getElementById('researchFreshnessBanner');
      const text = document.getElementById('researchFreshnessText');
      banner.classList.remove('fresh','aging','stale');
      if (body.error || !body.data) {
        text.textContent = 'Data freshness unavailable — Research offline';
        return;
      }
      const d = body.data;
      banner.classList.add(d.status || 'unknown');
      const age = d.oldest_age_hours;
      const label = age == null ? 'no cache'
                   : age < 1 ? `${Math.round(age*60)}m`
                   : `${age.toFixed(1)}h`;
      text.textContent = `Data cache: ${label} old · ${d.symbol_count} symbols`;
    }

    async function researchLoadStrategies() {
      const body = await fetchJSON('/tradelab/strategies');
      const sel = document.getElementById('researchFilterStrategy');
      sel.innerHTML = '<option value="">All strategies</option>';
      (body.data?.strategies || []).forEach(name => {
        const opt = document.createElement('option');
        opt.value = name; opt.textContent = name;
        sel.appendChild(opt);
      });
    }

    async function researchLoadLiveCards() {
      const container = document.getElementById('researchLiveCards');
      container.innerHTML = '';
      for (const liveId of LIVE_STRATS) {
        const tradelabName = LIVE_TO_TRADELAB[liveId];
        const body = await fetchJSON(`/tradelab/runs?strategy=${encodeURIComponent(tradelabName)}&limit=3`);
        const runs = body.data?.runs || [];
        container.appendChild(renderLiveCard(liveId, tradelabName, runs));
      }
    }

    function renderLiveCard(liveId, tradelabName, runs) {
      const card = document.createElement('div');
      card.className = 'research-card';
      if (!runs.length) {
        card.innerHTML = `<div class="research-card-header"><div class="research-card-name">${liveId}</div><span class="verdict-pill verdict-inconclusive">No runs</span></div>
          <div class="research-card-stats"><div class="research-card-stat"><div class="research-card-stat-label">map</div><div class="research-card-stat-value" style="font-size:11px">${tradelabName}</div></div></div>`;
        return card;
      }
      const latest = runs[0];
      const verdict = (latest.verdict || 'INCONCLUSIVE').toLowerCase();
      card.classList.add(`verdict-${verdict}`);
      const prior = runs[1]?.verdict;
      const rank = v => v==='ROBUST'?3 : v==='MARGINAL'?2 : v==='FRAGILE'?1 : 0;
      if (prior && rank(latest.verdict) < rank(prior)) card.classList.add('degraded');

      // Fetch metrics for the latest run (synchronous awaited call would be nicer —
      // kick off and let the row fill in after)
      fetchJSON(`/tradelab/runs/${latest.run_id}/metrics`).then(mBody => {
        const m = mBody.data || {};
        const statsEl = card.querySelector('.research-card-stats');
        if (statsEl) statsEl.innerHTML = statsRowHTML(m, latest.dsr_probability);
      });

      const trendLetters = runs.slice(0, 3).reverse().map(r => (r.verdict || '?')[0]).join(' → ');
      card.innerHTML = `
        <div class="research-card-header">
          <div class="research-card-name">${liveId}</div>
          <span class="verdict-pill verdict-${verdict}">${latest.verdict || 'INCONCLUSIVE'}</span>
        </div>
        <div class="research-card-stats"><div class="research-card-stat-label">Loading metrics...</div></div>
        <div class="research-card-trend">Trend: ${trendLetters}</div>
        ${card.classList.contains('degraded') ? '<div style="color:var(--amber);font-size:12px;margin:4px 0">⚠ degraded since last run</div>' : ''}
        <div class="research-card-actions">
          <button class="btn" onclick="openResearchModal('${latest.run_id}','dashboard','${tradelabName}','${latest.verdict}','${latest.timestamp_utc}')">Dashboard</button>
          <button class="btn" onclick="openResearchModal('${latest.run_id}','quantstats','${tradelabName}','${latest.verdict}','${latest.timestamp_utc}')">QS</button>
        </div>`;
      return card;
    }

    function statsRowHTML(m, dsr) {
      const pf = m.profit_factor != null ? m.profit_factor.toFixed(2) : '—';
      const wr = m.win_rate != null ? m.win_rate.toFixed(0)+'%' : '—';
      const dd = m.max_drawdown_pct != null ? m.max_drawdown_pct.toFixed(1)+'%' : '—';
      const dsrStr = dsr != null ? dsr.toFixed(2) : '—';
      return `
        <div class="research-card-stat"><div class="research-card-stat-label">PF</div><div class="research-card-stat-value">${pf}</div></div>
        <div class="research-card-stat"><div class="research-card-stat-label">WR</div><div class="research-card-stat-value">${wr}</div></div>
        <div class="research-card-stat"><div class="research-card-stat-label">DD</div><div class="research-card-stat-value">${dd}</div></div>
        <div class="research-card-stat"><div class="research-card-stat-label">DSR</div><div class="research-card-stat-value">${dsrStr}</div></div>`;
    }

    async function researchLoadPipeline() {
      const q = new URLSearchParams();
      if (researchState.filters.strategy) q.set('strategy', researchState.filters.strategy);
      if (researchState.filters.verdict) q.set('verdict', researchState.filters.verdict);
      if (researchState.filters.since) {
        const d = new Date(); d.setDate(d.getDate() - parseInt(researchState.filters.since));
        q.set('since', d.toISOString());
      }
      q.set('limit', researchState.limit);
      q.set('offset', researchState.offset);
      const body = await fetchJSON(`/tradelab/runs?${q.toString()}`);
      const runs = body.data?.runs || [];
      researchState.total = body.data?.total || 0;
      renderPipelineRows(runs, researchState.offset === 0);
      updatePaginationUI();
    }

    function renderPipelineRows(runs, replace) {
      const tbody = document.getElementById('researchPipelineBody');
      if (replace) tbody.innerHTML = '';
      if (!runs.length && replace) {
        tbody.innerHTML = '<tr><td colspan="8" class="research-skeleton-row">No runs match these filters.</td></tr>';
        return;
      }
      for (const r of runs) {
        const tr = document.createElement('tr');
        const verdict = (r.verdict || 'INCONCLUSIVE').toLowerCase();
        const date = r.timestamp_utc ? r.timestamp_utc.slice(0,10) : '—';
        tr.innerHTML = `
          <td>${r.strategy_name}</td>
          <td><span class="verdict-pill verdict-${verdict}">${r.verdict || '—'}</span></td>
          <td class="run-pf">…</td>
          <td class="run-wr">…</td>
          <td class="run-dd">…</td>
          <td class="run-trd">…</td>
          <td>${r.dsr_probability != null ? r.dsr_probability.toFixed(2) : '—'}</td>
          <td>${date}</td>`;
        tr.style.cursor = 'pointer';
        tr.onclick = () => openResearchModal(r.run_id, 'dashboard', r.strategy_name, r.verdict, r.timestamp_utc);
        tbody.appendChild(tr);
        // Lazy-fetch metrics per row
        fetchJSON(`/tradelab/runs/${r.run_id}/metrics`).then(mb => {
          const m = mb.data || {};
          tr.querySelector('.run-pf').textContent = m.profit_factor != null ? m.profit_factor.toFixed(2) : '—';
          tr.querySelector('.run-wr').textContent = m.win_rate != null ? m.win_rate.toFixed(0)+'%' : '—';
          tr.querySelector('.run-dd').textContent = m.max_drawdown_pct != null ? m.max_drawdown_pct.toFixed(1)+'%' : '—';
          tr.querySelector('.run-trd').textContent = m.total_trades != null ? m.total_trades : '—';
        });
      }
    }

    function updatePaginationUI() {
      const shown = Math.min(researchState.offset + researchState.limit, researchState.total);
      document.getElementById('researchPipelineCount').textContent =
        ` Showing 1–${shown} of ${researchState.total}`;
      const moreBtn = document.getElementById('researchLoadMoreBtn');
      moreBtn.style.display = shown < researchState.total ? 'inline-block' : 'none';
    }

    // Wiring
    document.addEventListener('DOMContentLoaded', () => {
      const f = (id, event, h) => {
        const el = document.getElementById(id);
        if (el) el.addEventListener(event, h);
      };
      f('researchFilterStrategy', 'change', e => { researchState.filters.strategy = e.target.value; researchState.offset = 0; researchLoadPipeline(); });
      f('researchFilterVerdict',  'change', e => { researchState.filters.verdict  = e.target.value; researchState.offset = 0; researchLoadPipeline(); });
      f('researchFilterSince',    'change', e => { researchState.filters.since    = e.target.value; researchState.offset = 0; researchLoadPipeline(); });
      f('researchFilterClear', 'click', () => {
        researchState.filters = { strategy:'', verdict:'', since:'30' };
        document.getElementById('researchFilterStrategy').value = '';
        document.getElementById('researchFilterVerdict').value = '';
        document.getElementById('researchFilterSince').value = '30';
        researchState.offset = 0;
        researchLoadPipeline();
      });
      f('researchLoadMoreBtn', 'click', () => {
        researchState.offset += researchState.limit;
        researchLoadPipeline();
      });
      f('researchRefreshDataBtn', 'click', async () => {
        const btn = document.getElementById('researchRefreshDataBtn');
        btn.disabled = true;
        btn.textContent = '↻ Refreshing...';
        const body = await fetchJSON('/tradelab/refresh-data', {
          method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'
        });
        btn.disabled = false;
        btn.textContent = '↻ Refresh Data';
        if (body.error) alert('Refresh failed: ' + body.error);
        await researchLoadFreshness();
      });
      f('researchNewStrategyBtn', 'click', () => {
        document.getElementById('researchNewStrategyModal').classList.add('show');
      });
      // Hook tab switch so Research lazy-loads only on first reveal
      const origTab = document.querySelector('.tab[data-tab="research"]');
      if (origTab) origTab.addEventListener('click', () => {
        if (!researchState.loaded) researchLoadAll();
      });
    });
```

- [ ] **Step 2: Smoke test — freshness + pipeline render**

Restart the server. Open http://localhost:8877, click Research.

Expected in DevTools Network tab: `/tradelab/data-freshness`, `/tradelab/strategies`, 6× `/tradelab/runs?strategy=...`, and `/tradelab/runs?limit=50&offset=0` fire. Banner populates. Live cards show verdicts (or "No runs" placeholders). Table rows appear.

- [ ] **Step 3: Record change**

```bash
echo "2026-04-22 — command_center.html: added Research tab JS module (freshness, live cards, pipeline table, filters, pagination)" >> "C:/TradingScripts/CHANGELOG-research-tab.txt"
```

---

## Task 11: Modal — Dashboard + QuantStats iframe tabs

**Files:**
- Modify: `C:\TradingScripts\command_center.html` (add JS inside the Research script block)

- [ ] **Step 1: Add the modal JS**

At the end of the Research script block (just before the tab-switch hook at the bottom), insert:

```javascript
    // ═══ Research modal ═════════════════════════════════════════════

    let modalState = { runId:null, strategy:null, verdict:null, tab:'dashboard' };

    window.openResearchModal = async function(runId, tab, strategy, verdict, timestampUtc) {
      modalState = { runId, strategy, verdict: verdict || 'INCONCLUSIVE', tab };
      const modal = document.getElementById('researchModal');
      const title = document.getElementById('researchModalTitle');
      title.innerHTML = `${strategy} · <span class="verdict-pill verdict-${(verdict||'').toLowerCase()}">${verdict||'?'}</span> · ${(timestampUtc||'').slice(0,10)}`;
      modal.classList.add('show');
      document.body.style.overflow = 'hidden';
      location.hash = `run=${runId}&view=${tab}`;

      // Enable/hide What-If tab based on ranges availability
      const whatifTab = document.querySelector('.research-modal-tabs .tab[data-modal-tab="whatif"]');
      whatifTab.style.display = 'none';
      const ranges = await fetchJSON(`/tradelab/ranges/${encodeURIComponent(strategy)}`);
      if (ranges.data && ranges.data.ranges) {
        whatifTab.style.display = '';
      }

      selectModalTab(tab);
    };

    function selectModalTab(tabName) {
      modalState.tab = tabName;
      document.querySelectorAll('.research-modal-tabs .tab').forEach(el =>
        el.classList.toggle('active', el.dataset.modalTab === tabName));
      const iframe = document.getElementById('researchModalIframe');
      const whatif = document.getElementById('researchModalWhatif');
      iframe.style.display = 'none';
      whatif.style.display = 'none';
      if (tabName === 'dashboard' || tabName === 'quantstats') {
        const file = tabName === 'dashboard' ? 'dashboard.html' : 'quantstats_tearsheet.html';
        iframe.src = `/tradelab/reports/${folderForRun(modalState.runId)}/${file}`;
        iframe.style.display = 'block';
      } else if (tabName === 'whatif') {
        whatif.style.display = 'block';
        renderWhatifPanel(modalState.strategy);
      }
      if (location.hash.startsWith('#run=')) {
        location.hash = `run=${modalState.runId}&view=${tabName}`;
      }
    }

    // run_id → folder lookup (cached on first call per modal session)
    let _runFolderCache = {};
    async function folderForRun(runId) {
      if (_runFolderCache[runId]) return _runFolderCache[runId];
      // Extract run folder from `report_card_html_path` via audit row lookup.
      // Simpler: the dashboard iframe src can use the run_id path if we add a redirect route.
      // For v1, reuse /tradelab/runs?limit=200 already cached; fall back to strategy-based guess if not found.
      return runId; // placeholder; see Task 11 Step 2 for the server-side redirect route
    }

    function closeResearchModal() {
      document.getElementById('researchModal').classList.remove('show');
      document.body.style.overflow = '';
      if (location.hash.startsWith('#run=')) location.hash = '';
    }

    document.addEventListener('DOMContentLoaded', () => {
      document.getElementById('researchModalClose').addEventListener('click', closeResearchModal);
      document.getElementById('researchModal').addEventListener('click', e => {
        if (e.target.id === 'researchModal') closeResearchModal();
      });
      document.querySelectorAll('.research-modal-tabs .tab').forEach(el => {
        el.addEventListener('click', () => selectModalTab(el.dataset.modalTab));
      });
      document.addEventListener('keydown', e => {
        if (e.key === 'Escape') {
          if (document.getElementById('researchNewStrategyModal').classList.contains('show')) {
            document.getElementById('researchNewStrategyModal').classList.remove('show');
          } else if (document.getElementById('researchModal').classList.contains('show')) {
            closeResearchModal();
          }
        }
      });
    });
```

- [ ] **Step 2: Add server-side redirect route for run_id → folder**

In `C:\TradingScripts\tradelab\src\tradelab\web\handlers.py`, add a new GET handler case inside `handle_get_with_status`. Find the `if path == "/tradelab/data-freshness":` block and add before it:

```python
    m = re.match(r"^/tradelab/runs/([^/]+)/folder$", path)
    if m:
        folder = audit_reader.get_run_folder(m.group(1), db_path=_db_path())
        if folder is None:
            return _err("run not found"), 404
        # Return path relative to tradelab root (used as iframe prefix)
        return _ok({"folder": str(folder).replace("\\", "/")}), 200
```

- [ ] **Step 3: Update the JS folderForRun helper to call the new route**

Replace the placeholder `folderForRun` with:

```javascript
    async function folderForRun(runId) {
      if (_runFolderCache[runId]) return _runFolderCache[runId];
      const body = await fetchJSON(`/tradelab/runs/${encodeURIComponent(runId)}/folder`);
      const folder = body.data?.folder || runId;
      // Strip tradelab-root prefix; we want just "reports/<run_folder>"
      const idx = folder.indexOf('reports/');
      const relative = idx >= 0 ? folder.substring(idx) : folder;
      _runFolderCache[runId] = relative;
      return relative;
    }
```

Update the `selectModalTab` iframe src to await the async folder:

```javascript
      if (tabName === 'dashboard' || tabName === 'quantstats') {
        const file = tabName === 'dashboard' ? 'dashboard.html' : 'quantstats_tearsheet.html';
        const folder = await folderForRun(modalState.runId);
        iframe.src = `/tradelab/${folder}/${file}`;
        iframe.style.display = 'block';
      }
```

Mark `selectModalTab` as `async function` since it now awaits.

- [ ] **Step 4: Add a test for the new folder endpoint**

In `tests/web/test_handlers.py`, append:

```python
def test_handle_runs_folder_lookup(fake_audit_db, fake_run_folder, monkeypatch):
    import sqlite3
    conn = sqlite3.connect(str(fake_audit_db))
    conn.execute(
        "UPDATE runs SET report_card_html_path = ? WHERE run_id = 'run-003'",
        (str(fake_run_folder),),
    )
    conn.commit(); conn.close()

    monkeypatch.setattr(handlers, "_db_path", lambda: fake_audit_db)
    monkeypatch.setattr(handlers, "_cache_root", lambda: Path("."))
    monkeypatch.setattr(handlers, "_src_root", lambda: Path("src"))

    body, status = handlers.handle_get_with_status("/tradelab/runs/run-003/folder")
    assert status == 200
    assert json.loads(body)["data"]["folder"].endswith("s4_inside_day_breakout_2026-04-20_120000")
```

- [ ] **Step 5: Run tests**

```bash
cd C:/TradingScripts/tradelab
pytest tests/web -v 2>&1 | tail -10
```

Expected: all passing.

- [ ] **Step 6: Manual smoke**

Restart server, open Research, click a Pipeline row. Modal opens. Dashboard iframe loads the existing per-run HTML. Switch tabs — QuantStats loads. ESC closes. Refresh browser with hash `#run=<id>&view=quantstats` and confirm it re-opens the modal to the QS tab.

- [ ] **Step 7: Commit backend + record HTML change**

```bash
cd C:/TradingScripts/tradelab
git add src/tradelab/web/handlers.py tests/web/test_handlers.py
git commit -m "feat(web): /tradelab/runs/<id>/folder route for modal iframe src resolution"

echo "2026-04-22 — command_center.html: added Research modal (Dashboard+QS iframe tabs, ESC close, hash deep-link)" >> "C:/TradingScripts/CHANGELOG-research-tab.txt"
```

---

## Task 12: Modal — What-If tab

**Files:**
- Modify: `C:\TradingScripts\command_center.html` (add JS)

- [ ] **Step 1: Add the What-If panel JS**

In the Research script block, after `selectModalTab`, add:

```javascript
    let whatifState = { strategy:null, ranges:null, symbol:'AAPL', params:{}, debounceTimer:null };

    async function renderWhatifPanel(strategyName) {
      const el = document.getElementById('researchModalWhatif');
      el.innerHTML = '<div class="whatif-panel">Loading ranges...</div>';
      const body = await fetchJSON(`/tradelab/ranges/${encodeURIComponent(strategyName)}`);
      const ranges = body.data?.ranges;
      if (!ranges) {
        el.innerHTML = '<div class="whatif-panel">No Claude-recommended ranges for this strategy yet.</div>';
        return;
      }
      whatifState = { strategy: strategyName, ranges, symbol:'AAPL', params: {}, debounceTimer:null };
      Object.entries(ranges).forEach(([k,v]) => whatifState.params[k] = v.default);

      el.innerHTML = `
        <div class="whatif-panel">
          <div class="whatif-controls">
            <label>Symbol: <input id="whatifSymbol" value="AAPL" class="settings-input" style="width:120px"></label>
          </div>
          <div class="whatif-sliders">
            ${Object.entries(ranges).map(([k,v]) => `
              <div class="whatif-slider-row" data-param="${k}">
                <div><strong>${k}</strong><div class="claude-note">${v.claude_note||''}</div></div>
                <input type="range" min="${v.min}" max="${v.max}" step="${v.step||1}" value="${v.default}">
                <div class="whatif-value">${v.default}</div>
                <div class="claude-note">(Claude: ${v.min}–${v.max})</div>
              </div>`).join('')}
          </div>
          <div class="whatif-result">
            <div class="whatif-metrics" id="whatifMetrics">Run a slider change to compute...</div>
            <div class="whatif-chart"><canvas id="whatifChart"></canvas></div>
          </div>
          <div style="margin-top:16px;display:flex;gap:10px">
            <button class="btn primary" id="whatifSave">Save as variant</button>
            <button class="btn" id="whatifReset">Reset to defaults</button>
          </div>
        </div>`;

      // Wire sliders
      el.querySelectorAll('.whatif-slider-row input[type=range]').forEach(input => {
        const row = input.closest('.whatif-slider-row');
        const valEl = row.querySelector('.whatif-value');
        input.addEventListener('input', () => {
          valEl.textContent = input.value;
          whatifState.params[row.dataset.param] = Number(input.value);
          scheduleWhatifCompute();
        });
      });
      document.getElementById('whatifSymbol').addEventListener('change', e => {
        whatifState.symbol = e.target.value.trim().toUpperCase();
        scheduleWhatifCompute();
      });
      document.getElementById('whatifSave').addEventListener('click', onWhatifSaveVariant);
      document.getElementById('whatifReset').addEventListener('click', onWhatifReset);

      // Initial compute
      runWhatifCompute();
    }

    function scheduleWhatifCompute() {
      if (whatifState.debounceTimer) clearTimeout(whatifState.debounceTimer);
      whatifState.debounceTimer = setTimeout(runWhatifCompute, 300);
    }

    async function runWhatifCompute() {
      const metricsEl = document.getElementById('whatifMetrics');
      metricsEl.classList.add('whatif-loading');
      metricsEl.textContent = 'Computing...';
      const body = await fetchJSON('/tradelab/whatif', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({
          strategy: whatifState.strategy,
          symbol: whatifState.symbol,
          params: whatifState.params,
        }),
      });
      metricsEl.classList.remove('whatif-loading');
      if (body.error) {
        metricsEl.innerHTML = `<div style="color:var(--red)">Error: ${body.error}</div>`;
        return;
      }
      const m = body.data.metrics || {};
      metricsEl.innerHTML = `
        <div class="whatif-metric-row"><span>PF</span><strong>${m.profit_factor?.toFixed(2) ?? '—'}</strong></div>
        <div class="whatif-metric-row"><span>WR</span><strong>${m.win_rate?.toFixed(1) ?? '—'}%</strong></div>
        <div class="whatif-metric-row"><span>DD</span><strong>${m.max_drawdown_pct?.toFixed(1) ?? '—'}%</strong></div>
        <div class="whatif-metric-row"><span>Trades</span><strong>${m.total_trades ?? '—'}</strong></div>
        <div class="whatif-metric-row"><span>Sharpe</span><strong>${m.sharpe_ratio?.toFixed(2) ?? '—'}</strong></div>`;
      renderWhatifChart(body.data.equity_curve || []);
    }

    let whatifChart = null;
    function renderWhatifChart(curve) {
      const canvas = document.getElementById('whatifChart');
      if (!canvas) return;
      const data = {
        labels: curve.map(p => p.date),
        datasets: [{ label:'Equity', data: curve.map(p => p.equity), borderColor:'#22c55e', borderWidth:2, fill:false, tension:0.1 }]
      };
      if (whatifChart) whatifChart.destroy();
      whatifChart = new Chart(canvas, {
        type:'line', data,
        options: { scales:{x:{display:false}, y:{ticks:{color:'#a0a4b0'}}}, plugins:{legend:{display:false}} }
      });
    }

    async function onWhatifReset() {
      Object.entries(whatifState.ranges).forEach(([k,v]) => whatifState.params[k] = v.default);
      document.querySelectorAll('#researchModalWhatif .whatif-slider-row').forEach(row => {
        const k = row.dataset.param;
        row.querySelector('input[type=range]').value = whatifState.ranges[k].default;
        row.querySelector('.whatif-value').textContent = whatifState.ranges[k].default;
      });
      runWhatifCompute();
    }

    async function onWhatifSaveVariant() {
      const suggested = `${whatifState.strategy}_v2`;
      const name = prompt('Save as variant — new strategy name:', suggested);
      if (!name) return;
      // Server reads original file, rewrites default params, and registers.
      // For v1 we POST a direct new-strategy call with the regenerated source.
      // The server Save route is Task 13.
      const body = await fetchJSON('/tradelab/save-variant', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({
          base_strategy: whatifState.strategy,
          new_name: name,
          params: whatifState.params,
        }),
      });
      if (body.error) { alert('Save failed: ' + body.error); return; }
      alert(`Saved as ${name}. Running full robustness in background.`);
    }
```

- [ ] **Step 2: Add Save-as-variant backend route**

In `C:\TradingScripts\tradelab\src\tradelab\web\handlers.py`, add inside `handle_post` above `if path == "/tradelab/refresh-data":`:

```python
    if path == "/tradelab/save-variant":
        try:
            base = payload["base_strategy"]
            new_name = payload["new_name"]
            new_params = payload.get("params") or {}
        except KeyError as e:
            return _err(f"missing field: {e}")
        from tradelab.registry import get_strategy_entry, list_registered_strategies
        if new_name in list_registered_strategies():
            return _err(f"name '{new_name}' already registered")
        try:
            entry = get_strategy_entry(base)
        except Exception as e:
            return _err(f"base strategy not registered: {e}")
        module_path = entry.module.replace("tradelab.strategies.", "")
        src_file = _src_root() / "tradelab" / "strategies" / f"{module_path}.py"
        if not src_file.exists():
            return _err(f"base strategy file missing: {src_file}")
        # Read the original source, then write it with the new default params injected
        code = src_file.read_text()
        code = _inject_default_params(code, new_params)
        result = new_strategy.validate_and_stage(
            name=new_name,
            code=code,
            staging_root=_staging_root(),
            src_root=_src_root(),
        )
        if result["error"]:
            return _err(result["error"], data={"stage": result.get("stage")})
        reg = new_strategy.register_strategy(
            name=new_name,
            class_name=result["class_name"],
            staging_root=_staging_root(),
            src_root=_src_root(),
            yaml_path=_yaml_path(),
        )
        if reg["error"]:
            return _err(reg["error"])
        subprocess.Popen(
            [sys.executable, "-m", "tradelab.cli", "run", new_name, "--robustness"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return _ok({"final_path": reg["final_path"]})
```

And add this helper at module level (top of `handlers.py` near the other helpers):

```python
def _inject_default_params(code: str, new_defaults: dict) -> str:
    """Rewrite the `default_params = {...}` class attribute with new_defaults.

    Naive replacement — expects a single `default_params = {` line in the file.
    Falls back to inserting a new class-level assignment after the class
    declaration if not found.
    """
    import re as _re
    if not new_defaults:
        return code
    literal = repr(new_defaults)
    pattern = _re.compile(r"default_params\s*=\s*\{[^}]*\}", _re.MULTILINE | _re.DOTALL)
    if pattern.search(code):
        return pattern.sub(f"default_params = {literal}", code, count=1)
    # fallback: insert after first class definition line
    cls = _re.compile(r"(class \w+\([^)]*Strategy[^)]*\):\s*\n)")
    m = cls.search(code)
    if m:
        insertion = m.group(0) + f"    default_params = {literal}\n"
        return cls.sub(insertion, code, count=1)
    return code
```

- [ ] **Step 3: Add test for save-variant endpoint**

Append to `tests/web/test_handlers.py`:

```python
def test_handle_save_variant_happy_path(fake_tradelab_root, monkeypatch):
    # Prepare a base strategy file
    strategies_dir = fake_tradelab_root / "src" / "tradelab" / "strategies"
    strategies_dir.mkdir(parents=True, exist_ok=True)
    (strategies_dir / "base_strat.py").write_text('''
from tradelab.strategies.base import Strategy
class BaseStrat(Strategy):
    default_params = {"x": 1}
    def generate_signals(self, data, spy_close=None):
        return {k: v.copy() for k,v in data.items()}
''')
    # Fake yaml
    yaml_path = fake_tradelab_root / "tradelab.yaml"
    yaml_path.write_text("strategies:\n  base_strat:\n    module: tradelab.strategies.base_strat\n    class_name: BaseStrat\n    params: {}\n")

    monkeypatch.setattr(handlers, "_db_path", lambda: Path("nope.db"))
    monkeypatch.setattr(handlers, "_cache_root", lambda: Path("."))
    monkeypatch.setattr(handlers, "_src_root", lambda: fake_tradelab_root / "src")
    monkeypatch.setattr(handlers, "_staging_root", lambda: fake_tradelab_root / ".cache" / "new_strategy_staging")
    monkeypatch.setattr(handlers, "_yaml_path", lambda: yaml_path)

    # Stub subprocess.Popen — no CLI run during test
    monkeypatch.setattr(handlers.subprocess, "Popen", lambda *a, **kw: None)

    # Skip the smoke_5 backtest by mocking validate_and_stage to succeed instantly
    def fake_validate(name, code, staging_root, src_root):
        (Path(staging_root) / f"{name}.py").write_text(code)
        return {"error": None, "stage":"complete", "metrics":{}, "equity_curves_by_symbol":{}, "class_name":"BaseStrat"}
    monkeypatch.setattr(handlers.new_strategy, "validate_and_stage", fake_validate)

    # And stub _is_registered so register doesn't think name is taken
    monkeypatch.setattr(handlers.new_strategy, "_is_registered", lambda n: False)

    payload = {"base_strategy":"base_strat","new_name":"base_strat_v2","params":{"x":5}}
    body = handlers.handle_post("/tradelab/save-variant", json.dumps(payload).encode())
    data = json.loads(body)
    assert data["error"] is None
    # Confirm the variant file was written with new defaults
    variant = fake_tradelab_root / "src" / "tradelab" / "strategies" / "base_strat_v2.py"
    assert variant.exists()
    assert "'x': 5" in variant.read_text() or '"x": 5' in variant.read_text()
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/web -v 2>&1 | tail -15
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/tradelab/web/handlers.py tests/web/test_handlers.py
git commit -m "feat(web): What-If save-as-variant route with default-params injection"

echo "2026-04-22 — command_center.html: added What-If modal tab (sliders, debounced compute, equity chart, save variant)" >> "C:/TradingScripts/CHANGELOG-research-tab.txt"
```

---

## Task 13: New Strategy modal — front-end wiring

**Files:**
- Modify: `C:\TradingScripts\command_center.html` (add JS)

- [ ] **Step 1: Add the New Strategy modal JS**

Append to the Research script block:

```javascript
    // ═══ New Strategy modal ═════════════════════════════════════════

    document.addEventListener('DOMContentLoaded', () => {
      const modal = document.getElementById('researchNewStrategyModal');
      const closeBtn = document.getElementById('researchNewStrategyClose');
      closeBtn.addEventListener('click', () => modal.classList.remove('show'));
      modal.addEventListener('click', e => { if (e.target === modal) modal.classList.remove('show'); });

      document.getElementById('nsCancel').addEventListener('click', () => modal.classList.remove('show'));
      document.getElementById('nsTest').addEventListener('click', onNsTest);
    });

    async function onNsTest() {
      const name = document.getElementById('nsName').value.trim();
      const code = document.getElementById('nsCode').value;
      const resultsEl = document.getElementById('nsResults');
      if (!name || !code) { resultsEl.innerHTML = '<div style="color:var(--amber)">Name and code required.</div>'; return; }
      resultsEl.innerHTML = '<div style="color:var(--text2)">Running smoke_5 backtest (~15s)...</div>';
      const body = await fetchJSON('/tradelab/new-strategy', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ action:'test', name, code }),
      });
      if (body.error) {
        resultsEl.innerHTML = `
          <div style="background:var(--red-bg);border:1px solid var(--red-border);color:var(--red);padding:12px;border-radius:4px;margin-bottom:12px">
            <strong>Stage ${body.data?.stage || '?'} failed:</strong> ${body.error}
          </div>
          ${body.data?.traceback ? `<details><summary>Traceback</summary><pre style="font-size:11px;background:var(--surface);padding:10px;border-radius:4px;overflow:auto">${escapeHtml(body.data.traceback)}</pre></details>` : ''}`;
        return;
      }
      const m = body.data.metrics || {};
      resultsEl.innerHTML = `
        <div style="color:var(--green);margin-bottom:10px">✓ Import, discover, and smoke_5 backtest passed</div>
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:14px">
          <div class="kpi"><div class="kpi-label">PF</div><div class="kpi-value">${m.profit_factor?.toFixed(2) ?? '—'}</div></div>
          <div class="kpi"><div class="kpi-label">WR</div><div class="kpi-value">${m.win_rate?.toFixed(0) ?? '—'}%</div></div>
          <div class="kpi"><div class="kpi-label">DD</div><div class="kpi-value">${m.max_drawdown_pct?.toFixed(1) ?? '—'}%</div></div>
          <div class="kpi"><div class="kpi-label">Trades</div><div class="kpi-value">${m.total_trades ?? '—'}</div></div>
        </div>
        <div style="display:flex;gap:10px;justify-content:flex-end">
          <button class="btn danger" onclick="onNsDiscard('${name}')">Discard</button>
          <button class="btn primary" onclick="onNsRegister('${name}','${body.data.class_name}')">Register + run full robustness</button>
        </div>`;
    }

    window.onNsDiscard = async function(name) {
      await fetchJSON('/tradelab/new-strategy', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ action:'discard', name }),
      });
      document.getElementById('researchNewStrategyModal').classList.remove('show');
      document.getElementById('nsName').value = '';
      document.getElementById('nsCode').value = '';
      document.getElementById('nsResults').innerHTML = '';
    };

    window.onNsRegister = async function(name, className) {
      const body = await fetchJSON('/tradelab/new-strategy', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ action:'register', name, class_name: className }),
      });
      if (body.error) { alert('Register failed: ' + body.error); return; }
      alert(`${name} registered. Running full robustness in background — table will update when complete.`);
      document.getElementById('researchNewStrategyModal').classList.remove('show');
      // Refresh pipeline and strategy filter list
      await researchLoadStrategies();
      await researchLoadPipeline();
    };

    function escapeHtml(s) {
      return (s || '').replace(/[&<>"']/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
    }
```

- [ ] **Step 2: Manual smoke**

Restart server. Open Research, click "+ New Strategy". Paste a minimal valid class (use the scaffold from the spec Section 8.9). Click Test. Verify success path renders metrics. Click Discard → modal closes. Reopen, paste again, click Register → strategy appears in Pipeline filter dropdown after a refresh; robustness subprocess logs to the server terminal.

- [ ] **Step 3: Record change**

```bash
echo "2026-04-22 — command_center.html: added New Strategy modal wiring (test / register / discard)" >> "C:/TradingScripts/CHANGELOG-research-tab.txt"
```

---

## Task 14: One-click launcher `.bat`

**Files:**
- Create: `C:\TradingScripts\research_dashboard.bat`

- [ ] **Step 1: Write the .bat**

Create `C:\TradingScripts\research_dashboard.bat`:

```bat
@echo off
title AlgoTrade Command Center + Research
cd /d C:\TradingScripts

:: Check if server already running on 8877
netstat -an | findstr :8877 >nul
if %errorlevel%==0 (
    start "" "http://localhost:8877/#tab=research"
    exit /b 0
)

start "" python launch_dashboard.py
timeout /t 2 /nobreak >nul
start "" "http://localhost:8877/#tab=research"
```

- [ ] **Step 2: Add hash-aware tab switcher to command_center.html JS**

In the Research script block's `DOMContentLoaded` handler, append at the end:

```javascript
      // Honor ?tab= or #tab= on initial page load so the .bat can deep-link
      function honorInitialHash() {
        const hash = location.hash || '';
        const match = hash.match(/tab=(\w+)/);
        if (match && match[1]) {
          const tab = document.querySelector(`.tab[data-tab="${match[1]}"]`);
          if (tab) tab.click();
        }
      }
      honorInitialHash();
```

- [ ] **Step 3: Double-click test**

Double-click `research_dashboard.bat` from File Explorer. Expected: browser opens directly on the Research tab.

- [ ] **Step 4: Record change**

```bash
echo "2026-04-22 — research_dashboard.bat: one-click launcher, opens to Research tab" >> "C:/TradingScripts/CHANGELOG-research-tab.txt"
```

---

## Task 15: Regression smoke + final pytest run

**Files:** none (verification only)

- [ ] **Step 1: Run the full pytest suite (tradelab + web)**

```bash
cd C:/TradingScripts/tradelab
source /c/TradingScripts/.venv-vectorbt/Scripts/activate
pytest tests/ -v 2>&1 | tail -30
```

Expected: all tradelab's existing tests pass AND all new tests in `tests/web/` pass. Any failure → stop, investigate, fix, re-run.

- [ ] **Step 2: Run tradelab doctor**

```bash
tradelab doctor 2>&1 | tail -20
```

Expected: all checks pass (env, config, strategies, canaries).

- [ ] **Step 3: Manual regression smoke**

Start the dashboard (`python launch_dashboard.py`). Click through this checklist:

- [ ] Overview tab: KPIs populate, cards render, flatten modal opens + cancels
- [ ] Calendar P&L tab: grid renders with coloring
- [ ] Strategy Performance tab: selector works, chart updates
- [ ] Settings tab: API keys load, Emergency Flatten dialog opens + cancels
- [ ] 10 safety mechanisms fire (review `Dashboard_Safety_Mechanisms.pdf` checklist)
- [ ] Research tab: freshness banner shows status, 6 Live cards render, Pipeline shows ≥1 row (if audit DB has data)
- [ ] Modal opens from row click; Dashboard, QuantStats tabs both load; What-If tab hidden when no ranges file exists
- [ ] ESC closes modal; backdrop click closes modal; hash persists across refresh
- [ ] Refresh Data button triggers without blocking; freshness banner updates
- [ ] New Strategy modal: rejects bad name, rejects non-strategy code, accepts valid strategy, Discard cleans up, Register queues robustness

Any issue → fix immediately; each fix should get its own small commit in the tradelab repo.

- [ ] **Step 4: Verify devtools console is clean**

With every tab open at least once, check browser DevTools console — should be empty of errors (a 404 for a missing iframe due to sparse audit DB is acceptable if the UI shows its error banner correctly).

- [ ] **Step 5: Record feature complete**

```bash
cd C:/TradingScripts/tradelab
echo "2026-04-22 — Research tab v1 complete (all 15 tasks, regression + pytest + doctor passing)"
echo "Command Center Research tab v1 — feature complete." >> "C:/TradingScripts/CHANGELOG-research-tab.txt"
```

- [ ] **Step 6: Verify the backup files still exist (in case of rollback need)**

```bash
ls -la "C:/TradingScripts/"*.bak-2026-04-22
```

Expected: both backup files still present.

---

## Rollback procedure

If the feature needs to be reverted:

```bash
# Restore the two in-place-edited files
cp "C:/TradingScripts/command_center.html.bak-2026-04-22" "C:/TradingScripts/command_center.html"
cp "C:/TradingScripts/launch_dashboard.py.bak-2026-04-22" "C:/TradingScripts/launch_dashboard.py"

# Delete the new .bat
rm "C:/TradingScripts/research_dashboard.bat"

# Revert the tradelab repo changes (all commits on master since 43c12d5 before the first web commit)
cd C:/TradingScripts/tradelab
git log --oneline | head -20      # find commit BEFORE "scaffold: tradelab.web package"
git reset --hard <commit-sha>
```

Existing Alpaca config, position_map, audit DB, and all tradelab reports are untouched.

---

## Self-review — plan-vs-spec gaps

Done after writing all tasks. Each spec section mapped to tasks:

| Spec section | Implementing task(s) |
|--------------|----------------------|
| §4 Architecture — one process, new routes | 0, 2–7, 8, 15 |
| §5 Data flow — error envelope, no auto-refresh, soft dep | 7, 8 |
| §6 Research tab layout — tab registration, banner, cards, pipeline, filters, pagination | 9, 10 |
| §7 Modal — shell, tabs, gating, deep-link, Dashboard/QS iframes, What-If, keyboard | 11, 12 |
| §8 New Strategy paste flow — validation pipeline, register, discard, staging hygiene, scaffold | 6, 7, 13 |
| §9 One-click launcher | 14 |
| §10 Scope boundary (no optuna, no shadow-trading, no correlation, etc.) | Honored throughout — no task adds these |
| §11 Testing — pytest + manual smoke + definition of done | Test steps within tasks 1–12, final verification in 15 |
| §12 Rollback | Rollback procedure section above |

**No placeholders** (grepped for TBD/TODO/FIXME in the plan).

**Type consistency check:**
- `audit_reader.list_runs(..., verdicts=[...])` — Task 2; called from `handlers.handle_get` Task 7. Matches.
- `new_strategy.validate_and_stage(name, code, staging_root, src_root)` — Task 6; called from `handlers` Task 7. Matches.
- `new_strategy.register_strategy(name, class_name, staging_root, src_root, yaml_path)` — Task 6; called from `handlers` Task 7 with `class_name` from the validate result's `class_name` field. Matches.
- Modal JS `openResearchModal(runId, tab, strategy, verdict, timestampUtc)` — Task 10 (live cards + pipeline rows), Task 11 (modal). Matches.
- `folderForRun` returns a relative `reports/<run_folder>` string; used in Task 11's iframe src. Matches.

**Caveat resolved:** original draft referenced a nonexistent `tradelab.marketdata.load_symbols`. Both `whatif.py` (Task 5) and `new_strategy.py` (Task 6's `_run_smoke_backtest`) have been updated to use the real cache API — `tradelab.marketdata.cache.read(symbol, timeframe)` — and the callers build the `{symbol: df}` dict themselves.

---

**Plan complete and saved to `C:\TradingScripts\tradelab\docs\superpowers\plans\2026-04-22-command-center-research-tab.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints for review

**Which approach?**
