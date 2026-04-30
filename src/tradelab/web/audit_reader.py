"""Read tradelab_history.db and join per-run backtest_result.json metrics.

Audit DB schema lives in tradelab.audit.history — this module is a
read-only view for the web layer with filtering and pagination.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import NamedTuple, Optional

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
        # Over-fetch to allow post-filtering of archived ids
        sql += " ORDER BY timestamp_utc DESC LIMIT ? OFFSET ?"
        args.extend([limit + len(archived_ids), offset])
        rows = conn.execute(sql, args).fetchall()
    finally:
        conn.close()

    out = [dict(r) for r in rows if r["run_id"] not in archived_ids]
    return out[:limit]


def count_runs(
    strategy: Optional[str] = None,
    verdicts: Optional[list[str]] = None,
    since: Optional[str] = None,
    db_path: Optional[Path] = None,
    exclude_archived: bool = True,
) -> int:
    """Return total count matching filter — used for pagination UI."""
    db = _resolve_db(db_path)
    if not db.exists():
        return 0
    archived_ids: set[str] = set()
    if exclude_archived:
        from tradelab.audit.archive import list_archived_run_ids
        archived_ids = list_archived_run_ids(db_path=db)

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
        if archived_ids:
            placeholders = ",".join("?" * len(archived_ids))
            where.append(f"run_id NOT IN ({placeholders})")
            args.extend(archived_ids)
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


class RunFolderLookup(NamedTuple):
    status: str  # "ok" | "no_run" | "no_folder"
    folder: Optional[Path]


def resolve_run_folder(
    run_id: str, db_path: Optional[Path] = None
) -> RunFolderLookup:
    """Three-way lookup distinguishing missing run from missing folder.

    - status="ok": run exists in DB and report_card_html_path resolves to a folder
    - status="no_run": run_id not in runs table (or DB doesn't exist)
    - status="no_folder": run is in DB but report_card_html_path is NULL
      (e.g. CLI runs invoked without --report)
    """
    db = _resolve_db(db_path)
    if not db.exists():
        return RunFolderLookup("no_run", None)
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT report_card_html_path FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return RunFolderLookup("no_run", None)
    if not row[0]:
        return RunFolderLookup("no_folder", None)
    p = Path(row[0])
    return RunFolderLookup("ok", p if p.is_dir() else p.parent)


def get_run_folder(run_id: str, db_path: Optional[Path] = None) -> Optional[Path]:
    """Return the run's reports folder (for iframe src construction).

    Collapses 'run not in DB' and 'run has null report path' into None.
    Use resolve_run_folder() when callers need to distinguish.
    """
    return resolve_run_folder(run_id, db_path).folder


def _pf_from_report_path(report_path_str: Optional[str]) -> Optional[float]:
    """Read profit_factor from the run's backtest_result.json sibling.

    The runs table doesn't store PF — it lives in the per-run JSON. Returns
    None on any miss so the slide-pane history can render "PF —".
    """
    if not report_path_str:
        return None
    folder = Path(report_path_str)
    if folder.is_file():
        folder = folder.parent
    json_path = folder / "backtest_result.json"
    if not json_path.exists():
        return None
    try:
        data = json.loads(json_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    metrics = data.get("metrics") or {}
    pf = metrics.get("profit_factor")
    if pf is None:
        pf = metrics.get("pf")
    try:
        return float(pf) if pf is not None else None
    except (TypeError, ValueError):
        return None


def _metrics_from_report_path(report_path_str: Optional[str]) -> dict:
    """Read full metrics dict from the run's backtest_result.json sibling.

    Like _pf_from_report_path() but returns the entire metrics block rather
    than just profit_factor. Returns {} on any miss so callers can treat
    "no data" uniformly.
    """
    if not report_path_str:
        return {}
    folder = Path(report_path_str)
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


def baselines_for_all_strategies(
    db_path: Optional[Path] = None,
    exclude_archived: bool = True,
) -> dict[str, dict]:
    """Return latest backtest metrics per strategy from the audit DB.

    For each strategy_name, walks runs newest-first and returns the first
    row whose backtest_result.json exists with a non-empty metrics dict.
    Strategies with no usable run are omitted.

    Why this exists: the Command Center's Strategy Divergence KPI compares
    live win rate against baseline values. Frozen baselines miscalibrate the
    KPI as strategies drift; this surfaces the most-recent OOS baseline so
    the dashboard can refresh on page load.

    Returned shape:
        {
            "s4_inside_day_breakout": {
                "run_id": "...",
                "timestamp_utc": "...",
                "verdict": "FRAGILE",
                "metrics": {win_rate, profit_factor, pct_return,
                            sharpe_ratio, max_drawdown_pct, total_trades, ...},
            },
            ...
        }
    """
    db = _resolve_db(db_path)
    if not db.exists():
        return {}

    archived_ids: set[str] = set()
    if exclude_archived:
        from tradelab.audit.archive import list_archived_run_ids
        archived_ids = list_archived_run_ids(db_path=db)

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT run_id, timestamp_utc, strategy_name, verdict, "
            "report_card_html_path FROM runs ORDER BY timestamp_utc DESC"
        ).fetchall()
    finally:
        conn.close()

    out: dict[str, dict] = {}
    for r in rows:
        if r["run_id"] in archived_ids:
            continue
        name = r["strategy_name"]
        if name in out:
            continue  # already have the newest valid run for this strategy
        metrics = _metrics_from_report_path(r["report_card_html_path"])
        if not metrics:
            continue
        out[name] = {
            "run_id": r["run_id"],
            "timestamp_utc": r["timestamp_utc"],
            "verdict": r["verdict"],
            "metrics": metrics,
        }
    return out


def history_for_strategy(
    strategy: str,
    *,
    limit: int = 10,
    exclude_archived: bool = True,
    db_path: Optional[Path] = None,
) -> list[dict]:
    """Return last N runs for a single strategy, ordered by timestamp desc.

    Each row gets a `pf` field joined from the run's backtest_result.json
    (None if the JSON is missing or has no profit_factor).
    """
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

    out = [dict(r) for r in rows if r["run_id"] not in archived_ids][:limit]
    for r in out:
        r["pf"] = _pf_from_report_path(r.get("report_card_html_path"))
    return out
