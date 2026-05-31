from pathlib import Path
import pytest
from tradelab.live.cards import CardRegistry
from tradelab.web.approve_strategy import accept_python_run, ActivationGateFailed


def _run_folder(tmp_path: Path) -> Path:
    rf = tmp_path / "reports" / "frog_2026-05-31_120000"
    rf.mkdir(parents=True)
    (rf / "backtest_result.json").write_text("{}")
    return rf


def _registry(tmp_path: Path) -> CardRegistry:
    cj = tmp_path / "cards.json"
    cj.write_text("{}")
    return CardRegistry(cj)


def test_accept_python_creates_disabled_card(tmp_path):
    rf = _run_folder(tmp_path); reg = _registry(tmp_path)
    card = accept_python_run(
        base_name="frog", symbol="AAPL", timeframe="1D", report_folder=str(rf),
        verdict="INCONCLUSIVE", dsr_probability=0.4, scoring_run_id="run-1",
        strategy="frog", registry=reg, reports_root=tmp_path / "reports", activate=False)
    assert card["card_id"] == "frog-v1"
    assert card["status"] == "disabled"
    assert card["mode"] == "paper"
    assert card["source"] == "python"
    assert card["strategy"] == "frog"
    assert "secret" in card and "pine_archive_path" not in card
    assert reg.get("frog-v1") is not None


def test_accept_python_advisory_gate_blocks_non_robust_activate(tmp_path):
    rf = _run_folder(tmp_path); reg = _registry(tmp_path)
    with pytest.raises(ActivationGateFailed):
        accept_python_run(
            base_name="frog", symbol="AAPL", timeframe="1D", report_folder=str(rf),
            verdict="FRAGILE", dsr_probability=None, scoring_run_id="run-1",
            strategy="frog", registry=reg, reports_root=tmp_path / "reports",
            activate=True, confirm_non_robust=False)


def test_accept_python_confirm_overrides_advisory_gate(tmp_path):
    rf = _run_folder(tmp_path); reg = _registry(tmp_path)
    card = accept_python_run(
        base_name="frog", symbol="AAPL", timeframe="1D", report_folder=str(rf),
        verdict="FRAGILE", dsr_probability=None, scoring_run_id="run-1",
        strategy="frog", registry=reg, reports_root=tmp_path / "reports",
        activate=True, confirm_non_robust=True)
    assert card["status"] == "enabled"
    assert card["activated_verdict"] == "FRAGILE"


def test_accept_route_requires_fields():
    import json
    from tradelab.web import handlers
    body, status = handlers.handle_post_with_status(
        "/tradelab/strategies/accept", json.dumps({"base_name": "frog"}).encode())
    assert status == 400
