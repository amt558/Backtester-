"""Verdict ledger — append-only record of every promote-path decision (WP4).

Slice A is CAPTURE-ONLY: one durable row per *activate-path* accept decision,
written at the accept chokepoint (approve_strategy.accept_scored /
accept_python_run), keyed off the route route_promotion already returned. This
module only WRITES; reading/query/render and accuracy scoring are later slices.

Lives in the same sqlite DB as the audit `runs` table
(data/tradelab_history.db) and manages its own schema with the same idempotent
CREATE/INDEX pattern as audit.history._connect — no migration framework, the
table self-heals on connect.

Append-only by design (decision C): each call inserts a fresh row; there is no
upsert and no delete. Full attempt history is what an accuracy ledger needs.

Fail-OPEN contract (decision 3, deliberately the OPPOSITE of the floor): a
ledger write that throws must NEVER block or reverse a legitimate activation.
This module may raise (sqlite errors, locked DB, ...); the accept chokepoint
wraps log_decision so a failure is logged loudly and the promotion proceeds.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .history import DEFAULT_DB_PATH


def _connect(db_path: Path) -> sqlite3.Connection:
    """Open the audit DB and ensure the verdict_ledger table + indexes exist.

    Mirrors audit.history._connect: idempotent CREATE TABLE IF NOT EXISTS +
    CREATE INDEX IF NOT EXISTS, so first write self-creates the schema and
    repeat connects are no-ops.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
    CREATE TABLE IF NOT EXISTS verdict_ledger (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at      TEXT NOT NULL,
        scoring_run_id  TEXT,
        strategy_name   TEXT NOT NULL,
        path            TEXT NOT NULL,
        verdict         TEXT,
        promotion_route TEXT NOT NULL,
        blockers_json   TEXT NOT NULL DEFAULT '[]',
        override_used   INTEGER NOT NULL DEFAULT 0,
        activated       INTEGER NOT NULL DEFAULT 0
    )
    """)
    # S6: override receipt columns — idempotent, NULL on older rows.
    existing = {row[1] for row in conn.execute("PRAGMA table_info(verdict_ledger)").fetchall()}
    # S9: action ('accept' default, 'override', 'go_live', 'leave_live') and
    # the live allocation committed at go-live.
    for col, sqltype in (("override_reason", "TEXT"), ("override_expires_at", "TEXT"),
                         ("allocation_cap_pct", "REAL"), ("thresholds_hash", "TEXT"),
                         ("action", "TEXT"), ("live_allocation_usd", "REAL"), ("card_id", "TEXT")):
        if col not in existing:
            conn.execute(f"ALTER TABLE verdict_ledger ADD COLUMN {col} {sqltype}")
    conn.executescript("""
    CREATE INDEX IF NOT EXISTS idx_ledger_run ON verdict_ledger(scoring_run_id);
    CREATE INDEX IF NOT EXISTS idx_ledger_strategy ON verdict_ledger(strategy_name);
    CREATE INDEX IF NOT EXISTS idx_ledger_created ON verdict_ledger(created_at);
    """)
    conn.commit()
    return conn


def get_row(row_id, db_path: Path = DEFAULT_DB_PATH) -> Optional[dict]:
    """One ledger row as a dict (S9: receipts are verified against it), or
    None when it does not exist / the DB is unreadable."""
    try:
        conn = _connect(db_path)
    except Exception:  # noqa: BLE001
        return None
    try:
        conn.row_factory = sqlite3.Row
        r = conn.execute("SELECT * FROM verdict_ledger WHERE id = ?", (int(row_id),)).fetchone()
        return dict(r) if r is not None else None
    except Exception:  # noqa: BLE001
        return None
    finally:
        conn.close()


LIVE_ACTIONS = ("go_live", "live_allocation", "live_rearm", "leave_live")


def get_latest_live_row(card_id: str, db_path: Path = DEFAULT_DB_PATH) -> Optional[dict]:
    """The newest live-action row for a card (go_live / live_allocation /
    live_rearm / leave_live), or None. A receipt is real only if it names
    THIS row — a leave_live newer than the receipt supersedes it."""
    if not card_id:
        return None
    try:
        conn = _connect(db_path)
    except Exception:  # noqa: BLE001
        return None
    try:
        conn.row_factory = sqlite3.Row
        q = "SELECT * FROM verdict_ledger WHERE card_id = ? AND action IN (%s) ORDER BY id DESC LIMIT 1" % \
            ",".join("?" * len(LIVE_ACTIONS))
        r = conn.execute(q, (card_id, *LIVE_ACTIONS)).fetchone()
        return dict(r) if r is not None else None
    except Exception:  # noqa: BLE001
        return None
    finally:
        conn.close()


def log_decision(
    *,
    strategy_name: str,
    scoring_run_id: Optional[str],
    path: str,
    verdict: Optional[str],
    promotion_route: str,
    blockers: Optional[list[str]] = None,
    override_used: bool = False,
    activated: bool = False,
    override_reason: Optional[str] = None,
    override_expires_at: Optional[str] = None,
    allocation_cap_pct: Optional[float] = None,
    thresholds_hash: Optional[str] = None,
    action: Optional[str] = None,
    live_allocation_usd: Optional[float] = None,
    card_id: Optional[str] = None,
    db_path: Path = DEFAULT_DB_PATH,
) -> int:
    """Append one verdict-ledger row. Returns the new row id.

    Args:
      strategy_name:   canonical strategy id (== base_name == audit strategy_name).
      scoring_run_id:  reference into audit runs.run_id (may be empty/None).
      path:            'pine' or 'python' (which accept chokepoint).
      verdict:         normalized verdict string at decision time.
      promotion_route: 'CLEAR' | 'ADVISORY' | 'BLOCKED' (route_promotion output).
      blockers:        DISQ_* token list; serialized to a JSON array.
      override_used:   confirm_non_robust as submitted (Pine path: always False).
      activated:       whether the card was created enabled (refused = False).

    Append-only: no upsert. May raise; the caller is responsible for the
    fail-open wrap (see approve_strategy._log_ledger).
    """
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    blockers_json = json.dumps(list(blockers or []))
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            """
            INSERT INTO verdict_ledger (
                created_at, scoring_run_id, strategy_name, path,
                verdict, promotion_route, blockers_json,
                override_used, activated,
                override_reason, override_expires_at, allocation_cap_pct, thresholds_hash,
                action, live_allocation_usd, card_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at, scoring_run_id, strategy_name, path,
                verdict, promotion_route, blockers_json,
                1 if override_used else 0,
                1 if activated else 0,
                override_reason, override_expires_at, allocation_cap_pct, thresholds_hash,
                action, live_allocation_usd, card_id,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()
