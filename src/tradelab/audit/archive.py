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
    conn = _connect(db)
    try:
        row = conn.execute(
            "SELECT 1 FROM archived_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def unarchive_run(run_id: str, *, db_path: Optional[Path] = None) -> bool:
    """Remove run_id from archived_runs. Idempotent.

    Returns True if a row was removed, False if it wasn't archived to begin
    with. Caller can use the bool to differentiate but the HTTP layer treats
    both as success.
    """
    db = Path(db_path) if db_path else DEFAULT_DB_PATH
    if not db.exists():
        return False
    conn = _connect(db)
    try:
        cur = conn.execute(
            "DELETE FROM archived_runs WHERE run_id = ?", (run_id,)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def list_archived_run_ids(*, db_path: Optional[Path] = None) -> set[str]:
    """Return the set of all archived run_ids. Empty set if DB missing."""
    db = Path(db_path) if db_path else DEFAULT_DB_PATH
    if not db.exists():
        return set()
    conn = _connect(db)
    try:
        rows = conn.execute("SELECT run_id FROM archived_runs").fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()
