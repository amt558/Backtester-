"""
Per-strategy summary for the Research v3 cross-strategy factor matrix.

For each strategy in the audit DB, returns the latest run's verdict +
signals[] (read from that run's robustness_result.json sibling). This
powers the FE matrix cells (8 columns × N rows: pass/marginal/fail/dim
based on each signal's outcome).

Strategies with no usable run are still surfaced (with empty signals)
so the matrix shows the full universe — the "dimmed" row state in CSS
makes "no data yet" visually distinct from "scored but failed".
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional


_DEFAULT_DB = Path("data") / "tradelab_history.db"


def _resolve_db(db_path: Optional[Path]) -> Path:
    return Path(db_path) if db_path else _DEFAULT_DB


def _read_robustness(folder: Optional[Path]) -> tuple[Optional[str], list[dict], Optional[float]]:
    """Return (verdict_lowercase, signals_list, dsr_probability) for a run folder.

    Returns (None, [], None) on any miss — the row still shows in the
    matrix, just dimmed.
    """
    if folder is None:
        return None, [], None
    rob_path = folder / "robustness_result.json"
    if not rob_path.exists():
        return None, [], None
    try:
        data = json.loads(rob_path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return None, [], None
    verdict_block = data.get("verdict") or {}
    raw_verdict = verdict_block.get("verdict")
    verdict = raw_verdict.lower() if isinstance(raw_verdict, str) else None
    signals = verdict_block.get("signals") or []
    if not isinstance(signals, list):
        signals = []
    dsr = data.get("dsr_probability")
    try:
        dsr_f = float(dsr) if dsr is not None else None
    except (TypeError, ValueError):
        dsr_f = None
    return verdict, signals, dsr_f


def get_summaries(db_path: Optional[Path] = None) -> list[dict]:
    """Return per-strategy latest-run summary, newest first by timestamp.

    Each entry shape (matches the FE FACTOR_COLUMNS contract):
        {
            "id":              "s4_inside_day_breakout",
            "verdict":         "robust" | "fragile" | ... | None,
            "signals":         [{name, outcome, reason}, ...],
            "dsr_probability": 0.78 | None,
            "run_id":          "...",
            "timestamp_utc":   "ISO8601",
        }

    Strategies with no scored run get verdict=None and signals=[] so the
    matrix can still render their row (dimmed).
    """
    db = _resolve_db(db_path)
    if not db.exists():
        return []
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT run_id, timestamp_utc, strategy_name, verdict, "
            "report_card_html_path FROM runs ORDER BY timestamp_utc DESC"
        ).fetchall()
    finally:
        conn.close()

    seen: set[str] = set()
    out: list[dict] = []
    for r in rows:
        name = r["strategy_name"]
        if not name or name in seen:
            continue
        seen.add(name)
        folder = None
        rcp = r["report_card_html_path"]
        if rcp:
            p = Path(rcp)
            folder = p if p.is_dir() else p.parent
            if not folder.exists():
                folder = None
        verdict, signals, dsr = _read_robustness(folder)
        # Prefer the verdict from robustness_result.json (full text); fall
        # back to the DB column (already uppercase).
        if not verdict and isinstance(r["verdict"], str):
            verdict = r["verdict"].lower()
        out.append({
            "id":              name,
            "verdict":         verdict,
            "signals":         signals,
            "dsr_probability": dsr,
            "run_id":          r["run_id"],
            "timestamp_utc":   r["timestamp_utc"],
        })
    return out
