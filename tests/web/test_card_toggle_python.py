"""Phase 3a Task 3: a Python card (created by accept_python_run) toggles on/off
through the same CardRegistry.bulk_update_status that the
`POST /tradelab/cards/bulk-toggle` route uses. No Python-specific toggle code is
needed — Python cards live in the same cards.json with the same `status` field."""
from __future__ import annotations

from pathlib import Path

from tradelab.live.cards import CardRegistry
from tradelab.web.approve_strategy import accept_python_run


def _make_python_card(tmp_path: Path) -> CardRegistry:
    rf = tmp_path / "reports" / "frog_2026-05-31_120000"
    rf.mkdir(parents=True)
    # S4: accept routes every run (not only on activate), so the folder needs a
    # real backtest_result.json — an empty one fails closed.
    from tradelab.results import BacktestMetrics, BacktestResult
    bt = BacktestResult(strategy="frog", symbol="AAPL", timeframe="1D", start_date="2024-01-01",
                        end_date="2026-04-20", metrics=BacktestMetrics(net_pnl=240.0))
    (rf / "backtest_result.json").write_text(bt.model_dump_json())
    cj = tmp_path / "cards.json"
    cj.write_text("{}")
    reg = CardRegistry(cj)
    accept_python_run(
        base_name="frog", symbol="AAPL", timeframe="1D", report_folder=str(rf),
        verdict="ROBUST", dsr_probability=0.9, scoring_run_id="r", strategy="frog",
        registry=reg, reports_root=tmp_path / "reports", activate=False,
    )
    return reg


def test_python_card_toggles_enabled_then_disabled(tmp_path):
    reg = _make_python_card(tmp_path)
    assert reg.get("frog-v1")["status"] == "disabled"

    updated, failed = reg.bulk_update_status(["frog-v1"], "enabled")
    assert "frog-v1" in updated and not failed
    # persisted to disk (the route re-reads via a fresh CardRegistry)
    assert CardRegistry(tmp_path / "cards.json").get("frog-v1")["status"] == "enabled"

    reg.bulk_update_status(["frog-v1"], "disabled")
    assert CardRegistry(tmp_path / "cards.json").get("frog-v1")["status"] == "disabled"
