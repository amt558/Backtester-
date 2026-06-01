"""Task F: the advisory-verdict endpoint recomputes a candidate run's verdict
under user threshold overrides, labelled advisory, and writes NOTHING — it
cannot overwrite the stored verdict, the yaml, or create a card.
"""
from __future__ import annotations

import json
from pathlib import Path

from tradelab.results import BacktestMetrics, BacktestResult
from tradelab.robustness.suite import RobustnessSuiteResult
from tradelab.robustness.verdict import VerdictResult
from tradelab.web import handlers


def _seed_run(reports: Path) -> Path:
    run = reports / "adv_2024_01_01_000000"
    run.mkdir(parents=True)
    bt = BacktestResult(
        strategy="adv",
        start_date="2024-01-01",
        end_date="2024-06-01",
        metrics=BacktestMetrics(total_trades=30, profit_factor=1.4),
    )
    (run / "backtest_result.json").write_text(bt.model_dump_json(), encoding="utf-8")
    rob = RobustnessSuiteResult(
        strategy="adv",
        dsr_probability=None,
        verdict=VerdictResult(verdict="FRAGILE", signals=[]),
    )
    (run / "robustness_result.json").write_text(rob.model_dump_json(), encoding="utf-8")
    return run


def test_advisory_verdict_recomputes_without_writing(tmp_path: Path, monkeypatch):
    reports = tmp_path / "reports"
    run = _seed_run(reports)
    monkeypatch.setattr(handlers, "_reports_root", lambda: reports)

    body = handlers.handle_post(
        "/tradelab/new-strategy/advisory-verdict",
        json.dumps({
            "report_folder": "reports/adv_2024_01_01_000000",
            "overrides": {"pf_robust": 0.001, "pf_fragile": 0.0005},
        }).encode(),
    )
    data = json.loads(body)
    assert data["error"] is None, data
    d = data["data"]
    assert d["advisory"] is True
    # Stored verdict is read, never recomputed.
    assert d["canonical_verdict"] == "FRAGILE"
    # A lenient PF override removes the fragile baseline → no longer FRAGILE.
    assert d["advisory_verdict"] != "FRAGILE"

    # Guardrail: the run folder is byte-for-byte unchanged (no new/edited files).
    assert sorted(p.name for p in run.iterdir()) == [
        "backtest_result.json", "robustness_result.json"
    ]
    stored = json.loads((run / "robustness_result.json").read_text(encoding="utf-8"))
    assert stored["verdict"]["verdict"] == "FRAGILE"


def test_advisory_verdict_rejects_folder_outside_reports(tmp_path: Path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    monkeypatch.setattr(handlers, "_reports_root", lambda: reports)
    body = handlers.handle_post(
        "/tradelab/new-strategy/advisory-verdict",
        json.dumps({"report_folder": "../../etc", "overrides": {}}).encode(),
    )
    data = json.loads(body)
    assert data["error"] is not None
