"""
Audit trail — append-only SQLite record of every tradelab evaluation run.

Why append-only: when a live strategy degrades in 2027, Amit needs to be able
to answer "what did tradelab say on approval day?" with full precision. That
requires the history to be immutable. There is no `delete` or `mark_invalid`
path; filter at query time if needed.

Schema (table `runs`):
  run_id               TEXT   UUID primary key
  timestamp_utc        TEXT   ISO 8601 UTC
  strategy_name        TEXT
  strategy_version     TEXT   optional (git commit of strategy file or tag)
  tradelab_version     TEXT
  tradelab_git_commit  TEXT
  input_data_hash      TEXT   SHA-256 of OHLCV inputs (via hash_universe)
  config_hash          TEXT   SHA-256 of active config
  verdict              TEXT   ROBUST / INCONCLUSIVE / FRAGILE / undefined
  dsr_probability      REAL   [0,1]
  report_card_markdown TEXT   full report text
  report_card_html_path TEXT  filesystem reference (may be relative)
  signal_values_json   TEXT   full signal vector at evaluation time (Slice 0)
  thresholds_json      TEXT   active thresholds at evaluation time (Slice 0)
  accepted_bool        INTEGER TRUE/FALSE/NULL for live approval decision (Slice 0)
  reject_reason        TEXT   free text from Reject modal or override reason (Slice 0)
"""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


_NEW_COLUMNS = (
    ("signal_values_json", "TEXT"),
    ("thresholds_json", "TEXT"),
    ("accepted_bool", "INTEGER"),
    ("reject_reason", "TEXT"),
)

DEFAULT_DB_PATH = Path("data") / "tradelab_history.db"


@dataclass
class HistoryRow:
    run_id: str
    timestamp_utc: str
    strategy_name: str
    strategy_version: Optional[str] = None
    tradelab_version: Optional[str] = None
    tradelab_git_commit: Optional[str] = None
    input_data_hash: Optional[str] = None
    config_hash: Optional[str] = None
    verdict: Optional[str] = None
    dsr_probability: Optional[float] = None
    report_card_markdown: Optional[str] = None
    report_card_html_path: Optional[str] = None
    signal_values_json: Optional[str] = None
    thresholds_json: Optional[str] = None
    accepted_bool: Optional[int] = None
    reject_reason: Optional[str] = None


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))

    # First, create the table if it doesn't exist (without indexes on new columns)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS runs (
        run_id               TEXT PRIMARY KEY,
        timestamp_utc        TEXT NOT NULL,
        strategy_name        TEXT NOT NULL,
        strategy_version     TEXT,
        tradelab_version     TEXT,
        tradelab_git_commit  TEXT,
        input_data_hash      TEXT,
        config_hash          TEXT,
        verdict              TEXT,
        dsr_probability      REAL,
        report_card_markdown TEXT,
        report_card_html_path TEXT
    )
    """)

    # Legacy DB migration: add missing columns idempotently
    existing = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
    for col, sqltype in _NEW_COLUMNS:
        if col not in existing:
            conn.execute(f"ALTER TABLE runs ADD COLUMN {col} {sqltype}")

    # Create indexes (idempotent with IF NOT EXISTS)
    conn.executescript("""
    CREATE INDEX IF NOT EXISTS idx_runs_strategy ON runs(strategy_name);
    CREATE INDEX IF NOT EXISTS idx_runs_timestamp ON runs(timestamp_utc);
    CREATE INDEX IF NOT EXISTS idx_runs_accepted ON runs(accepted_bool);
    """)

    conn.commit()
    return conn


def record_run(
    strategy_name: str,
    *,
    verdict: Optional[str] = None,
    dsr_probability: Optional[float] = None,
    input_data_hash: Optional[str] = None,
    config_hash: Optional[str] = None,
    report_card_markdown: Optional[str] = None,
    report_card_html_path: Optional[str] = None,
    strategy_version: Optional[str] = None,
    tradelab_version: Optional[str] = None,
    tradelab_git_commit: Optional[str] = None,
    signal_values: Optional[dict] = None,
    thresholds: Optional[dict] = None,
    accepted: Optional[bool] = None,
    reject_reason: Optional[str] = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> str:
    """
    Insert one row. Returns the new run_id.

    Any field may be None (schema-level NULLs), but at minimum strategy_name
    is required. Other fields are populated from determinism helpers when
    the caller doesn't supply them.

    New optional kwargs (Slice 0):
      signal_values: dict of full signal vector at evaluation time
      thresholds: dict of active thresholds at evaluation time
      accepted: whether user accepted to live (True/False/None=undecided)
      reject_reason: free text from Reject modal (or override reason)
    """
    import json
    from ..determinism import env_fingerprint, git_commit_hash, tradelab_version as _tl_ver

    env = env_fingerprint()
    run_id = str(uuid.uuid4())
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    accepted_bool = None if accepted is None else (1 if accepted else 0)

    conn = _connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO runs (
                run_id, timestamp_utc, strategy_name, strategy_version,
                tradelab_version, tradelab_git_commit,
                input_data_hash, config_hash,
                verdict, dsr_probability,
                report_card_markdown, report_card_html_path,
                signal_values_json, thresholds_json, accepted_bool, reject_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id, ts, strategy_name, strategy_version,
                tradelab_version or _tl_ver(),
                tradelab_git_commit or git_commit_hash(),
                input_data_hash, config_hash,
                verdict, dsr_probability,
                report_card_markdown, str(report_card_html_path) if report_card_html_path else None,
                json.dumps(signal_values) if signal_values is not None else None,
                json.dumps(thresholds) if thresholds is not None else None,
                accepted_bool,
                reject_reason,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return run_id


def _row_to_dataclass(row) -> HistoryRow:
    return HistoryRow(
        run_id=row[0],
        timestamp_utc=row[1],
        strategy_name=row[2],
        strategy_version=row[3],
        tradelab_version=row[4],
        tradelab_git_commit=row[5],
        input_data_hash=row[6],
        config_hash=row[7],
        verdict=row[8],
        dsr_probability=row[9],
        report_card_markdown=row[10],
        report_card_html_path=row[11],
        signal_values_json=row[12],
        thresholds_json=row[13],
        accepted_bool=row[14],
        reject_reason=row[15],
    )


def list_runs(
    strategy: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = 50,
    db_path: Path = DEFAULT_DB_PATH,
) -> list[HistoryRow]:
    """List recent runs, optionally filtered by strategy and/or timestamp."""
    if not db_path.exists():
        return []
    conn = _connect(db_path)
    try:
        sql = "SELECT * FROM runs"
        where = []
        args: list = []
        if strategy:
            where.append("strategy_name = ?")
            args.append(strategy)
        if since:
            where.append("timestamp_utc >= ?")
            args.append(since)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY timestamp_utc DESC LIMIT ?"
        args.append(limit)
        rows = conn.execute(sql, args).fetchall()
    finally:
        conn.close()
    return [_row_to_dataclass(r) for r in rows]


def get_run(run_id: str, db_path: Path = DEFAULT_DB_PATH) -> Optional[HistoryRow]:
    if not db_path.exists():
        return None
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    finally:
        conn.close()
    return _row_to_dataclass(row) if row else None


def diff_runs(
    run_id_a: str, run_id_b: str, db_path: Path = DEFAULT_DB_PATH
) -> str:
    """Return a unified diff between the two runs' report markdown."""
    import difflib

    a = get_run(run_id_a, db_path)
    b = get_run(run_id_b, db_path)
    if a is None:
        return f"run_id {run_id_a!r} not found"
    if b is None:
        return f"run_id {run_id_b!r} not found"
    a_text = (a.report_card_markdown or "").splitlines(keepends=True)
    b_text = (b.report_card_markdown or "").splitlines(keepends=True)
    diff = difflib.unified_diff(
        a_text, b_text,
        fromfile=f"{a.run_id[:8]} ({a.timestamp_utc})",
        tofile=f"{b.run_id[:8]} ({b.timestamp_utc})",
        lineterm="",
    )
    return "\n".join(diff)
