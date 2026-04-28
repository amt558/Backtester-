import json
import sqlite3
from pathlib import Path

import pytest


def test_backfill_from_reports_extracts_signal_vector(tmp_path):
    """Backfill reads robustness_result.json (real shape) and writes per-signal
    outcomes into the runs table's signal_values_json column."""
    from tradelab.scripts.backfill_runs_table import backfill_from_reports

    db = tmp_path / "history.db"
    reports = tmp_path / "reports"
    one = reports / "s4_inside_day_breakout_2026-04-19"
    one.mkdir(parents=True)
    (one / "robustness_result.json").write_text(json.dumps({
        "strategy": "s4_inside_day_breakout",
        "dsr_probability": 0.42,
        "verdict": {
            "verdict": "FRAGILE",
            "signals": [
                {"name": "baseline_pf", "outcome": "fragile", "reason": "PF 1.05"},
                {"name": "entry_delay", "outcome": "fragile", "reason": "66%"},
                {"name": "param_landscape", "outcome": "robust", "reason": "..."},
            ],
        },
    }))

    n = backfill_from_reports(reports_dir=reports, db_path=db)
    assert n == 1

    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT strategy_name, verdict, dsr_probability, signal_values_json "
        "FROM runs WHERE strategy_name = 's4_inside_day_breakout'"
    ).fetchone()
    assert row[0] == "s4_inside_day_breakout"
    assert row[1] == "FRAGILE"
    assert row[2] == pytest.approx(0.42)
    sv = json.loads(row[3])
    # signal_values_json should be the per-signal map: {name: {outcome, reason}}
    assert sv["baseline_pf"]["outcome"] == "fragile"
    assert sv["entry_delay"]["outcome"] == "fragile"
    assert sv["param_landscape"]["outcome"] == "robust"


def test_backfill_skips_malformed_reports(tmp_path):
    from tradelab.scripts.backfill_runs_table import backfill_from_reports
    db = tmp_path / "history.db"
    reports = tmp_path / "reports"
    bad = reports / "broken"
    bad.mkdir(parents=True)
    (bad / "robustness_result.json").write_text("not valid json {")
    good = reports / "ok"
    good.mkdir(parents=True)
    (good / "robustness_result.json").write_text(json.dumps({
        "strategy": "x", "verdict": {"verdict": "ROBUST", "signals": []},
    }))

    n = backfill_from_reports(reports_dir=reports, db_path=db)
    assert n == 1  # only the valid one


def test_backfill_handles_legacy_shape(tmp_path):
    """Older reports may have signals as a top-level dict — must still backfill."""
    from tradelab.scripts.backfill_runs_table import backfill_from_reports
    db = tmp_path / "history.db"
    reports = tmp_path / "reports"
    legacy = reports / "old_shape"
    legacy.mkdir(parents=True)
    (legacy / "robustness_result.json").write_text(json.dumps({
        "strategy": "legacy_strat",
        "verdict": "FRAGILE",  # bare string in old shape
        "dsr_probability": 0.3,
        "signals": {
            "baseline_pf": {"value": 0.78, "verdict": "FRAGILE"},
            "dsr": {"value": 0.001, "verdict": "FRAGILE"},
        },
    }))
    n = backfill_from_reports(reports_dir=reports, db_path=db)
    assert n == 1
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT verdict, signal_values_json FROM runs WHERE strategy_name = 'legacy_strat'"
    ).fetchone()
    assert row[0] == "FRAGILE"
    assert json.loads(row[1])["baseline_pf"]["verdict"] == "FRAGILE"
