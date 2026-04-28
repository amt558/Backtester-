"""Runtime canary integrity check (Slice 0.5).

Tests for `tradelab.canaries.runtime.run_canary_check`. The function reads the
most recent verdict per canary from the audit DB and reports MATCH / MISMATCH /
UNKNOWN per canary. Only MISMATCH (a verdict outside the expected set, e.g.
ROBUST) flips `all_match=False` — UNKNOWN (never run) is a missing-data state,
not engine drift, so it must NOT block accepts.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tradelab.audit import record_run
from tradelab.canaries.runtime import CanaryStatus, run_canary_check
from tradelab.cli_canary import CANARY_NAMES


def _db(tmp_path: Path) -> Path:
    return tmp_path / "data" / "tradelab_history.db"


def test_all_canaries_never_run_returns_unknown_but_all_match_true(tmp_path):
    """Empty DB → 4 canaries with status UNKNOWN, all_match=True (UNKNOWN does
    not block accepts; only MISMATCH does)."""
    status = run_canary_check(db_path=_db(tmp_path))
    assert isinstance(status, CanaryStatus)
    assert status.all_match is True
    assert len(status.canaries) == 4
    names = {c["name"] for c in status.canaries}
    assert names == set(CANARY_NAMES)
    for c in status.canaries:
        assert c["status"] == "UNKNOWN"
        assert c["actual"] is None
        assert c["last_run"] is None


def test_all_fragile_returns_all_match(tmp_path):
    """All 4 canaries with FRAGILE verdicts → all_match=True, all MATCH."""
    db = _db(tmp_path)
    for name in CANARY_NAMES:
        record_run(name, verdict="FRAGILE", dsr_probability=0.2, db_path=db)
    status = run_canary_check(db_path=db)
    assert status.all_match is True
    for c in status.canaries:
        assert c["status"] == "MATCH"
        assert c["actual"] == "FRAGILE"
        assert c["last_run"] is not None


def test_one_robust_canary_flips_all_match_false(tmp_path):
    """3 FRAGILE + 1 ROBUST (leak_canary) → all_match=False, that one MISMATCH."""
    db = _db(tmp_path)
    for name in CANARY_NAMES:
        verdict = "ROBUST" if name == "leak_canary" else "FRAGILE"
        record_run(name, verdict=verdict, dsr_probability=0.5, db_path=db)
    status = run_canary_check(db_path=db)
    assert status.all_match is False
    by_name = {c["name"]: c for c in status.canaries}
    assert by_name["leak_canary"]["status"] == "MISMATCH"
    assert by_name["leak_canary"]["actual"] == "ROBUST"
    for other in ("rand_canary", "overfit_canary", "survivor_canary"):
        assert by_name[other]["status"] == "MATCH"


def test_inconclusive_is_match_for_canaries(tmp_path):
    """INCONCLUSIVE is in EXPECTED_VERDICT for every canary → MATCH not MISMATCH."""
    db = _db(tmp_path)
    for name in CANARY_NAMES:
        record_run(name, verdict="INCONCLUSIVE", dsr_probability=0.5, db_path=db)
    status = run_canary_check(db_path=db)
    assert status.all_match is True
    for c in status.canaries:
        assert c["status"] == "MATCH"
        assert c["actual"] == "INCONCLUSIVE"


def test_status_dict_serializes_via_to_dict(tmp_path):
    """CanaryStatus.to_dict() returns a JSON-serializable dict with the expected keys."""
    db = _db(tmp_path)
    record_run("rand_canary", verdict="FRAGILE", dsr_probability=0.2, db_path=db)
    status = run_canary_check(db_path=db)
    d = status.to_dict()
    assert set(d.keys()) == {"all_match", "canaries", "last_run_at"}
    assert isinstance(d["all_match"], bool)
    assert isinstance(d["canaries"], list)
    assert isinstance(d["last_run_at"], str) and d["last_run_at"]
    # Round-trip through json to confirm serializability
    blob = json.dumps(d)
    parsed = json.loads(blob)
    assert parsed["all_match"] == d["all_match"]
    assert len(parsed["canaries"]) == 4


def test_only_most_recent_row_per_canary_is_consulted(tmp_path):
    """If history has FRAGILE then ROBUST for the same canary, only the latest
    (ROBUST) counts → MISMATCH (engine drift). Guards against averaging /
    multi-row logic creeping in.

    Uses direct SQL to set explicit timestamps so the ordering can't be
    confused by sub-second collisions on fast hardware.
    """
    import sqlite3
    import uuid

    db = _db(tmp_path)
    # Seed the DB / schema via record_run for the other canaries first.
    for name in ("overfit_canary", "leak_canary", "survivor_canary"):
        record_run(name, verdict="FRAGILE", dsr_probability=0.2, db_path=db)
    # Insert two rows for rand_canary with explicit, ordered timestamps.
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO runs (run_id, timestamp_utc, strategy_name, verdict, dsr_probability) "
            "VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), "2026-04-27T10:00:00+00:00", "rand_canary", "FRAGILE", 0.2),
        )
        conn.execute(
            "INSERT INTO runs (run_id, timestamp_utc, strategy_name, verdict, dsr_probability) "
            "VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), "2026-04-28T10:00:00+00:00", "rand_canary", "ROBUST", 0.99),
        )
        conn.commit()
    finally:
        conn.close()
    status = run_canary_check(db_path=db)
    assert status.all_match is False
    by_name = {c["name"]: c for c in status.canaries}
    assert by_name["rand_canary"]["status"] == "MISMATCH"
    assert by_name["rand_canary"]["actual"] == "ROBUST"
