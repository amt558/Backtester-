import json
from pathlib import Path
import pytest
from tradelab.live.cards import CardRegistry
from tradelab.web.approve_strategy import accept_python_run, ActivationGateFailed
from tradelab.web import handlers


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


def test_accept_python_records_allocation(tmp_path):
    from tradelab.web.approve_strategy import accept_python_run
    from tradelab.live.cards import CardRegistry
    rf = tmp_path / "reports" / "frog_x"; rf.mkdir(parents=True); (rf/"backtest_result.json").write_text("{}")
    cj = tmp_path/"cards.json"; cj.write_text("{}"); reg = CardRegistry(cj)
    card = accept_python_run(base_name="frog", symbol="AAPL", timeframe="1D",
        report_folder=str(rf), verdict="ROBUST", dsr_probability=0.9, scoring_run_id="r",
        strategy="frog", registry=reg, reports_root=tmp_path/"reports", activate=False,
        allocation_usd=2500.0)
    assert card["allocation_usd"] == 2500.0


def test_patch_allocation_usd_via_existing_card_route(tmp_path, monkeypatch):
    """PATCH /tradelab/cards/{id} with allocation_usd updates the card
    via the existing handle_patch_with_status route (no new route needed)."""
    # Create a card in tmp cards.json
    cj = tmp_path / "cards.json"
    cj.write_text("{}")
    reg = CardRegistry(cj)
    reg.create("frog-v1", {"card_id": "frog-v1", "status": "disabled", "allocation_usd": None})

    monkeypatch.setattr(handlers, "_cards_path", lambda: cj)

    body_raw, status = handlers.handle_patch_with_status(
        "/tradelab/cards/frog-v1",
        json.dumps({"allocation_usd": 1500.0}).encode(),
    )
    assert status == 200, body_raw
    body = json.loads(body_raw)
    assert body["error"] is None

    # Confirm persisted — read a fresh registry from the file
    assert CardRegistry(cj).get("frog-v1")["allocation_usd"] == 1500.0


def test_patch_allocation_usd_rejects_negative(tmp_path, monkeypatch):
    """allocation_usd < 0 must be rejected with 400."""
    cj = tmp_path / "cards.json"
    cj.write_text("{}")
    reg = CardRegistry(cj)
    reg.create("frog-v1", {"card_id": "frog-v1", "status": "disabled"})

    monkeypatch.setattr(handlers, "_cards_path", lambda: cj)

    body_raw, status = handlers.handle_patch_with_status(
        "/tradelab/cards/frog-v1",
        json.dumps({"allocation_usd": -100.0}).encode(),
    )
    assert status == 400
    assert "allocation_usd" in json.loads(body_raw)["error"]


def test_patch_allocation_usd_accepts_null(tmp_path, monkeypatch):
    """allocation_usd: null is valid (clears allocation)."""
    cj = tmp_path / "cards.json"
    cj.write_text("{}")
    reg = CardRegistry(cj)
    reg.create("frog-v1", {"card_id": "frog-v1", "status": "disabled", "allocation_usd": 500.0})

    monkeypatch.setattr(handlers, "_cards_path", lambda: cj)

    body_raw, status = handlers.handle_patch_with_status(
        "/tradelab/cards/frog-v1",
        json.dumps({"allocation_usd": None}).encode(),
    )
    assert status == 200
    # Confirm persisted — read a fresh registry from the file
    assert CardRegistry(cj).get("frog-v1")["allocation_usd"] is None
