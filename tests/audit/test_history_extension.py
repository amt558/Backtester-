import sqlite3
import pytest
from pathlib import Path

from tradelab.audit.history import _connect, record_run


def test_extended_columns_present_on_fresh_db(tmp_path):
    db = tmp_path / "test.db"
    conn = _connect(db)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
    for required in ("signal_values_json", "thresholds_json", "accepted_bool", "reject_reason"):
        assert required in cols, f"missing column {required}"
    # also verify the legacy columns are still there
    for legacy in ("run_id", "timestamp_utc", "strategy_name", "verdict", "dsr_probability"):
        assert legacy in cols


def test_idempotent_migration_on_pre_extension_db(tmp_path):
    """Existing legacy DBs (verdict + dsr_probability only) get ALTER TABLE migrations."""
    db = tmp_path / "old.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY,
            timestamp_utc TEXT NOT NULL,
            strategy_name TEXT NOT NULL,
            verdict TEXT,
            dsr_probability REAL
        );
    """)
    conn.commit()
    conn.close()
    # Re-connect via _connect; migration should add the 4 columns
    conn2 = _connect(db)
    cols = {row[1] for row in conn2.execute("PRAGMA table_info(runs)").fetchall()}
    assert "signal_values_json" in cols
    assert "thresholds_json" in cols
    assert "accepted_bool" in cols
    assert "reject_reason" in cols


def test_migration_runs_idempotently_on_already_extended_db(tmp_path):
    """Calling _connect twice must not error."""
    db = tmp_path / "new.db"
    _connect(db).close()
    # second call should be a no-op for ALTER TABLE
    conn = _connect(db)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
    assert "signal_values_json" in cols


def test_record_run_persists_extended_fields(tmp_path):
    import json
    db = tmp_path / "test.db"
    run_id = record_run(
        strategy_name="S4_test",
        verdict="ROBUST",
        signal_values={"baseline_pf": 1.62, "dsr": 0.83},
        thresholds={"baseline_robust_pf": 1.5, "baseline_fragile_pf": 1.1},
        accepted=True,
        reject_reason=None,
        db_path=db,
    )
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT signal_values_json, thresholds_json, accepted_bool, reject_reason "
        "FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    assert row is not None
    assert json.loads(row[0])["baseline_pf"] == 1.62
    assert json.loads(row[1])["baseline_robust_pf"] == 1.5
    assert row[2] == 1
    assert row[3] is None


def test_record_run_accepted_false_persists_zero(tmp_path):
    db = tmp_path / "test.db"
    run_id = record_run(
        strategy_name="S2_test", verdict="FRAGILE",
        accepted=False, reject_reason="failed hold-out gate",
        db_path=db,
    )
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT accepted_bool, reject_reason FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    assert row[0] == 0
    assert row[1] == "failed hold-out gate"


def test_record_run_accepted_none_persists_null(tmp_path):
    """If accepted=None, accepted_bool should remain NULL (no decision yet)."""
    db = tmp_path / "test.db"
    run_id = record_run(
        strategy_name="S7_test", verdict="INCONCLUSIVE",
        accepted=None, db_path=db,
    )
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT accepted_bool FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    assert row[0] is None


def test_record_run_legacy_call_still_works(tmp_path):
    """Existing callers that don't pass signal_values/thresholds/accepted must still work."""
    db = tmp_path / "test.db"
    run_id = record_run(strategy_name="legacy", verdict="ROBUST", db_path=db)
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT signal_values_json, thresholds_json, accepted_bool FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    assert row[0] is None
    assert row[1] is None
    assert row[2] is None
