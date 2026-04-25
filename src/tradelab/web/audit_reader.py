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
        try:
            archived_ids = list_archived_run_ids(db_path=db)
        except sqlite3.OperationalError:
            # archived_runs sidecar table may not exist yet (no run has been
            # archived). Treat as no archived runs.
            archived_ids = set()

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
