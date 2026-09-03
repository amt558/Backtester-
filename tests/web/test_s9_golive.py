"""S9 (2026-09-03) — the go-live gate: live keys + typed confirmation; CLEAR or
ADVISORY with an active override; ladder + canaries; tickers; flat paper;
budget; ledger first (fail closed); the card is armed OFF; only the go-live
route writes mode:"live"; PATCH re-checks the live budget."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from tradelab.live import golive
from tradelab.web import handlers

NOW = datetime(2026, 9, 3, 15, 0, tzinfo=timezone.utc)
POLICY = {"max_total_allocation_usd": 25000.0, "daily_loss_limit_usd": 1000.0, "require_flat_paper": True}
FT_OK = {"ok": True, "code": "ok", "reason": None}
FT_BAD = {"ok": False, "code": "not_full", "reason": "latest run is a Trial, not a Full trial"}
ACTIVE_OVR = {"reason": "x" * 24, "granted_at": (NOW - timedelta(days=1)).isoformat(),
              "expires_at": (NOW + timedelta(days=29)).isoformat(), "allocation_cap_pct": 50.0}
EXPIRED_OVR = {**ACTIVE_OVR, "expires_at": (NOW - timedelta(days=1)).isoformat()}


# ---- pure policy ---------------------------------------------------------------

def _req(**over):
    base = dict(strategy="alpha", confirm="alpha LIVE", route="CLEAR", card={"card_id": "alpha-v1"}, live_ready=True,
                full_trial=FT_OK, canary_mismatch=False, symbols=["NVDA"], open_paper_lots=0, policy=POLICY, now=NOW)
    base.update(over)
    return base


def test_validate_request_order_and_codes():
    golive.validate_request(**_req())
    golive.validate_request(**_req(route="ADVISORY", card={"card_id": "a", "override": ACTIVE_OVR}))
    for change, code in [
        ({"confirm": "alpha"}, "confirm"), ({"confirm": "alpha live"}, "confirm"), ({"confirm": None}, "confirm"),
        ({"live_ready": False}, "not_configured"),
        ({"full_trial": FT_BAD}, "not_full"), ({"full_trial": None}, "no_run"),
        ({"canary_mismatch": True}, "canary"),
        ({"route": "BLOCKED"}, "blocked"),
        ({"route": "ADVISORY"}, "override_required"),
        ({"route": "ADVISORY", "card": {"card_id": "a", "override": EXPIRED_OVR}}, "override_expired"),
        ({"route": None}, "no_route"),
        ({"symbols": []}, "no_tickers"),
        ({"open_paper_lots": 2}, "flatten_paper_first"),
    ]:
        with pytest.raises(golive.GoLiveRefused) as e:
            golive.validate_request(**_req(**change))
        assert e.value.code == code, change
    # require_flat_paper=False lets open paper lots through
    golive.validate_request(**_req(open_paper_lots=2, policy={**POLICY, "require_flat_paper": False}))


def test_budget_and_allocation():
    assert golive.check_budget(allocation_usd="5000", policy=POLICY, others_total=20000.0) == 5000.0
    for alloc, others, code in [(None, 0, "allocation"), ("abc", 0, "allocation"), (0, 0, "allocation"), (-5, 0, "allocation"),
                                (5001, 20000, "budget"), (30000, 0, "budget")]:
        with pytest.raises(golive.GoLiveRefused) as e:
            golive.check_budget(allocation_usd=alloc, policy=POLICY, others_total=others)
        assert e.value.code == code
    cards = [{"card_id": "a", "mode": "live", "allocation_usd": 1000}, {"card_id": "b", "mode": "live", "allocation_usd": "abc"},
             {"card_id": "c", "mode": "paper", "allocation_usd": 9999}, {"card_id": "d", "mode": "live", "status": "disabled", "allocation_usd": 500}]
    assert golive.live_allocation_total(cards) == 1500.0          # Off live cards still count
    assert golive.live_allocation_total(cards, exclude_card_id="a") == 500.0


def test_policy_from_config_defaults_and_yaml():
    from tradelab.config import Config, PathsConfig, LiveConfig
    p = golive.policy_from_config(Config(paths=PathsConfig(**{k: "." for k in PathsConfig.model_fields})))
    assert p == POLICY
    assert golive.policy_from_config(LiveConfig(max_total_allocation_usd=100))["max_total_allocation_usd"] == 100.0
    assert golive.policy_from_config({"require_flat_paper": False})["require_flat_paper"] is False


def test_checks_view_lists_every_check_and_budget():
    v = golive.checks_view(strategy="alpha", route="ADVISORY", card={"override": EXPIRED_OVR}, live_ready=False, full_trial=FT_OK,
                           canary_mismatch=False, symbols=[], open_paper_lots=1, policy=POLICY, others_total=20000.0, now=NOW)
    keys = [c["key"] for c in v["checks"]]
    assert keys == ["keys", "full_trial", "canary", "route", "tickers", "flat_paper"]
    bad = {c["key"] for c in v["checks"] if not c["ok"]}
    assert bad == {"keys", "route", "tickers", "flat_paper"} and v["all_ok"] is False
    assert v["expected_confirm"] == "alpha LIVE" and v["budget"]["available"] == 5000.0 and v["override_cap_pct"] == 50.0


# ---- the routes --------------------------------------------------------------------

def _seed(tmp_path, monkeypatch, cards: dict):
    cards_path = tmp_path / "cards.json"; cards_path.write_text(json.dumps(cards))
    db = tmp_path / "hist.db"
    monkeypatch.setattr(handlers, "_db_path", lambda: db)
    monkeypatch.setattr(handlers, "_cards_path", lambda: cards_path)
    monkeypatch.setattr(handlers, "_live_policy", lambda: dict(POLICY))
    monkeypatch.chdir(tmp_path)
    return cards_path, db


CARD = {"card_id": "alpha-v1", "base_name": "alpha", "strategy": "alpha", "symbol": "PORTFOLIO", "timeframe": "1D",
        "status": "disabled", "mode": "paper", "source": "python", "verdict": "ROBUST", "promotion_route": "CLEAR",
        "scoring_run_id": "run-1", "allocation_usd": 2000, "secret": "s"}
GOOD = dict(route="CLEAR", full_trial=FT_OK, canary_mismatch=False, symbols=["NVDA", "AMD"], open_paper_lots=0,
            live_ready=True, thresholds_hash="t1", now=NOW)


def _post_live(card_id, body, deps):
    return handlers._go_live(card_id, body, deps=deps)


def test_go_live_arms_the_card_off_with_receipt_and_ledger_row(tmp_path, monkeypatch):
    cards_path, db = _seed(tmp_path, monkeypatch, {"alpha-v1": CARD})
    body, status = _post_live("alpha-v1", {"confirm": "alpha LIVE", "allocation_usd": 5000}, GOOD)
    assert status == 200, body
    card = json.loads(cards_path.read_text())["alpha-v1"]
    assert card["mode"] == "live" and card["status"] == "disabled" and card["allocation_usd"] == 5000.0
    assert card["live"]["route"] == "CLEAR" and card["live"]["thresholds_hash"] == "t1" and card["live"]["scoring_run_id"] == "run-1"
    row = sqlite3.connect(str(db)).execute(
        "SELECT id, action, live_allocation_usd, promotion_route, activated FROM verdict_ledger ORDER BY id DESC LIMIT 1").fetchone()
    assert row[1:] == ("go_live", 5000.0, "CLEAR", 0)
    assert card["live"]["ledger_row_id"] == row[0]          # the receipt names its ledger row
    assert handlers._verify_live_receipt(card) is True
    # a second go-live on the same card is refused
    body, status = _post_live("alpha-v1", {"confirm": "alpha LIVE", "allocation_usd": 5000}, GOOD)
    assert status == 422 and json.loads(body)["code"] == "already_live"


@pytest.mark.parametrize("payload, deps, code", [
    ({"confirm": "alpha", "allocation_usd": 5000}, {}, "confirm"),
    ({"confirm": "alpha LIVE", "allocation_usd": 5000}, {"live_ready": False}, "not_configured"),
    ({"confirm": "alpha LIVE", "allocation_usd": 5000}, {"full_trial": FT_BAD}, "not_full"),
    ({"confirm": "alpha LIVE", "allocation_usd": 5000}, {"canary_mismatch": True}, "canary"),
    ({"confirm": "alpha LIVE", "allocation_usd": 5000}, {"route": "BLOCKED"}, "blocked"),
    ({"confirm": "alpha LIVE", "allocation_usd": 5000}, {"route": "ADVISORY"}, "override_required"),
    ({"confirm": "alpha LIVE", "allocation_usd": 5000}, {"symbols": []}, "no_tickers"),
    ({"confirm": "alpha LIVE", "allocation_usd": 5000}, {"open_paper_lots": 3}, "flatten_paper_first"),
    ({"confirm": "alpha LIVE", "allocation_usd": 5000}, {"open_paper_lots": -1}, "paper_unverifiable"),   # unreachable / cut window
    ({"confirm": "alpha LIVE", "allocation_usd": 30000}, {}, "budget"),
    ({"confirm": "alpha LIVE"}, {}, "allocation"),
])
def test_go_live_refusals_leave_the_card_on_paper(tmp_path, monkeypatch, payload, deps, code):
    cards_path, db = _seed(tmp_path, monkeypatch, {"alpha-v1": CARD})
    body, status = _post_live("alpha-v1", payload, {**GOOD, **deps})
    assert status == 422 and json.loads(body)["code"] == code and json.loads(body)["gate"] == "live"
    card = json.loads(cards_path.read_text())["alpha-v1"]
    assert card["mode"] == "paper" and "live" not in card
    assert not db.exists() or sqlite3.connect(str(db)).execute("SELECT COUNT(*) FROM verdict_ledger").fetchone()[0] == 0


def test_advisory_with_active_override_may_go_live(tmp_path, monkeypatch):
    card = {**CARD, "promotion_route": "ADVISORY", "verdict": "INCONCLUSIVE", "override": ACTIVE_OVR}
    cards_path, db = _seed(tmp_path, monkeypatch, {"alpha-v1": card})
    body, status = _post_live("alpha-v1", {"confirm": "alpha LIVE", "allocation_usd": 4000}, {**GOOD, "route": "ADVISORY"})
    assert status == 200, body
    assert json.loads(cards_path.read_text())["alpha-v1"]["live"]["route"] == "ADVISORY"
    row = sqlite3.connect(str(db)).execute("SELECT override_used, allocation_cap_pct FROM verdict_ledger ORDER BY id DESC LIMIT 1").fetchone()
    assert row == (1, 50.0)
    # expired override → refused
    card2 = {**card, "card_id": "beta-v1", "override": EXPIRED_OVR}
    cards_path.write_text(json.dumps({"beta-v1": card2}))
    body, status = _post_live("beta-v1", {"confirm": "alpha LIVE", "allocation_usd": 4000}, {**GOOD, "route": "ADVISORY"})
    assert status == 422 and json.loads(body)["code"] == "override_expired"


def test_budget_sums_existing_live_cards(tmp_path, monkeypatch):
    other = {**CARD, "card_id": "gamma-v1", "strategy": "gamma", "mode": "live", "allocation_usd": 21000, "live": {"granted_at": "x"}}
    cards_path, db = _seed(tmp_path, monkeypatch, {"alpha-v1": CARD, "gamma-v1": other})
    body, status = _post_live("alpha-v1", {"confirm": "alpha LIVE", "allocation_usd": 4001}, GOOD)
    assert status == 422 and json.loads(body)["code"] == "budget"
    body, status = _post_live("alpha-v1", {"confirm": "alpha LIVE", "allocation_usd": 4000}, GOOD)
    assert status == 200


def test_ledger_failure_is_fail_closed(tmp_path, monkeypatch):
    cards_path, db = _seed(tmp_path, monkeypatch, {"alpha-v1": CARD})

    def boom(**kw):
        raise RuntimeError("disk full")
    body, status = _post_live("alpha-v1", {"confirm": "alpha LIVE", "allocation_usd": 5000}, {**GOOD, "log_decision": boom})
    assert status == 503
    assert json.loads(cards_path.read_text())["alpha-v1"]["mode"] == "paper"


def test_enable_gate_for_live_cards_needs_verified_receipt_keys_and_current_evidence(monkeypatch):
    monkeypatch.setattr(handlers, "_live_ready", lambda: True)
    monkeypatch.setattr(handlers, "_verify_live_receipt", lambda card: True)
    monkeypatch.setattr(handlers, "_live_evidence_stale", lambda card: None)
    armed = {**CARD, "mode": "live", "live": {"granted_at": "x"}}
    assert handlers._enable_gate(armed, {"status": "enabled"}) is None
    hand_edited = {**CARD, "mode": "live"}
    assert "receipt" in handlers._enable_gate(hand_edited, {"status": "enabled"})
    monkeypatch.setattr(handlers, "_verify_live_receipt", lambda card: False)
    assert "does not match the audit ledger" in handlers._enable_gate(armed, {"status": "enabled"})
    monkeypatch.setattr(handlers, "_verify_live_receipt", lambda card: True)
    monkeypatch.setattr(handlers, "_live_evidence_stale", lambda card: "strategy code changed since the Full trial")
    assert "code changed" in handlers._enable_gate(armed, {"status": "enabled"})
    monkeypatch.setattr(handlers, "_live_evidence_stale", lambda card: None)
    monkeypatch.setattr(handlers, "_live_ready", lambda: False)
    assert "live keys" in handlers._enable_gate(armed, {"status": "enabled"})
    # paper cards are untouched by the live checks
    assert handlers._enable_gate(CARD, {"status": "enabled"}) is None


def test_forged_receipt_does_not_verify(tmp_path, monkeypatch):
    """A hand-edited cards.json cannot arm real money: the receipt must name a
    ledger row that says the same strategy, run and allocation."""
    from tradelab.audit.verdict_ledger import log_decision, get_row
    cards_path, db = _seed(tmp_path, monkeypatch, {"alpha-v1": CARD})
    forged = {**CARD, "mode": "live", "live": {"granted_at": "x", "scoring_run_id": "run-1", "allocation_usd": 5000, "ledger_row_id": 1}}
    assert handlers._verify_live_receipt(forged) is False            # no ledger at all
    rid = log_decision(db_path=db, strategy_name="alpha", scoring_run_id="run-1", path="python", verdict="ROBUST",
                       promotion_route="CLEAR", action="go_live", live_allocation_usd=5000, card_id="alpha-v1")
    good = {**forged, "live": {**forged["live"], "ledger_row_id": rid}}
    assert handlers._verify_live_receipt(good) is True
    for bad in ({"allocation_usd": 50000}, {"scoring_run_id": "run-2"}, {"ledger_row_id": rid + 1}):
        assert handlers._verify_live_receipt({**good, "live": {**good["live"], **bad}}) is False
    assert handlers._verify_live_receipt({**good, "strategy": "beta"}) is False
    # another card cannot adopt this card's row
    assert handlers._verify_live_receipt({**good, "card_id": "alpha-v2"}) is False
    other = log_decision(db_path=db, strategy_name="alpha", scoring_run_id="run-1", path="python", verdict="ROBUST",
                         promotion_route="CLEAR", action="accept", live_allocation_usd=5000, card_id="alpha-v1")
    assert handlers._verify_live_receipt({**good, "live": {**good["live"], "ledger_row_id": other}}) is False
    assert get_row(10**9, db_path=db) is None
    # a leave_live newer than the receipt supersedes it: the copied receipt no longer verifies
    log_decision(db_path=db, strategy_name="alpha", scoring_run_id="run-1", path="python", verdict="ROBUST",
                 promotion_route="CLEAR", action="leave_live", live_allocation_usd=5000, card_id="alpha-v1")
    assert handlers._verify_live_receipt(good) is False


def test_mode_and_live_are_not_patchable_and_allocation_rechecks_budget_and_is_ledgered(tmp_path, monkeypatch):
    armed = {**CARD, "mode": "live", "live": {"granted_at": "x", "scoring_run_id": "run-1", "allocation_usd": 5000, "ledger_row_id": 1}, "allocation_usd": 5000}
    other = {**CARD, "card_id": "gamma-v1", "mode": "live", "live": {"granted_at": "x"}, "allocation_usd": 19000}
    cards_path, db = _seed(tmp_path, monkeypatch, {"alpha-v1": armed, "gamma-v1": other})
    for field in ("mode", "live"):
        body, status = handlers.handle_patch_with_status("/tradelab/cards/alpha-v1", json.dumps({field: "paper"}).encode())
        assert status == 400 and "unknown field" in json.loads(body)["error"]
    body, status = handlers.handle_patch_with_status("/tradelab/cards/alpha-v1", json.dumps({"allocation_usd": 6001}).encode())
    assert status == 422 and json.loads(body)["code"] == "budget"
    body, status = handlers.handle_patch_with_status("/tradelab/cards/alpha-v1", json.dumps({"allocation_usd": 6000}).encode())
    assert status == 200
    card = json.loads(cards_path.read_text())["alpha-v1"]
    assert card["allocation_usd"] == 6000 and card["live"]["allocation_usd"] == 6000.0
    row = sqlite3.connect(str(db)).execute("SELECT id, action, live_allocation_usd FROM verdict_ledger ORDER BY id DESC LIMIT 1").fetchone()
    assert row[1:] == ("live_allocation", 6000.0) and card["live"]["ledger_row_id"] == row[0]
    assert handlers._verify_live_receipt(card) is True          # the moved receipt still verifies
    # a live card without a receipt cannot have its allocation changed at all
    cards_path.write_text(json.dumps({"beta-v1": {**CARD, "card_id": "beta-v1", "mode": "live"}}))
    body, status = handlers.handle_patch_with_status("/tradelab/cards/beta-v1", json.dumps({"allocation_usd": 100}).encode())
    assert status == 422


def test_leave_live_needs_a_flat_live_account_and_keeps_history(tmp_path, monkeypatch):
    armed = {**CARD, "mode": "live", "status": "enabled", "live": {"granted_at": "x", "allocation_usd": 5000}}
    cards_path, db = _seed(tmp_path, monkeypatch, {"alpha-v1": armed})
    body, status = handlers._leave_live("alpha-v1", {}, deps={"open_live_lots": 2})
    assert status == 422 and json.loads(body)["code"] == "flatten_live_first"
    body, status = handlers._leave_live("alpha-v1", {}, deps={"open_live_lots": -1})
    assert status == 422 and json.loads(body)["code"] == "flatten_live_first"
    body, status = handlers._leave_live("alpha-v1", {}, deps={"open_live_lots": 0})
    assert status == 200, body
    card = json.loads(cards_path.read_text())["alpha-v1"]
    assert card["mode"] == "paper" and card["status"] == "disabled" and card["live"] is None
    assert card["live_history"][0]["allocation_usd"] == 5000 and "left_at" in card["live_history"][0]
    assert "ledger_row_id" not in card["live_history"][0]
    row = sqlite3.connect(str(db)).execute("SELECT action FROM verdict_ledger ORDER BY id DESC LIMIT 1").fetchone()
    assert row == ("leave_live",)
    body, status = handlers._leave_live("alpha-v1", {}, deps={"open_live_lots": 0})
    assert status == 422 and json.loads(body)["code"] == "not_live"


def test_board_emits_live_state_for_live_cards():
    from tradelab.web import board
    state, action = board.derive_state(latest_run={"run_id": "r", "verdict": "ROBUST", "timestamp_utc": "2026-09-01T00:00:00"},
                                       route="CLEAR", blockers=[], card={**CARD, "mode": "live", "status": "enabled"}, retired=None)
    assert state == "live" and action["kind"] == "open_tab" and "LIVE" in action["label"]
    state, action = board.derive_state(latest_run={"run_id": "r", "verdict": "ROBUST", "timestamp_utc": "2026-09-01T00:00:00"},
                                       route="CLEAR", blockers=[], card={**CARD, "mode": "live"}, retired=None)
    assert state == "live" and "Off" in action["label"]
    state, _ = board.derive_state(latest_run={"run_id": "r", "verdict": "ROBUST", "timestamp_utc": "2026-09-01T00:00:00"},
                                  route="CLEAR", blockers=[], card=CARD, retired=None)
    assert state == "accepted"


def test_flatten_and_activity_use_the_cards_account(tmp_path, monkeypatch):
    """A live card's flatten/activity go to the live client; a paper card's to paper."""
    from tradelab.live import alpaca_client as ac
    seen = []
    monkeypatch.setattr(ac, "list_closed_orders", lambda days=90, account="paper": (seen.append(("orders", account)), [])[1])
    monkeypatch.setattr(ac, "list_positions_detail", lambda account="paper": (seen.append(("pos", account)), [])[1])
    monkeypatch.setattr(handlers, "_card_symbols", lambda card: ["NVDA"])
    armed = {**CARD, "mode": "live", "live": {"granted_at": "x"}}
    cards_path, db = _seed(tmp_path, monkeypatch, {"alpha-v1": armed, "beta-v1": {**CARD, "card_id": "beta-v1"}})
    body, status = handlers._flatten_card("alpha-v1", {"dry_run": True})
    assert status == 200 and json.loads(body)["data"]["account"] == "live"
    body, status = handlers.handle_get_with_status("/tradelab/cards/beta-v1/activity?days=30")
    assert status == 200 and json.loads(body)["data"]["account"] == "paper"
    assert ("orders", "live") in seen and ("orders", "paper") in seen


def test_lot_counts_refuse_to_guess_when_the_order_window_is_cut(monkeypatch):
    from tradelab.live import alpaca_client as ac, card_activity
    many = [{"id": str(i), "client_order_id": f"zzz-2026-01-01-buy", "symbol": "X", "side": "buy", "qty": 1, "filled_qty": 1,
             "filled_avg_price": 1.0, "filled_at": "2026-01-01T00:00:00Z", "status": "filled"} for i in range(card_activity.ORDERS_PAGE_LIMIT)]
    monkeypatch.setattr(ac, "list_closed_orders", lambda days=90, account="paper": many)
    monkeypatch.setattr(ac, "list_positions_detail", lambda account="paper": [])
    assert handlers._open_paper_lots({"card_id": "alpha-v1"}) == -1
    assert handlers._open_live_lots({"card_id": "alpha-v1"}) == -1
    monkeypatch.setattr(ac, "list_closed_orders", lambda days=90, account="paper": many[:10])
    assert handlers._open_paper_lots({"card_id": "alpha-v1"}) == 0
    monkeypatch.setattr(ac, "list_closed_orders", lambda days=90, account="paper": (_ for _ in ()).throw(RuntimeError("down")))
    assert handlers._open_live_lots({"card_id": "alpha-v1"}) == -1


def test_paper_client_refuses_a_non_paper_config(tmp_path, monkeypatch):
    from tradelab.live import alpaca_client as ac
    cfg = tmp_path / "alpaca_config.json"
    cfg.write_text(json.dumps({"alpaca": {"api_key": "k", "secret_key": "s", "paper_trading": False}}))
    monkeypatch.setattr(ac, "CONFIG_PATH", cfg)
    ac._clients.pop("paper", None)
    with pytest.raises(ac.PaperMisconfigured):
        ac.get_client("paper")
    cfg.write_text(json.dumps({"alpaca": {"api_key": "k", "secret_key": "s"}}))
    with pytest.raises(ac.PaperMisconfigured):
        ac.get_client("paper")
    ac._clients.pop("paper", None)


def test_leave_live_then_replaying_the_old_receipt_does_not_rearm(tmp_path, monkeypatch):
    cards_path, db = _seed(tmp_path, monkeypatch, {"alpha-v1": CARD})
    body, status = _post_live("alpha-v1", {"confirm": "alpha LIVE", "allocation_usd": 5000}, GOOD)
    assert status == 200
    armed = json.loads(cards_path.read_text())["alpha-v1"]
    assert handlers._verify_live_receipt(armed) is True
    body, status = handlers._leave_live("alpha-v1", {}, deps={"open_live_lots": 0})
    assert status == 200
    # hand-edit: copy the old receipt back and flip the mode
    replay = {**json.loads(cards_path.read_text())["alpha-v1"], "mode": "live", "live": armed["live"]}
    assert handlers._verify_live_receipt(replay) is False
    monkeypatch.setattr(handlers, "_live_ready", lambda: True)
    assert "does not match the audit ledger" in handlers._enable_gate(replay, {"status": "enabled"})


def test_renew_on_a_live_card_requires_a_verified_receipt(tmp_path, monkeypatch):
    """A bad receipt cannot be laundered into a real live_rearm row."""
    bad = {**CARD, "mode": "live", "promotion_route": "ADVISORY", "override": ACTIVE_OVR,
           "live": {"granted_at": "x", "scoring_run_id": "run-1", "allocation_usd": 5000, "ledger_row_id": 7}}
    cards_path, db = _seed(tmp_path, monkeypatch, {"alpha-v1": bad})
    body, status = handlers._renew_override("alpha-v1", {"confirm": "alpha", "reason": "x" * 30, "confirm_live": "alpha LIVE"})
    assert status == 422 and json.loads(body)["code"] == "receipt_unverified"
