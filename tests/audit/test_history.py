"""Audit-trail SQLite history tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from tradelab.audit import diff_runs, get_run, list_runs, record_run


@pytest.fixture
def db(tmp_path):
    return tmp_path / "audit.db"


def test_record_and_get(db):
    rid = record_run(
        "s2_pocket_pivot",
        verdict="INCONCLUSIVE",
        dsr_probability=0.72,
        input_data_hash="abc123",
        config_hash="def456",
        report_card_markdown="# report\nbody",
        report_card_html_path="reports/foo/dashboard.html",
        db_path=db,
    )
    row = get_run(rid, db_path=db)
    assert row is not None
    assert row.run_id == rid
    assert row.strategy_name == "s2_pocket_pivot"
    assert row.verdict == "INCONCLUSIVE"
    assert row.dsr_probability == 0.72
    assert row.input_data_hash == "abc123"
    assert row.report_card_markdown == "# report\nbody"


def test_list_runs_filters_by_strategy(db):
    record_run("s2_pocket_pivot", db_path=db)
    record_run("rand_canary", db_path=db)
    record_run("s2_pocket_pivot", db_path=db)

    all_runs = list_runs(db_path=db)
    assert len(all_runs) == 3

    s2_only = list_runs(strategy="s2_pocket_pivot", db_path=db)
    assert len(s2_only) == 2
    assert all(r.strategy_name == "s2_pocket_pivot" for r in s2_only)


def test_list_runs_order_newest_first(db):
    id_1 = record_run("a", db_path=db)
    id_2 = record_run("a", db_path=db)
    rows = list_runs(db_path=db)
    # Most recent first
    assert rows[0].run_id == id_2
    assert rows[-1].run_id == id_1


def test_list_runs_empty_when_no_db():
    assert list_runs(db_path=Path("nonexistent.db")) == []


def test_get_run_missing_returns_none(db):
    # Create DB by recording one run, then query for a bogus id
    record_run("x", db_path=db)
    assert get_run("not-a-real-uuid", db_path=db) is None


def test_diff_runs_produces_unified_diff(db):
    a = record_run("x", report_card_markdown="one\ntwo\n", db_path=db)
    b = record_run("x", report_card_markdown="one\nTWO\n", db_path=db)
    d = diff_runs(a, b, db_path=db)
    assert "+TWO" in d or "+TWO\n" in d
    assert "-two" in d


def test_diff_runs_missing_side(db):
    a = record_run("x", report_card_markdown="one\n", db_path=db)
    d = diff_runs(a, "bogus", db_path=db)
    assert "not found" in d


def test_record_auto_populates_version_and_commit(db):
    rid = record_run("x", db_path=db)
    row = get_run(rid, db_path=db)
    # These should be auto-filled from determinism helpers
    assert row.tradelab_version is not None
    assert row.tradelab_git_commit is not None


def test_record_run_is_append_only_no_update_path(db):
    # There is no update API. Two records with the same strategy are distinct.
    id_1 = record_run("x", verdict="ROBUST", db_path=db)
    id_2 = record_run("x", verdict="FRAGILE", db_path=db)
    assert id_1 != id_2
    r1 = get_run(id_1, db_path=db)
    r2 = get_run(id_2, db_path=db)
    assert r1.verdict == "ROBUST"
    assert r2.verdict == "FRAGILE"
