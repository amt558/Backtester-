"""Tests for the cross-strategy factor matrix data layer (Task 13)."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tradelab.web import strategies_summary


def _seed_robustness(folder: Path, *, verdict: str, signals: list[dict], dsr: float | None = None) -> None:
    """Drop a robustness_result.json into a run folder."""
    folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "strategy": folder.name.split("_")[0],
        "dsr_probability": dsr,
        "verdict": {
            "verdict": verdict,
            "signals": signals,
        },
    }
    (folder / "robustness_result.json").write_text(json.dumps(payload))


def test_get_summaries_empty_db(tmp_path: Path) -> None:
    db = tmp_path / "data" / "tradelab_history.db"
    assert strategies_summary.get_summaries(db_path=db) == []


def test_get_summaries_one_strategy_with_signals(fake_audit_db: Path, fake_run_folder: Path) -> None:
    """Latest run has a robustness_result.json with 3 signals → matrix row
    surfaces verdict + signals (lowercase, list-of-dicts shape)."""
    # Wire run-003 (newest s4_inside_day_breakout) to the run folder
    conn = sqlite3.connect(str(fake_audit_db))
    conn.execute(
        "UPDATE runs SET report_card_html_path = ? WHERE run_id = 'run-003'",
        (str(fake_run_folder / "dashboard.html"),),
    )
    conn.commit(); conn.close()
    _seed_robustness(
        fake_run_folder,
        verdict="ROBUST",
        signals=[
            {"name": "baseline_pf", "outcome": "robust", "reason": "PF 1.42 >= 1.3"},
            {"name": "dsr", "outcome": "inconclusive", "reason": "DSR 0.78"},
            {"name": "mc_max_dd", "outcome": "robust", "reason": "DD top 19%"},
        ],
        dsr=0.78,
    )
    out = strategies_summary.get_summaries(db_path=fake_audit_db)
    by_id = {s["id"]: s for s in out}
    s4 = by_id.get("s4_inside_day_breakout")
    assert s4 is not None
    # Verdict from robustness_result.json (lowercased), signals as list-of-dicts
    assert s4["verdict"] == "robust"
    assert isinstance(s4["signals"], list)
    assert len(s4["signals"]) == 3
    names = sorted(x["name"] for x in s4["signals"])
    assert names == ["baseline_pf", "dsr", "mc_max_dd"]
    # DSR plumbed through
    assert s4["dsr_probability"] == pytest.approx(0.78, abs=1e-9)
    # The newer run's id (not run-002)
    assert s4["run_id"] == "run-003"


def test_get_summaries_strategy_with_no_robustness_file_still_appears(
    fake_audit_db: Path, fake_run_folder: Path,
) -> None:
    """A strategy whose latest run is missing robustness_result.json should
    still show in the matrix with empty signals + verdict from the DB row
    (lowercased) — so the user sees the row dimmed instead of absent."""
    # Don't seed robustness for run-001 (s2_pocket_pivot, FRAGILE in db); the
    # row should still surface with signals=[] and verdict="fragile".
    out = strategies_summary.get_summaries(db_path=fake_audit_db)
    by_id = {s["id"]: s for s in out}
    s2 = by_id.get("s2_pocket_pivot")
    assert s2 is not None
    assert s2["verdict"] == "fragile"  # lowercased from DB row
    assert s2["signals"] == []


def test_get_summaries_picks_newest_per_strategy(
    fake_audit_db: Path, fake_run_folder: Path,
) -> None:
    """Two runs for s4_inside_day_breakout in fixture (run-002 older,
    run-003 newer) → only run-003 surfaces."""
    out = strategies_summary.get_summaries(db_path=fake_audit_db)
    s4_rows = [s for s in out if s["id"] == "s4_inside_day_breakout"]
    assert len(s4_rows) == 1
    assert s4_rows[0]["run_id"] == "run-003"


def test_get_summaries_handles_corrupt_robustness_json(
    fake_audit_db: Path, fake_run_folder: Path,
) -> None:
    """A malformed robustness_result.json must not blow up the whole
    summary call — the row degrades to verdict from DB + empty signals."""
    conn = sqlite3.connect(str(fake_audit_db))
    conn.execute(
        "UPDATE runs SET report_card_html_path = ? WHERE run_id = 'run-003'",
        (str(fake_run_folder / "dashboard.html"),),
    )
    conn.commit(); conn.close()
    (fake_run_folder / "robustness_result.json").write_text("{not json")
    out = strategies_summary.get_summaries(db_path=fake_audit_db)
    by_id = {s["id"]: s for s in out}
    s4 = by_id["s4_inside_day_breakout"]
    assert s4["signals"] == []
    # Falls back to DB column verdict (ROBUST → robust)
    assert s4["verdict"] == "robust"


def test_handler_strategies_summary_route_returns_200(
    fake_audit_db: Path, monkeypatch,
) -> None:
    """The HTTP route returns the {strategies: [...]} envelope. Must be
    reachable without any path params."""
    from tradelab.web import handlers
    monkeypatch.setattr(handlers, "_db_path", lambda: fake_audit_db)
    body, status = handlers.handle_get_with_status("/tradelab/strategies-summary")
    assert status == 200
    payload = json.loads(body)
    assert "strategies" in payload
    assert isinstance(payload["strategies"], list)
    # The fake_audit_db has 2 distinct strategies
    ids = sorted(s["id"] for s in payload["strategies"])
    assert ids == ["s2_pocket_pivot", "s4_inside_day_breakout"]
    # Each row has the full contract shape
    for s in payload["strategies"]:
        for k in ("id", "verdict", "signals", "dsr_probability", "run_id", "timestamp_utc"):
            assert k in s, f"missing key {k!r} on row {s.get('id')}"


def test_handler_strategies_summary_no_db_returns_empty_list(
    tmp_path: Path, monkeypatch,
) -> None:
    """If the audit DB doesn't exist (fresh checkout / wrong cwd) the
    handler returns a 200 with an empty list, not a 500."""
    from tradelab.web import handlers
    monkeypatch.setattr(handlers, "_db_path", lambda: tmp_path / "missing.db")
    body, status = handlers.handle_get_with_status("/tradelab/strategies-summary")
    assert status == 200
    payload = json.loads(body)
    assert payload == {"strategies": []}
