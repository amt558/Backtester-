"""S6 (2026-09-03) — the override: ADVISORY only, typed name, written reason,
expiry, capped size, budget, ledger receipt; BLOCKED never."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from tradelab import override as ov
from tradelab.live.cards import CardRegistry
from tradelab.web import handlers

NOW = datetime(2026, 9, 3, 14, 0, tzinfo=timezone.utc)
POLICY = {"expiry_days": 30, "cap_pct": 50.0, "budget": 2, "reason_min_chars": 20}
GOOD_REASON = "Edge is regime-specific but hold-out PF is strong; paper it small."


# ---- pure policy ---------------------------------------------------------------

def test_validate_request_rules():
    ok = dict(strategy="alpha", confirm="alpha", reason=GOOD_REASON, route="ADVISORY", policy=POLICY, active_count=0)
    ov.validate_request(**ok)
    for change, code in [({"route": "BLOCKED"}, "blocked"), ({"route": "CLEAR"}, "not_needed"), ({"route": None}, "no_route"),
                         ({"confirm": "Alpha"}, "confirm"), ({"confirm": ""}, "confirm"),
                         ({"reason": "too short"}, "reason"), ({"active_count": 2}, "budget")]:
        with pytest.raises(ov.OverrideRefused) as e:
            ov.validate_request(**{**ok, **change})
        assert e.value.code == code, change


def test_build_record_and_receipt():
    rec = ov.build_record(reason="  " + GOOD_REASON + "  ", now=NOW, policy=POLICY, scoring_run_id="r1", thresholds_hash="t1")
    assert rec["reason"] == GOOD_REASON and rec["expires_at"].startswith("2026-10-03") and rec["allocation_cap_pct"] == 50.0
    card = {"card_id": "a-v1", "override": rec}
    r = ov.receipt(card, NOW)
    assert r["active"] is True and r["expired"] is False and r["days_left"] == 30
    r = ov.receipt(card, NOW + timedelta(days=31))
    assert r["active"] is False and r["expired"] is True and r["days_left"] == 0
    assert ov.receipt({"card_id": "b"}, NOW) is None


def test_policy_from_config_defaults_and_yaml():
    from tradelab.config import Config, PathsConfig, PromotionConfig
    p = ov.policy_from_config(Config(paths=PathsConfig(**{k: "." for k in PathsConfig.model_fields})))
    assert p == POLICY
    assert ov.policy_from_config(PromotionConfig(override_budget=1, override_expiry_days=7))["budget"] == 1
    assert ov.policy_from_config({"override_allocation_cap_pct": 25})["cap_pct"] == 25.0


def test_active_overrides_counts_only_unexpired_and_can_exclude_self():
    cards = [{"card_id": "a", "override": {"expires_at": (NOW + timedelta(days=1)).isoformat()}},
             {"card_id": "b", "override": {"expires_at": (NOW - timedelta(days=1)).isoformat()}},
             {"card_id": "c", "override": {"expires_at": (NOW + timedelta(days=9)).isoformat()}},
             {"card_id": "d"}]
    assert [c["card_id"] for c in ov.active_overrides(cards, NOW)] == ["a", "c"]
    assert [c["card_id"] for c in ov.active_overrides(cards, NOW, exclude_card_id="a")] == ["c"]


# ---- accept with override (handler) -------------------------------------------------

def _seed(tmp_path, monkeypatch, write_backtest_result, *, verdict="INCONCLUSIVE", dsr=0.4, net_pnl=240.0,
          tier="full", strategy="alpha", existing_cards=None):
    from tradelab.audit.history import record_run
    reports = tmp_path / "reports"; folder = reports / f"{strategy}_x"; folder.mkdir(parents=True, exist_ok=True)
    write_backtest_result(folder, net_pnl=net_pnl, strategy=strategy)
    db = tmp_path / "hist.db"
    run_id = record_run(strategy, verdict=verdict, dsr_probability=dsr, tier=tier, code_hash="c1", thresholds_hash="t1",
                        report_card_html_path=str(folder / "dashboard.html"), db_path=db)
    cards = tmp_path / "cards.json"
    if not cards.exists():
        cards.write_text(json.dumps(existing_cards or {}))
    monkeypatch.setattr(handlers, "_db_path", lambda: db)
    monkeypatch.setattr(handlers, "_cards_path", lambda: cards)
    monkeypatch.setattr(handlers, "_reports_root", lambda: reports)
    monkeypatch.setattr(handlers, "_current_hashes_for", lambda name: ("c1", "t1"))
    monkeypatch.setattr(handlers, "_canary_mismatch_now", lambda: False)
    monkeypatch.chdir(tmp_path)
    return run_id, folder, cards, db


def _accept(run_id, folder, strategy="alpha", override=None, **extra):
    body = {"base_name": strategy, "strategy": strategy, "symbol": "NVDA", "timeframe": "1D",
            "report_folder": str(folder), "scoring_run_id": run_id, "activate": False}
    if override is not None:
        body["override"] = override
    body.update(extra)
    return handlers.handle_post_with_status("/tradelab/strategies/accept", json.dumps(body).encode())


def test_advisory_without_override_is_still_refused(tmp_path, monkeypatch, write_backtest_result):
    run_id, folder, cards, db = _seed(tmp_path, monkeypatch, write_backtest_result)
    body, status = _accept(run_id, folder)
    assert status == 422 and json.loads(body).get("state") == "ADVISORY"
    # the old checkbox no longer works either
    body, status = _accept(run_id, folder, confirm_non_robust=True)
    assert status == 422 and json.loads(cards.read_text()) == {}


def test_override_grants_an_off_card_with_receipt_and_ledger_row(tmp_path, monkeypatch, write_backtest_result):
    run_id, folder, cards, db = _seed(tmp_path, monkeypatch, write_backtest_result)
    body, status = _accept(run_id, folder, override={"confirm": "alpha", "reason": GOOD_REASON})
    assert status == 200, body
    card = json.loads(cards.read_text())["alpha-v1"]
    assert card["status"] == "disabled" and card["promotion_route"] == "ADVISORY"
    ovr = card["override"]
    assert ovr["reason"] == GOOD_REASON and ovr["allocation_cap_pct"] == 50.0 and ovr["thresholds_hash"] == "t1"
    assert ovr["scoring_run_id"] == run_id
    exp = datetime.fromisoformat(ovr["expires_at"]); gr = datetime.fromisoformat(ovr["granted_at"])
    assert (exp - gr).days == 30
    row = sqlite3.connect(str(db)).execute(
        "SELECT override_used, override_reason, override_expires_at, allocation_cap_pct, thresholds_hash, promotion_route "
        "FROM verdict_ledger ORDER BY id DESC LIMIT 1").fetchone()
    assert row == (1, GOOD_REASON, ovr["expires_at"], 50.0, "t1", "ADVISORY")


@pytest.mark.parametrize("override, code", [
    ({"confirm": "Alpha", "reason": GOOD_REASON}, "confirm"),
    ({"confirm": "alpha", "reason": "nope"}, "reason"),
    ({"confirm": "alpha"}, "reason"),
])
def test_override_refusals(tmp_path, monkeypatch, write_backtest_result, override, code):
    run_id, folder, cards, db = _seed(tmp_path, monkeypatch, write_backtest_result)
    body, status = _accept(run_id, folder, override=override)
    assert status == 422 and json.loads(body)["code"] == code and json.loads(body)["gate"] == "override"
    assert json.loads(cards.read_text()) == {}


def test_override_never_applies_to_blocked_and_is_refused_on_clear(tmp_path, monkeypatch, write_backtest_result):
    run_id, folder, cards, db = _seed(tmp_path, monkeypatch, write_backtest_result, verdict="ROBUST", dsr=-0.5)
    body, status = _accept(run_id, folder, override={"confirm": "alpha", "reason": GOOD_REASON})
    assert status == 422 and json.loads(body)["code"] == "blocked"
    run_id2, folder2, cards2, db2 = _seed(tmp_path, monkeypatch, write_backtest_result, verdict="ROBUST", dsr=0.9, strategy="beta")
    body, status = _accept(run_id2, folder2, strategy="beta", override={"confirm": "beta", "reason": GOOD_REASON})
    assert status == 422 and json.loads(body)["code"] == "not_needed"
    assert json.loads(cards.read_text()) == {}


def test_override_needs_a_full_trial_and_clean_canaries(tmp_path, monkeypatch, write_backtest_result):
    run_id, folder, cards, db = _seed(tmp_path, monkeypatch, write_backtest_result, tier="trial")
    body, status = _accept(run_id, folder, override={"confirm": "alpha", "reason": GOOD_REASON})
    assert status == 422 and json.loads(body)["gate"] == "full_trial" and json.loads(body)["code"] == "not_full"
    run_id, folder, cards, db = _seed(tmp_path, monkeypatch, write_backtest_result)
    monkeypatch.setattr(handlers, "_canary_mismatch_now", lambda: True)
    body, status = _accept(run_id, folder, override={"confirm": "alpha", "reason": GOOD_REASON})
    assert status == 422 and json.loads(body)["code"] == "canary_mismatch"


def test_override_budget_of_two(tmp_path, monkeypatch, write_backtest_result):
    live = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()
    existing = {"x-v1": {"card_id": "x-v1", "strategy": "x", "override": {"expires_at": live}},
                "y-v1": {"card_id": "y-v1", "strategy": "y", "override": {"expires_at": live}}}
    run_id, folder, cards, db = _seed(tmp_path, monkeypatch, write_backtest_result, existing_cards=existing)
    body, status = _accept(run_id, folder, override={"confirm": "alpha", "reason": GOOD_REASON})
    assert status == 422 and json.loads(body)["code"] == "budget"
    # an expired one frees the budget
    data = json.loads(cards.read_text()); data["y-v1"]["override"]["expires_at"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    cards.write_text(json.dumps(data))
    body, status = _accept(run_id, folder, override={"confirm": "alpha", "reason": GOOD_REASON})
    assert status == 200, body


def test_override_cannot_be_patched_onto_a_card(tmp_path, monkeypatch):
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps({"a-v1": {"card_id": "a-v1", "status": "disabled", "promotion_route": "ADVISORY"}}))
    monkeypatch.setattr(handlers, "_cards_path", lambda: cards)
    body, status = handlers.handle_patch_with_status("/tradelab/cards/a-v1", json.dumps({"override": {"expires_at": "2099-01-01"}}).encode())
    assert status == 400


# ---- enable gate + renewal ---------------------------------------------------------

def _card_file(tmp_path, monkeypatch, card):
    cards = tmp_path / "cards.json"; cards.write_text(json.dumps({card["card_id"]: card}))
    monkeypatch.setattr(handlers, "_cards_path", lambda: cards)
    return cards


def test_enable_gate_requires_an_active_override_for_advisory(tmp_path, monkeypatch):
    live = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    dead = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    base = {"card_id": "a-v1", "status": "disabled", "promotion_route": "ADVISORY", "allocation_usd": 100}
    assert "needs an override" in handlers._enable_gate(base, {"status": "enabled"})
    assert "expired" in handlers._enable_gate({**base, "override": {"expires_at": dead}}, {"status": "enabled"})
    assert handlers._enable_gate({**base, "override": {"expires_at": live}}, {"status": "enabled"}) is None


def test_renew_is_a_fresh_override_with_a_fresh_reason(tmp_path, monkeypatch, write_backtest_result):
    run_id, folder, cards, db = _seed(tmp_path, monkeypatch, write_backtest_result)
    _accept(run_id, folder, override={"confirm": "alpha", "reason": GOOD_REASON})
    # age it: expired + stamped Off by the daemon
    data = json.loads(cards.read_text())
    data["alpha-v1"]["override"]["expires_at"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    data["alpha-v1"]["override_expired_at"] = datetime.now(timezone.utc).isoformat()
    cards.write_text(json.dumps(data))
    # renewal needs NEW evidence: without a Full trial newer than the grant it is refused
    body, status = handlers.handle_post_with_status("/tradelab/cards/alpha-v1/override",
                                                    json.dumps({"confirm": "alpha", "reason": "Renewing: Rung-3 progress is 12/30 trades, PF holding at 1.4."}).encode())
    assert status == 422 and json.loads(body)["code"] == "no_newer_trial"
    from tradelab.audit.history import record_run
    new_run = record_run("alpha", verdict="INCONCLUSIVE", dsr_probability=0.45, tier="full", code_hash="c1", thresholds_hash="t1",
                         report_card_html_path=str(folder / "dashboard.html"), db_path=db)
    body, status = handlers.handle_post_with_status("/tradelab/cards/alpha-v1/override",
                                                    json.dumps({"confirm": "alpha", "reason": "old reason"}).encode())
    assert status == 422 and json.loads(body)["code"] == "reason"
    body, status = handlers.handle_post_with_status("/tradelab/cards/alpha-v1/override",
                                                    json.dumps({"confirm": "alpha", "reason": "Renewing: Rung-3 progress is 12/30 trades, PF holding at 1.4."}).encode())
    assert status == 200, body
    card = json.loads(cards.read_text())["alpha-v1"]
    assert card["override"]["reason"].startswith("Renewing") and card.get("override_expired_at") is None
    assert card["scoring_run_id"] == new_run and card["override"]["scoring_run_id"] == new_run
    assert ov.is_active(card, datetime.now(timezone.utc))
    n = sqlite3.connect(str(db)).execute("SELECT COUNT(*) FROM verdict_ledger WHERE override_used = 1").fetchone()[0]
    assert n == 2
    # a CLEAR card has nothing to renew
    data = json.loads(cards.read_text()); data["alpha-v1"]["promotion_route"] = "CLEAR"; cards.write_text(json.dumps(data))
    assert handlers.handle_post_with_status("/tradelab/cards/alpha-v1/override",
                                            json.dumps({"confirm": "alpha", "reason": GOOD_REASON}).encode())[1] == 422


def test_ledger_migration_adds_columns_to_an_old_db(tmp_path):
    db = tmp_path / "old.db"
    conn = sqlite3.connect(str(db))
    conn.execute("""CREATE TABLE verdict_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
        scoring_run_id TEXT, strategy_name TEXT NOT NULL, path TEXT NOT NULL, verdict TEXT, promotion_route TEXT NOT NULL,
        blockers_json TEXT NOT NULL DEFAULT '[]', override_used INTEGER NOT NULL DEFAULT 0, activated INTEGER NOT NULL DEFAULT 0)""")
    conn.execute("INSERT INTO verdict_ledger (created_at, strategy_name, path, promotion_route) VALUES ('t','a','python','CLEAR')")
    conn.commit(); conn.close()
    from tradelab.audit.verdict_ledger import log_decision
    log_decision(strategy_name="a", scoring_run_id="r", path="python", verdict="INCONCLUSIVE", promotion_route="ADVISORY",
                 override_used=True, override_reason="why", override_expires_at="2026-10-03T00:00:00+00:00",
                 allocation_cap_pct=50.0, thresholds_hash="t", db_path=db)
    rows = sqlite3.connect(str(db)).execute("SELECT override_reason, allocation_cap_pct FROM verdict_ledger ORDER BY id").fetchall()
    assert rows == [(None, None), ("why", 50.0)]


# ---- specialist notes ---------------------------------------------------------------

def test_cap_is_clamped_and_missing_cap_sizes_zero():
    live = (NOW + timedelta(days=1)).isoformat()
    assert ov.effective_allocation({"allocation_usd": 1000, "override": {"expires_at": live, "allocation_cap_pct": 500}}, NOW) == 1000.0
    assert ov.effective_allocation({"allocation_usd": 1000, "override": {"expires_at": live}}, NOW) == 0.0
    assert ov.effective_allocation({"allocation_usd": 1000, "override": {"expires_at": live, "allocation_cap_pct": -5}}, NOW) == 0.0


def test_grant_is_refused_when_the_ledger_cannot_be_written(tmp_path, monkeypatch, write_backtest_result):
    """A receipt with no audit row is not a receipt: ledger first, fail closed."""
    run_id, folder, cards, db = _seed(tmp_path, monkeypatch, write_backtest_result)
    import tradelab.audit.verdict_ledger as vl
    monkeypatch.setattr(vl, "log_decision", lambda **kw: (_ for _ in ()).throw(sqlite3.OperationalError("locked")))
    body, status = _accept(run_id, folder, override={"confirm": "alpha", "reason": GOOD_REASON})
    assert status == 503 and "ledger" in json.loads(body)["error"]
    assert json.loads(cards.read_text()) == {}


def test_grant_with_activate_true_is_refused(tmp_path, monkeypatch, write_backtest_result):
    run_id, folder, cards, db = _seed(tmp_path, monkeypatch, write_backtest_result)
    body, status = _accept(run_id, folder, override={"confirm": "alpha", "reason": GOOD_REASON}, activate=True)
    assert status == 422 and json.loads(cards.read_text()) == {}


def test_expired_but_enabled_card_reads_as_halted_on_the_board():
    from tradelab.web import board
    dead = (NOW - timedelta(days=1)).isoformat()
    cards = {"a-v1": {"card_id": "a-v1", "strategy": "alpha", "version": 1, "status": "enabled",
                      "promotion_route": "ADVISORY", "override": {"expires_at": dead, "reason": "r", "allocation_cap_pct": 50}}}
    b = board.build_board(registered=["alpha"], latest_runs={}, route_for_run=lambda r: ("ADVISORY", []), cards=cards,
                          retired=[], jobs=[], symbols_for=lambda n: [], now=NOW)
    r = b["rows"][0]
    assert r["effective_status"] == "halted" and r["override"]["expired"] is True
    assert "halted" in r["next_action"]["label"]


def test_renew_recomputes_the_route_from_the_new_run(tmp_path, monkeypatch, write_backtest_result):
    """A newer Full trial that now routes BLOCKED cannot renew an override."""
    run_id, folder, cards, db = _seed(tmp_path, monkeypatch, write_backtest_result)
    _accept(run_id, folder, override={"confirm": "alpha", "reason": GOOD_REASON})
    from tradelab.audit.history import record_run
    record_run("alpha", verdict="INCONCLUSIVE", dsr_probability=-0.4, tier="full", code_hash="c1", thresholds_hash="t1",
               report_card_html_path=str(folder / "dashboard.html"), db_path=db)
    body, status = handlers.handle_post_with_status("/tradelab/cards/alpha-v1/override",
                                                    json.dumps({"confirm": "alpha", "reason": GOOD_REASON}).encode())
    assert status == 422 and json.loads(body)["code"] == "blocked"


def test_s9_renewing_a_live_cards_override_needs_the_live_confirmation_and_rearms(tmp_path, monkeypatch, write_backtest_result):
    run_id, folder, cards, db = _seed(tmp_path, monkeypatch, write_backtest_result)
    _accept(run_id, folder, override={"confirm": "alpha", "reason": GOOD_REASON})
    from tradelab.audit.verdict_ledger import log_decision
    rid = log_decision(db_path=db, strategy_name="alpha", scoring_run_id=run_id, path="python", verdict="INCONCLUSIVE",
                       promotion_route="ADVISORY", action="go_live", live_allocation_usd=3000, card_id="alpha-v1")
    data = json.loads(cards.read_text())
    data["alpha-v1"].update({"mode": "live", "allocation_usd": 3000,
                             "live": {"granted_at": "x", "scoring_run_id": run_id, "allocation_usd": 3000, "ledger_row_id": rid}})
    cards.write_text(json.dumps(data))
    from tradelab.audit.history import record_run
    new_run = record_run("alpha", verdict="INCONCLUSIVE", dsr_probability=0.45, tier="full", code_hash="c1", thresholds_hash="t1",
                         report_card_html_path=str(folder / "dashboard.html"), db_path=db)
    reason = "Renewing on live: paper PF held at 1.4 over 30 days."
    body, status = handlers.handle_post_with_status("/tradelab/cards/alpha-v1/override",
                                                    json.dumps({"confirm": "alpha", "reason": reason}).encode())
    assert status == 422 and json.loads(body)["code"] == "live_confirm"
    body, status = handlers.handle_post_with_status("/tradelab/cards/alpha-v1/override",
                                                    json.dumps({"confirm": "alpha", "reason": reason, "confirm_live": "alpha LIVE"}).encode())
    assert status == 200, body
    card = json.loads(cards.read_text())["alpha-v1"]
    assert card["mode"] == "live" and card["live"]["scoring_run_id"] == new_run
    row = sqlite3.connect(str(db)).execute("SELECT id, action, scoring_run_id FROM verdict_ledger ORDER BY id DESC LIMIT 1").fetchone()
    assert row[1:] == ("live_rearm", new_run) and card["live"]["ledger_row_id"] == row[0]
    assert handlers._verify_live_receipt(card) is True
