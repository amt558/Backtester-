"""Tests for the Research v3 drift-sparkline data source."""
import sqlite3
from pathlib import Path

import pytest

from tradelab.web.verdict_history import get_recent_verdicts


@pytest.fixture
def fixture_db(tmp_path: Path) -> Path:
    """Build a fixture audit DB with 15 runs for one strategy."""
    db = tmp_path / "tradelab_history.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE runs ("
        "  run_id TEXT PRIMARY KEY, "
        "  strategy_name TEXT, "
        "  verdict TEXT, "
        "  timestamp_utc TEXT"
        ")"
    )
    # Production stores verdicts UPPERCASE; helper normalizes to lowercase.
    rows = [
        (f"r{i:03d}", "virpo-mu-v1", v, f"2026-04-{(i % 28) + 1:02d}T10:00:00")
        for i, v in enumerate([
            "ROBUST", "ROBUST", "ROBUST", "MARGINAL", "ROBUST",
            "ROBUST", "MARGINAL", "MARGINAL", "FRAGILE", "ROBUST",
            "ROBUST", "ROBUST", "ROBUST", "ROBUST", "ROBUST",
        ])
    ]
    conn.executemany("INSERT INTO runs VALUES (?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return db


def test_returns_at_most_n_verdicts(fixture_db: Path):
    out = get_recent_verdicts("virpo-mu-v1", n=12, db_path=fixture_db)
    assert len(out) == 12


def test_returns_oldest_to_newest_order(fixture_db: Path):
    out = get_recent_verdicts("virpo-mu-v1", n=12, db_path=fixture_db)
    # The 12 most recent runs by timestamp_utc; r014 is newest at 2026-04-15
    # (i=14 → day 15) with verdict "ROBUST". Last few inserted rows are all ROBUST.
    assert out[-1] == "robust"
    assert out[-2] == "robust"


def test_returned_verdicts_are_lowercase(fixture_db: Path):
    out = get_recent_verdicts("virpo-mu-v1", n=12, db_path=fixture_db)
    for v in out:
        assert v == v.lower()
        assert v in {"robust", "marginal", "fragile", "inconclusive"}


def test_unknown_strategy_returns_empty(fixture_db: Path):
    assert get_recent_verdicts("does-not-exist", n=12, db_path=fixture_db) == []


def test_default_db_path_used_when_unspecified(monkeypatch, fixture_db: Path):
    monkeypatch.setattr(
        "tradelab.web.verdict_history._default_db_path", lambda: fixture_db
    )
    assert len(get_recent_verdicts("virpo-mu-v1", n=12)) == 12


def test_missing_db_returns_empty(tmp_path: Path):
    no_db = tmp_path / "does-not-exist.db"
    assert get_recent_verdicts("virpo-mu-v1", n=12, db_path=no_db) == []


def test_n_smaller_than_available(fixture_db: Path):
    out = get_recent_verdicts("virpo-mu-v1", n=3, db_path=fixture_db)
    assert len(out) == 3
    # All three should be the most-recent runs (oldest→newest order in result)
    assert out[-1] == "robust"
