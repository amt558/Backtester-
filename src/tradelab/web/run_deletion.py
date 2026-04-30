"""
Atomic run deletion: DB row + on-disk report folder + JSONL audit log.

Order: lookup -> DB delete -> folder rmtree -> log append. Earlier steps are
committed before later steps run; full rollback would require shadow folders
and is intentionally out of scope for v3. Callers should treat a returned
manifest as the source of truth for what was removed.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class RunNotFound(Exception):
    """run_id is not present in the runs table."""


def _default_db_path() -> Path:
    return Path("data") / "tradelab_history.db"


def _default_log_path() -> Path:
    return Path("data") / "deletions.log"


def _resolve_folder(report_card_html_path: Optional[str]) -> Optional[Path]:
    """Mirror audit_reader.resolve_run_folder logic without the DB round-trip.
    Returns None when the path is NULL or the entry no longer exists on disk."""
    if not report_card_html_path:
        return None
    p = Path(report_card_html_path)
    folder = p if p.is_dir() else p.parent
    return folder if folder.exists() else None


def delete_run_atomic(
    run_id: str,
    db_path: Optional[Path] = None,
    log_path: Optional[Path] = None,
) -> dict:
    """Delete a run end-to-end. Returns a manifest dict.

    Raises RunNotFound if run_id is not in the DB.
    """
    db = Path(db_path) if db_path else _default_db_path()
    log = Path(log_path) if log_path else _default_log_path()

    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT strategy_name, report_card_html_path "
            "FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise RunNotFound(f"run_id {run_id} not in {db}")
        strategy, report_card_html_path = row

        conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
        conn.commit()
    finally:
        conn.close()

    paths_removed: list[str] = []
    folder = _resolve_folder(report_card_html_path)
    if folder is not None:
        paths_removed = [str(p) for p in folder.rglob("*") if p.is_file()]
        shutil.rmtree(folder)

    log.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "run_id": run_id,
        "strategy": strategy,
        "deleted_by": "ui",
        "paths_removed": paths_removed,
    }
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    return entry
