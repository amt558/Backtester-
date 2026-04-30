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


def test_handle_baselines_returns_envelope_with_per_strategy_metrics(
    fake_audit_db: Path, fake_run_folder: Path, monkeypatch
):
    import sqlite3
    conn = sqlite3.connect(str(fake_audit_db))
    conn.execute(
        "UPDATE runs SET report_card_html_path = ? WHERE run_id = 'run-003'",
        (str(fake_run_folder),),
    )
    conn.commit(); conn.close()

    monkeypatch.setattr(handlers, "_db_path", lambda: fake_audit_db)
    body = handlers.handle_get("/tradelab/baselines")
    data = json.loads(body)
    assert data["error"] is None
    assert "baselines" in data["data"]
    s4 = data["data"]["baselines"]["s4_inside_day_breakout"]
    assert s4["metrics"]["win_rate"] == 59.09
    assert s4["metrics"]["profit_factor"] == 1.42
    assert s4["verdict"] == "ROBUST"


def test_handle_baselines_returns_empty_dict_when_db_missing(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(handlers, "_db_path", lambda: tmp_path / "nope.db")
    body = handlers.handle_get("/tradelab/baselines")
    data = json.loads(body)
    assert data["error"] is None
    assert data["data"] == {"baselines": {}}


def test_handle_relative_context_unknown_run_returns_404(monkeypatch):
    """T6: /tradelab/relative-context/<run_id> with unknown run_id → 404."""
    monkeypatch.setattr(handlers, "_db_path", lambda: Path("nope.db"))
    body, status = handlers.handle_get_with_status(
        "/tradelab/relative-context/no-such-run"
    )
    assert status == 404
    data = json.loads(body)
    assert data["error"] == "run not found"


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


def test_handle_runs_folder_distinguishes_no_run_from_no_folder(
    fake_audit_db, monkeypatch
):
    """Run in DB with NULL report_card_html_path must not say 'run not found'."""
    monkeypatch.setattr(handlers, "_db_path", lambda: fake_audit_db)
    monkeypatch.setattr(handlers, "_cache_root", lambda: Path("."))
    monkeypatch.setattr(handlers, "_src_root", lambda: Path("src"))

    # run-002 exists in fixture but report_card_html_path is NULL
    body, status = handlers.handle_get_with_status("/tradelab/runs/run-002/folder")
    assert status == 404
    assert json.loads(body)["error"] == "run has no report folder"

    # Truly missing run → "run not found"
    body, status = handlers.handle_get_with_status(
        "/tradelab/runs/does-not-exist/folder"
    )
    assert status == 404
    assert json.loads(body)["error"] == "run not found"


def test_handle_runs_robustness_returns_empty_for_no_folder(
    fake_audit_db, monkeypatch
):
    """Run in DB but null report path → 200 with empty signals (expected miss,
    not an error). Browser would otherwise log every Pipeline 404 to console.
    """
    monkeypatch.setattr(handlers, "_db_path", lambda: fake_audit_db)
    monkeypatch.setattr(handlers, "_cache_root", lambda: Path("."))
    monkeypatch.setattr(handlers, "_src_root", lambda: Path("src"))

    body, status = handlers.handle_get_with_status(
        "/tradelab/runs/run-002/robustness"
    )
    assert status == 200
    data = json.loads(body)["data"]
    assert data["signals"] == []
    assert data["verdict"] is None
    assert data["run_id"] == "run-002"

    # Missing run still says "run not found" (genuine error)
    body, status = handlers.handle_get_with_status(
        "/tradelab/runs/does-not-exist/robustness"
    )
    assert status == 404
    assert json.loads(body)["error"] == "run not found"


def test_handle_correlation_returns_empty_for_no_folder(
    fake_audit_db, monkeypatch
):
    monkeypatch.setattr(handlers, "_db_path", lambda: fake_audit_db)
    monkeypatch.setattr(handlers, "_cache_root", lambda: Path("."))
    monkeypatch.setattr(handlers, "_src_root", lambda: Path("src"))

    body, status = handlers.handle_get_with_status(
        "/tradelab/correlation/run-002"
    )
    assert status == 200
    data = json.loads(body)["data"]
    assert data["pairs"] == []
    assert data["max_return_rho"] == 0.0

    body, status = handlers.handle_get_with_status(
        "/tradelab/correlation/does-not-exist"
    )
    assert status == 404
    assert json.loads(body)["error"] == "run not found"


def test_handle_relative_context_returns_empty_for_no_folder(
    fake_audit_db, monkeypatch
):
    monkeypatch.setattr(handlers, "_db_path", lambda: fake_audit_db)
    monkeypatch.setattr(handlers, "_cache_root", lambda: Path("."))
    monkeypatch.setattr(handlers, "_src_root", lambda: Path("src"))

    body, status = handlers.handle_get_with_status(
        "/tradelab/relative-context/run-002"
    )
    assert status == 200
    data = json.loads(body)["data"]
    assert data["cohort_size"] == 0
    assert data["candidate"]["pf"] is None


def test_handle_tracking_error_returns_insufficient_for_missing_csv(
    fake_tradelab_root, monkeypatch
):
    """Non-Pine cards (e.g. tradelab strategy IDs in the Research-tab health
    grid) have no pine_archive entry. Return 200 + insufficient instead of
    404 so devtools stays clean."""
    monkeypatch.setattr(handlers, "_db_path", lambda: Path("nope.db"))
    monkeypatch.setattr(handlers, "_cache_root", lambda: Path("."))
    monkeypatch.setattr(handlers, "_src_root", lambda: Path("src"))
    monkeypatch.setattr(
        handlers, "_pine_archive_root", lambda: fake_tradelab_root / "pine_archive"
    )

    body, status = handlers.handle_get_with_status(
        "/tradelab/cards/S2_PocketPivot/tracking-error"
    )
    assert status == 200
    data = json.loads(body)["data"]
    assert data["status"] == "insufficient"
    assert data["n_live_trades"] == 0
    assert data["te"] is None


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


# ─── Research v3 routes ────────────────────────────────────────────────


def test_get_qs_metrics_unknown_run_returns_404(fake_audit_db: Path, monkeypatch):
    monkeypatch.setattr(handlers, "_db_path", lambda: fake_audit_db)
    body, status = handlers.handle_get_with_status(
        "/tradelab/runs/does-not-exist/qs-metrics"
    )
    assert status == 404


def test_get_qs_metrics_happy_returns_metric_keys(
    fake_audit_db: Path, fake_run_folder: Path, monkeypatch,
):
    """qs-metrics for a run with a backtest_result.json equity_curve returns
    the full sub-grid payload (sharpe, sortino, cagr, drawdown, monthly,
    rolling, plus the 4 header numbers)."""
    import sqlite3
    conn = sqlite3.connect(str(fake_audit_db))
    conn.execute(
        "UPDATE runs SET report_card_html_path = ? WHERE run_id = 'run-003'",
        (str(fake_run_folder / "dashboard.html"),),
    )
    conn.commit(); conn.close()
    monkeypatch.setattr(handlers, "_db_path", lambda: fake_audit_db)

    body, status = handlers.handle_get_with_status(
        "/tradelab/runs/run-003/qs-metrics"
    )
    assert status == 200
    payload = json.loads(body)
    for key in (
        "sharpe", "sortino", "cagr", "max_drawdown",
        "monthly_returns", "rolling_sharpe", "drawdown_series",
        "total_return", "trades", "win_rate", "profit_factor",
        "avg_win_pct", "avg_loss_pct", "avg_bars_held",
    ):
        assert key in payload, f"missing key {key!r}"
    assert isinstance(payload["monthly_returns"], list)
    assert isinstance(payload["rolling_sharpe"], list)
    assert isinstance(payload["drawdown_series"], list)
    # drawdown_series should be aligned with the equity curve (same length as
    # daily returns derived from it). Values are <= 0 (always at peak or below).
    if payload["drawdown_series"]:
        assert all(v <= 1e-9 for v in payload["drawdown_series"])


def test_get_qs_metrics_run_with_no_equity_curve_returns_404(
    fake_audit_db: Path, fake_tradelab_root: Path, monkeypatch,
):
    """A run with a folder but no backtest_result.json/equity_curve returns 404
    — the FE shows an empty-state rather than a fabricated metric payload."""
    import sqlite3
    folder = fake_tradelab_root / "reports" / "empty_run"
    folder.mkdir()
    (folder / "dashboard.html").write_text("<html></html>")
    conn = sqlite3.connect(str(fake_audit_db))
    conn.execute(
        "UPDATE runs SET report_card_html_path = ? WHERE run_id = 'run-001'",
        (str(folder / "dashboard.html"),),
    )
    conn.commit(); conn.close()
    monkeypatch.setattr(handlers, "_db_path", lambda: fake_audit_db)

    body, status = handlers.handle_get_with_status(
        "/tradelab/runs/run-001/qs-metrics"
    )
    assert status == 404


def test_get_verdict_history_returns_oldest_to_newest(
    fake_audit_db: Path, monkeypatch,
):
    """fake_audit_db has 2 ROBUST runs for s4_inside_day_breakout (run-002
    older, run-003 newer). Endpoint returns lowercase verdicts oldest → newest."""
    monkeypatch.setattr(handlers, "_db_path", lambda: fake_audit_db)
    body, status = handlers.handle_get_with_status(
        "/tradelab/strategies/s4_inside_day_breakout/verdict-history"
    )
    assert status == 200
    payload = json.loads(body)
    assert payload["verdicts"] == ["robust", "robust"]


def test_get_verdict_history_unknown_strategy_returns_empty_list(
    fake_audit_db: Path, monkeypatch,
):
    monkeypatch.setattr(handlers, "_db_path", lambda: fake_audit_db)
    body, status = handlers.handle_get_with_status(
        "/tradelab/strategies/nonexistent/verdict-history"
    )
    assert status == 200
    assert json.loads(body) == {"verdicts": []}


def test_post_accept_with_invalid_activate_type_returns_400(
    fake_tradelab_root: Path, monkeypatch,
):
    """activate must be a boolean; a string is rejected at the validation layer."""
    monkeypatch.setattr(handlers, "_cards_path",
                        lambda: fake_tradelab_root / "cards.json")
    monkeypatch.setattr(handlers, "_pine_archive_root",
                        lambda: fake_tradelab_root / "pine_archive")
    monkeypatch.setattr(handlers, "_reports_root",
                        lambda: fake_tradelab_root / "reports")

    payload = {
        "base_name": "smoke",
        "symbol": "AMZN",
        "timeframe": "1H",
        "report_folder": str(fake_tradelab_root / "reports" / "x"),
        "verdict": "ROBUST",
        "activate": "yes",  # invalid — should be a bool
    }
    body, status = handlers.handle_post_with_status(
        "/tradelab/accept", json.dumps(payload).encode()
    )
    assert status == 400
    assert "activate" in json.loads(body)["error"]


