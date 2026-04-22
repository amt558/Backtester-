"""Integration tests for request handlers (dispatch layer)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tradelab.web import handlers


def test_handle_runs_list(fake_audit_db: Path, monkeypatch):
    monkeypatch.setattr(handlers, "_db_path", lambda: fake_audit_db)
    monkeypatch.setattr(handlers, "_cache_root", lambda: Path("."))
    monkeypatch.setattr(handlers, "_src_root", lambda: Path("src"))

    body = handlers.handle_get("/tradelab/runs")
    data = json.loads(body)
    assert data["error"] is None
    assert len(data["data"]["runs"]) == 3
    assert data["data"]["total"] == 3


def test_handle_runs_list_with_query(fake_audit_db: Path, monkeypatch):
    monkeypatch.setattr(handlers, "_db_path", lambda: fake_audit_db)
    monkeypatch.setattr(handlers, "_cache_root", lambda: Path("."))
    monkeypatch.setattr(handlers, "_src_root", lambda: Path("src"))

    body = handlers.handle_get("/tradelab/runs?strategy=s4_inside_day_breakout&limit=10")
    data = json.loads(body)
    assert len(data["data"]["runs"]) == 2


def test_handle_data_freshness(fake_parquet_cache: Path, monkeypatch):
    monkeypatch.setattr(handlers, "_cache_root", lambda: fake_parquet_cache)
    monkeypatch.setattr(handlers, "_db_path", lambda: Path("nope.db"))
    monkeypatch.setattr(handlers, "_src_root", lambda: Path("src"))

    body = handlers.handle_get("/tradelab/data-freshness")
    data = json.loads(body)
    assert data["error"] is None
    assert data["data"]["symbol_count"] == 3


def test_handle_unknown_route_returns_404_shape():
    body, status = handlers.handle_get_with_status("/tradelab/nope")
    assert status == 404
    data = json.loads(body)
    assert data["error"] == "not found"


def test_handle_new_strategy_test_action(fake_tradelab_root: Path, monkeypatch):
    monkeypatch.setattr(handlers, "_db_path", lambda: Path("nope.db"))
    monkeypatch.setattr(handlers, "_cache_root", lambda: Path("."))
    monkeypatch.setattr(handlers, "_src_root", lambda: fake_tradelab_root / "src")
    monkeypatch.setattr(handlers, "_staging_root", lambda: fake_tradelab_root / ".cache" / "new_strategy_staging")

    from tradelab.web import new_strategy
    monkeypatch.setattr(new_strategy, "_is_registered", lambda n: False)

    payload = {
        "action": "discard",
        "name": "ghost_strat",
    }
    body = handlers.handle_post("/tradelab/new-strategy", json.dumps(payload).encode())
    data = json.loads(body)
    # Discard of non-existent staging is idempotent — error is None
    assert data["error"] is None


def test_handle_runs_folder_lookup(fake_audit_db, fake_run_folder, monkeypatch):
    import sqlite3
    conn = sqlite3.connect(str(fake_audit_db))
    conn.execute(
        "UPDATE runs SET report_card_html_path = ? WHERE run_id = 'run-003'",
        (str(fake_run_folder),),
    )
    conn.commit(); conn.close()

    monkeypatch.setattr(handlers, "_db_path", lambda: fake_audit_db)
    monkeypatch.setattr(handlers, "_cache_root", lambda: Path("."))
    monkeypatch.setattr(handlers, "_src_root", lambda: Path("src"))

    body, status = handlers.handle_get_with_status("/tradelab/runs/run-003/folder")
    assert status == 200
    assert json.loads(body)["data"]["folder"].endswith("s4_inside_day_breakout_2026-04-20_120000")
