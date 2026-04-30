"""
Verdict history fetch for the Research v3 drift sparkline.

Returns the N most recent verdicts for a strategy, oldest -> newest, lowercase.
Frontend renders these as colored dots in `<div class="drift">`.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional


def _default_db_path() -> Path:
    return Path("data") / "tradelab_history.db"


def get_recent_verdicts(
    strategy_id: str, n: int = 12, db_path: Optional[Path] = None
) -> list[str]:
    """
    Return up to N most recent verdicts for a strategy, oldest -> newest.

    Lowercase strings: "robust" / "marginal" / "fragile" / "inconclusive".
    Empty list if the DB is missing or the strategy has no runs.
    """
    db = Path(db_path) if db_path else _default_db_path()
    if not db.exists():
        return []

    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT verdict FROM runs "
            "WHERE strategy_name = ? "
            "ORDER BY timestamp_utc DESC LIMIT ?",
            (strategy_id, n),
        ).fetchall()
    finally:
        conn.close()

    # Reverse so the result is oldest-first; normalize to lowercase for the FE.
    return [(r[0] or "").lower() for r in reversed(rows)]
