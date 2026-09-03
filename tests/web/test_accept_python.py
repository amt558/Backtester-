import json
from pathlib import Path
import pytest
from tradelab.live.cards import CardRegistry
from tradelab.web.approve_strategy import accept_python_run, ActivationGateFailed
from tradelab.web import handlers


def _run_folder(tmp_path: Path, write_backtest_result) -> Path:
    # Step 3: activate=True now fail-closed-reads backtest_result.json, so the
    # folder needs a VALID one (positive net_pnl → disqualifier floor clean).
    rf = tmp_path / "reports" / "frog_2026-05-31_120000"
    write_backtest_result(rf)
    return rf


def _registry(tmp_path: Path) -> CardRegistry:
    cj = tmp_path / "cards.json"
    cj.write_text("{}")
    return CardRegistry(cj)


def test_accept_python_creates_disabled_card(tmp_path, write_backtest_result):
    rf = _run_folder(tmp_path, write_backtest_result); reg = _registry(tmp_path)
    # S4: only a CLEAR route (ROBUST verdict, clean floor) becomes a card —
    # even Off. INCONCLUSIVE is ADVISORY and refused until the S6 override.
    card = accept_python_run(
        base_name="frog", symbol="AAPL", timeframe="1D", report_folder=str(rf),
        verdict="ROBUST", dsr_probability=0.9, scoring_run_id="run-1",
        strategy="frog", registry=reg, reports_root=tmp_path / "reports", activate=False)
    assert card["card_id"] == "frog-v1" and card["promotion_route"] == "CLEAR"
    assert card["status"] == "disabled"
    assert card["mode"] == "paper"
    assert card["source"] == "python"
    assert card["strategy"] == "frog"
    assert "secret" in card and "pine_archive_path" not in card
    assert reg.get("frog-v1") is not None


def test_accept_python_advisory_gate_blocks_non_robust_activate(tmp_path, write_backtest_result):
    rf = _run_folder(tmp_path, write_backtest_result); reg = _registry(tmp_path)
    with pytest.raises(ActivationGateFailed):
        accept_python_run(
            base_name="frog", symbol="AAPL", timeframe="1D", report_folder=str(rf),
            verdict="FRAGILE", dsr_probability=None, scoring_run_id="run-1",
            strategy="frog", registry=reg, reports_root=tmp_path / "reports",
            activate=True, confirm_non_robust=False)


def test_accept_python_checkbox_no_longer_confirms_advisory(tmp_path, write_backtest_result):
    """S6: confirm_non_robust is ignored — only an override receipt confirms
    ADVISORY, and a grant never arms the card."""
    from tradelab.web.approve_strategy import AdvisoryRefused, ActivationGateFailed
    rf = _run_folder(tmp_path, write_backtest_result); reg = _registry(tmp_path)
    with pytest.raises(AdvisoryRefused):
        accept_python_run(
            base_name="frog", symbol="AAPL", timeframe="1D", report_folder=str(rf),
            verdict="FRAGILE", dsr_probability=None, scoring_run_id="run-1",
            strategy="frog", registry=reg, reports_root=tmp_path / "reports",
            activate=True, confirm_non_robust=True)
    receipt = {"reason": "x" * 20, "granted_at": "2026-09-03T00:00:00+00:00", "expires_at": "2026-10-03T00:00:00+00:00",
               "allocation_cap_pct": 50.0, "scoring_run_id": "run-1", "thresholds_hash": "t"}
    with pytest.raises(ActivationGateFailed):
        accept_python_run(
            base_name="frog", symbol="AAPL", timeframe="1D", report_folder=str(rf),
            verdict="FRAGILE", dsr_probability=None, scoring_run_id="run-1",
            strategy="frog", registry=reg, reports_root=tmp_path / "reports",
            activate=True, override=receipt, db_path=tmp_path / "audit.db")
    card = accept_python_run(
        base_name="frog", symbol="AAPL", timeframe="1D", report_folder=str(rf),
        verdict="FRAGILE", dsr_probability=None, scoring_run_id="run-1",
        strategy="frog", registry=reg, reports_root=tmp_path / "reports",
        activate=False, override=receipt, db_path=tmp_path / "audit.db")
    assert card["status"] == "disabled" and card["override"]["reason"] == "x" * 20


def test_accept_route_requires_fields():
    import json
    from tradelab.web import handlers
    body, status = handlers.handle_post_with_status(
        "/tradelab/strategies/accept", json.dumps({"base_name": "frog"}).encode())
    assert status == 400


def test_accept_python_records_allocation(tmp_path, write_backtest_result):
    from tradelab.web.approve_strategy import accept_python_run
    from tradelab.live.cards import CardRegistry
    # S4: the route gate runs on every accept, so the folder needs a real
    # backtest_result.json even when activate=False.
    rf = _run_folder(tmp_path, write_backtest_result)
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


def test_accept_python_off_still_refuses_advisory(tmp_path, write_backtest_result):
    """S4 (specialist review): activate=False used to skip the ADVISORY refusal,
    creating Off cards for non-ROBUST runs against the 2026-06-11 rule."""
    from tradelab.web.approve_strategy import AdvisoryRefused
    rf = _run_folder(tmp_path, write_backtest_result); reg = _registry(tmp_path)
    with pytest.raises(AdvisoryRefused):
        accept_python_run(
            base_name="frog", symbol="AAPL", timeframe="1D", report_folder=str(rf),
            verdict="INCONCLUSIVE", dsr_probability=0.4, scoring_run_id="run-1",
            strategy="frog", registry=reg, reports_root=tmp_path / "reports", activate=False)
    assert reg.get("frog-v1") is None
