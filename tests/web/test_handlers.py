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
    # /tradelab/runs now merges JobManager in-flight jobs; stub to empty
    from unittest.mock import MagicMock
    fake_jm = MagicMock(); fake_jm.list_jobs.return_value = []
    monkeypatch.setattr(handlers, "_get_job_manager", lambda: fake_jm)

    body = handlers.handle_get("/tradelab/runs")
    data = json.loads(body)
    # New unenveloped shape: {"runs": [...]} with `source` discriminator
    assert "runs" in data
    assert len(data["runs"]) == 3
    assert all(r["source"] == "audit" for r in data["runs"])


def test_handle_runs_list_with_query(fake_audit_db: Path, monkeypatch):
    monkeypatch.setattr(handlers, "_db_path", lambda: fake_audit_db)
    monkeypatch.setattr(handlers, "_cache_root", lambda: Path("."))
    monkeypatch.setattr(handlers, "_src_root", lambda: Path("src"))
    from unittest.mock import MagicMock
    fake_jm = MagicMock(); fake_jm.list_jobs.return_value = []
    monkeypatch.setattr(handlers, "_get_job_manager", lambda: fake_jm)

    body = handlers.handle_get("/tradelab/runs?strategy=s4_inside_day_breakout&limit=10")
    data = json.loads(body)
    assert len(data["runs"]) == 2


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


def test_handle_save_variant_happy_path(fake_tradelab_root, monkeypatch):
    # Prepare a base strategy file
    strategies_dir = fake_tradelab_root / "src" / "tradelab" / "strategies"
    strategies_dir.mkdir(parents=True, exist_ok=True)
    (strategies_dir / "base_strat.py").write_text('''
from tradelab.strategies.base import Strategy
class BaseStrat(Strategy):
    default_params = {"x": 1}
    def generate_signals(self, data, spy_close=None):
        return {k: v.copy() for k,v in data.items()}
''')
    # Fake yaml
    yaml_path = fake_tradelab_root / "tradelab.yaml"
    yaml_path.write_text("strategies:\n  base_strat:\n    module: tradelab.strategies.base_strat\n    class_name: BaseStrat\n    params: {}\n")

    monkeypatch.setattr(handlers, "_db_path", lambda: Path("nope.db"))
    monkeypatch.setattr(handlers, "_cache_root", lambda: Path("."))
    monkeypatch.setattr(handlers, "_src_root", lambda: fake_tradelab_root / "src")
    monkeypatch.setattr(handlers, "_staging_root", lambda: fake_tradelab_root / ".cache" / "new_strategy_staging")
    monkeypatch.setattr(handlers, "_yaml_path", lambda: yaml_path)

    # Stub subprocess.Popen — no CLI run during test
    monkeypatch.setattr(handlers.subprocess, "Popen", lambda *a, **kw: None)

    # Skip the smoke_5 backtest by mocking validate_and_stage to succeed instantly
    def fake_validate(name, code, staging_root, src_root):
        (Path(staging_root) / f"{name}.py").write_text(code)
        return {"error": None, "stage":"complete", "metrics":{}, "equity_curves_by_symbol":{}, "class_name":"BaseStrat"}
    monkeypatch.setattr(handlers.new_strategy, "validate_and_stage", fake_validate)

    # And stub _is_registered so register doesn't think name is taken
    monkeypatch.setattr(handlers.new_strategy, "_is_registered", lambda n: False)

    # Stub the registry so the route can resolve base_strat → module path
    # (list_registered_strategies / get_strategy_entry read real tradelab.yaml via get_config)
    from tradelab.config import StrategyEntry
    import tradelab.registry as _registry
    fake_entry = StrategyEntry(module="tradelab.strategies.base_strat", class_name="BaseStrat")
    monkeypatch.setattr(_registry, "list_registered_strategies", lambda: {"base_strat": fake_entry})
    monkeypatch.setattr(_registry, "get_strategy_entry", lambda name: fake_entry)

    payload = {"base_strategy":"base_strat","new_name":"base_strat_v2","params":{"x":5}}
    body = handlers.handle_post("/tradelab/save-variant", json.dumps(payload).encode())
    data = json.loads(body)
    assert data["error"] is None
    # Confirm the variant file was written with new defaults
    variant = fake_tradelab_root / "src" / "tradelab" / "strategies" / "base_strat_v2.py"
    assert variant.exists()
    assert "'x': 5" in variant.read_text() or '"x": 5' in variant.read_text()


def test_get_preflight_returns_all_four_statuses(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    from tradelab.web.handlers import handle_get_with_status
    body_str, status = handle_get_with_status("/tradelab/preflight")
    assert status == 200
    body = json.loads(body_str)
    assert body["error"] is None
    assert set(body["data"].keys()) == {"universe", "cache", "strategy", "tdapi"}
