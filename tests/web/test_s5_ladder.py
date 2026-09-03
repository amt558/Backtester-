"""S5 (2026-09-03) — the test ladder: named rungs, the Full-trial accept gate,
and a presentation score over the verdict's signals."""
from __future__ import annotations

import json

import pytest

from tradelab import ladder
from tradelab.web import board, handlers


# ---- rungs and hashes -----------------------------------------------------------

def test_tier_for_flags():
    assert ladder.tier_for_flags(robustness=False, full=False, validation_deep=False) == "basic"
    assert ladder.tier_for_flags(robustness=True, full=False, validation_deep=False) == "trial"
    assert ladder.tier_for_flags(robustness=False, full=True, validation_deep=False) == "trial"
    assert ladder.tier_for_flags(robustness=False, full=True, validation_deep=True) == "full"
    assert ladder.COMMAND_TIER["run --full --validation-deep"] == "full"


def test_code_hash_tracks_the_source_file(tmp_path, monkeypatch):
    src = tmp_path / "mystrat.py"
    src.write_text("class S:\n    symbols = ['NVDA']\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    import importlib
    mod = importlib.import_module("mystrat")
    h1 = ladder.code_hash_for_class(mod.S)
    assert h1 and len(h1) == 64
    src.write_text("class S:\n    symbols = ['NVDA', 'AAPL']\n")
    assert ladder.code_hash_for_class(mod.S) != h1     # same class object, edited file
    assert ladder.code_hash_for_class(int) is None      # builtins have no source file


def test_thresholds_hash_is_canonical_and_sensitive():
    from tradelab.config import RobustnessThresholds, RobustnessConfig
    a = ladder.thresholds_hash(RobustnessThresholds())
    b = ladder.thresholds_hash(RobustnessThresholds().model_dump())
    c = ladder.thresholds_hash({**RobustnessThresholds().model_dump(), "pf_robust": 1.6})
    assert a == b and a != c and len(a) == 64
    # Specialist S5 #4: the WHOLE robustness config is hashed — knobs outside
    # RobustnessThresholds (shuffles, hold-out window…) change the verdict too.
    base = RobustnessConfig()
    h0 = ladder.thresholds_hash(base)
    assert ladder.thresholds_hash(base.model_copy(update={"monte_carlo_shuffles": base.monte_carlo_shuffles + 1})) != h0
    assert ladder.thresholds_hash(base.model_copy(update={"thresholds": RobustnessThresholds(pf_robust=9.9)})) != h0


# ---- the gate ----------------------------------------------------------------

FULL = {"tier": "full", "code_hash": "c1", "thresholds_hash": "t1"}


def test_full_trial_status_matrix():
    ok = ladder.full_trial_status(FULL, current_code_hash="c1", current_thresholds_hash="t1")
    assert ok == {"ok": True, "code": None, "reason": None}
    assert ladder.full_trial_status(None, current_code_hash="c1", current_thresholds_hash="t1")["code"] == "no_run"
    assert ladder.full_trial_status({**FULL, "tier": "trial"}, current_code_hash="c1", current_thresholds_hash="t1")["code"] == "not_full"
    assert ladder.full_trial_status({**FULL, "tier": None}, current_code_hash="c1", current_thresholds_hash="t1")["code"] == "not_full"
    assert ladder.full_trial_status({"tier": "full"}, current_code_hash="c1", current_thresholds_hash="t1")["code"] == "unrecorded"
    r = ladder.full_trial_status(FULL, current_code_hash="c2", current_thresholds_hash="t1")
    assert r["code"] == "code_changed" and "strategy file changed" in r["reason"]
    r = ladder.full_trial_status(FULL, current_code_hash="c1", current_thresholds_hash="t2")
    assert r["code"] == "thresholds_changed"
    r = ladder.full_trial_status(FULL, current_code_hash="c1", current_thresholds_hash="t1", canary_mismatch=True)
    assert r["code"] == "canary_mismatch"


def test_gate_is_fail_closed_when_current_hashes_unknown():
    """Specialist S5 #3: an unknown CURRENT hash (strategy file gone, config
    unloadable) must refuse, not skip the comparison."""
    r = ladder.full_trial_status(FULL, current_code_hash=None, current_thresholds_hash="t1")
    assert r["ok"] is False and r["code"] == "unverifiable"
    r = ladder.full_trial_status(FULL, current_code_hash="c1", current_thresholds_hash=None)
    assert r["ok"] is False and r["code"] == "unverifiable"
    assert ladder.full_trial_status({"tier": "full"}, current_code_hash=None, current_thresholds_hash=None)["code"] == "unrecorded"


# ---- the score -----------------------------------------------------------------

def _sig(*outcomes, hard=False):
    s = [{"name": f"s{i}", "outcome": o, "reason": ""} for i, o in enumerate(outcomes)]
    if hard:
        s.append({"name": "regime_spread_hard", "outcome": "fragile", "reason": "hard"})
    return s


def test_score_ranks_two_advisory_strategies_differently():
    a = ladder.score_from_signals(_sig("robust", "robust", "inconclusive", "inconclusive"))   # 0.75
    b = ladder.score_from_signals(_sig("robust", "inconclusive", "inconclusive", "inconclusive"))  # 0.625
    assert a > b
    assert ladder.score_from_signals(_sig("robust", "robust", "robust")) == 1.0
    assert ladder.score_from_signals(_sig("fragile", "fragile")) == 0.0
    assert ladder.score_from_signals([]) is None


def test_score_hard_override_caps_at_quarter():
    assert ladder.score_from_signals(_sig("robust", "robust", "robust", hard=True)) == 0.25
    assert ladder.score_from_signals(_sig("fragile", "fragile", hard=True)) == 0.0


def test_split_signals_separates_gating_from_read_anyway():
    out = ladder.split_signals(_sig("robust", "fragile", hard=True), {"trade_efficiency": 0.4321},
                               [{"name": "validation_suite", "outcome": "info", "reason": "present"}])
    assert [g["name"] for g in out["gating"]] == ["s0", "s1"]
    assert out["hard_override"][0]["name"] == "regime_spread_hard"
    assert {r["name"] for r in out["read_anyway"]} == {"trade_efficiency", "validation_suite"}
    assert out["read_anyway"][0]["reason"] == "0.432"


def test_rung_estimates_from_job_history_else_defaults():
    jobs = [{"command": "run --robustness", "status": "done", "started_at": "2026-09-03T00:00:00Z", "ended_at": "2026-09-03T00:01:10Z"},
            {"command": "run --robustness", "status": "done", "started_at": "2026-09-03T01:00:00Z", "ended_at": "2026-09-03T01:01:00Z"},
            {"command": "run --robustness", "status": "failed", "started_at": "2026-09-03T02:00:00Z", "ended_at": "2026-09-03T02:00:04Z"}]
    est = ladder.rung_estimates(jobs)
    assert est["trial"]["from_history"] and est["trial"]["seconds"] == 65.0 and est["trial"]["label"] == "~65 s"
    assert est["full"]["from_history"] is False and est["full"]["label"] == "~15–40 min"
    assert est["smoke"]["label"] == "seconds"


# ---- the board follows the gate -------------------------------------------------

def _run(verdict="ROBUST", **over):
    r = {"strategy_name": "alpha", "verdict": verdict, "dsr_probability": 0.8, "run_id": "r1",
         "timestamp_utc": "2026-09-01T00:00:00Z", "report_card_html_path": "reports/alpha/dashboard.html",
         "tier": "full", "code_hash": "c1", "thresholds_hash": "t1"}
    r.update(over)
    return r


def _board(run, ft, route="CLEAR"):
    return board.build_board(registered=["alpha"], latest_runs={"alpha": run}, route_for_run=lambda r: (route, []),
                             cards={}, retired=[], jobs=[], symbols_for=lambda n: [],
                             full_trial_for=lambda name, r: ft, signals_for=lambda r: {"score": 0.6, "gating": [{"name": "dsr", "outcome": "robust", "reason": ""}], "read_anyway": [], "hard_override": []})


def test_board_clear_with_full_trial_offers_accept():
    r = _board(_run(), {"ok": True, "code": None, "reason": None})["rows"][0]
    assert r["next_action"]["kind"] == "accept" and r["tier"] == "full" and r["score"] == 0.6
    assert r["signals"]["gating"][0]["name"] == "dsr"


def test_board_clear_without_full_trial_offers_full_trial_not_accept():
    r = _board(_run(tier="trial"), {"ok": False, "code": "not_full", "reason": "Full trial required"})["rows"][0]
    assert r["next_action"]["kind"] == "full_trial" and r["next_action"]["label"] == "Full trial"
    assert "Full trial required" in r["next_action"]["reason"]


def test_board_stale_full_trial_offers_full_trial_again():
    for code in ("code_changed", "thresholds_changed"):
        r = _board(_run(), {"ok": False, "code": code, "reason": "x changed"})["rows"][0]
        assert r["next_action"]["kind"] == "full_trial" and r["next_action"]["label"] == "Full trial again"


def test_board_canary_mismatch_disables_accept_without_asking_for_a_rerun():
    r = _board(_run(), {"ok": False, "code": "canary_mismatch", "reason": "engine integrity"})["rows"][0]
    assert r["next_action"]["kind"] == "accept" and r["next_action"]["enabled"] is False


def test_board_blocked_and_advisory_are_unchanged_by_the_ladder():
    r = _board(_run("FRAGILE"), {"ok": False, "code": "not_full", "reason": "x"}, route="BLOCKED")["rows"][0]
    assert r["next_action"]["kind"] == "retrial"
    r = _board(_run("INCONCLUSIVE"), {"ok": False, "code": "not_full", "reason": "x"}, route="ADVISORY")["rows"][0]
    assert r["next_action"]["kind"] == "accept_override" and r["next_action"]["enabled"] is False


def test_board_without_gate_callable_fails_closed():
    b = board.build_board(registered=["alpha"], latest_runs={"alpha": _run()}, route_for_run=lambda r: ("CLEAR", []),
                          cards={}, retired=[], jobs=[], symbols_for=lambda n: [])
    assert b["rows"][0]["next_action"]["kind"] == "full_trial"


# ---- accept handler refuses without a Full trial --------------------------------

def _seed(tmp_path, monkeypatch, write_backtest_result, **row):
    from tradelab.audit.history import record_run
    reports = tmp_path / "reports"; folder = reports / "alpha_x"; folder.mkdir(parents=True)
    write_backtest_result(folder, net_pnl=240.0, strategy="alpha")
    db = tmp_path / "hist.db"
    fields = dict(verdict="ROBUST", dsr_probability=0.9, report_card_html_path=str(folder / "dashboard.html"),
                  tier="full", code_hash="c1", thresholds_hash="t1")
    fields.update(row)
    run_id = record_run("alpha", db_path=db, **fields)
    cards = tmp_path / "cards.json"; cards.write_text("{}")
    monkeypatch.setattr(handlers, "_db_path", lambda: db)
    monkeypatch.setattr(handlers, "_cards_path", lambda: cards)
    monkeypatch.setattr(handlers, "_reports_root", lambda: reports)
    monkeypatch.setattr(handlers, "_current_hashes_for", lambda name: ("c1", "t1"))
    monkeypatch.setattr(handlers, "_canary_mismatch_now", lambda: False)
    monkeypatch.chdir(tmp_path)
    return run_id, folder, cards


def _accept(run_id, folder):
    return handlers.handle_post_with_status("/tradelab/strategies/accept", json.dumps({
        "base_name": "alpha", "strategy": "alpha", "symbol": "NVDA", "timeframe": "1D",
        "report_folder": str(folder), "scoring_run_id": run_id, "activate": False}).encode())


def test_accept_refuses_trial_rung(tmp_path, monkeypatch, write_backtest_result):
    run_id, folder, cards = _seed(tmp_path, monkeypatch, write_backtest_result, tier="trial")
    body, status = _accept(run_id, folder)
    assert status == 422
    d = json.loads(body)
    assert d["gate"] == "full_trial" and d["code"] == "not_full" and "Full trial required" in d["error"]
    assert json.loads(cards.read_text()) == {}


def test_accept_refuses_legacy_run_without_hashes(tmp_path, monkeypatch, write_backtest_result):
    run_id, folder, cards = _seed(tmp_path, monkeypatch, write_backtest_result, code_hash=None, thresholds_hash=None)
    body, status = _accept(run_id, folder)
    assert status == 422 and json.loads(body)["code"] == "unrecorded"


def test_accept_refuses_when_code_or_thresholds_changed(tmp_path, monkeypatch, write_backtest_result):
    run_id, folder, cards = _seed(tmp_path, monkeypatch, write_backtest_result)
    monkeypatch.setattr(handlers, "_current_hashes_for", lambda name: ("c2", "t1"))
    assert json.loads(_accept(run_id, folder)[0])["code"] == "code_changed"
    monkeypatch.setattr(handlers, "_current_hashes_for", lambda name: ("c1", "t2"))
    assert json.loads(_accept(run_id, folder)[0])["code"] == "thresholds_changed"
    assert json.loads(cards.read_text()) == {}


def test_accept_refuses_while_a_canary_mismatches(tmp_path, monkeypatch, write_backtest_result):
    run_id, folder, cards = _seed(tmp_path, monkeypatch, write_backtest_result)
    monkeypatch.setattr(handlers, "_canary_mismatch_now", lambda: True)
    body, status = _accept(run_id, folder)
    assert status == 422 and json.loads(body)["code"] == "canary_mismatch"


def test_accept_passes_a_current_full_trial(tmp_path, monkeypatch, write_backtest_result):
    run_id, folder, cards = _seed(tmp_path, monkeypatch, write_backtest_result)
    body, status = _accept(run_id, folder)
    assert status == 200, body
    assert json.loads(cards.read_text())["alpha-v1"]["promotion_route"] == "CLEAR"


def test_blocked_run_is_reported_as_blocked_not_as_missing_full_trial(tmp_path, monkeypatch, write_backtest_result):
    run_id, folder, cards = _seed(tmp_path, monkeypatch, write_backtest_result, tier="trial", dsr_probability=-0.3)
    body, status = _accept(run_id, folder)
    assert status == 422 and json.loads(body).get("state") == "BLOCKED"


# ---- the CLI records the rung and the hashes ------------------------------------

def test_record_run_round_trips_tier_and_hashes(tmp_path):
    from tradelab.audit.history import record_run, get_run
    db = tmp_path / "h.db"
    rid = record_run("alpha", verdict="ROBUST", tier="full", code_hash="c", thresholds_hash="t",
                     thresholds={"pf_robust": 1.5}, db_path=db)
    row = get_run(rid, db_path=db)
    assert (row.tier, row.code_hash, row.thresholds_hash) == ("full", "c", "t")
    assert json.loads(row.thresholds_json)["pf_robust"] == 1.5
    # legacy DB rows migrate to NULLs, never crash
    rid2 = record_run("beta", verdict="ROBUST", db_path=db)
    assert get_run(rid2, db_path=db).tier is None


def test_cli_run_records_the_rung(monkeypatch):
    """The record_run call in cli_run passes tier/code_hash/thresholds_hash —
    checked structurally so the wiring can't be dropped silently."""
    import inspect
    from tradelab import cli_run
    src = inspect.getsource(cli_run)
    assert "tier=_ladder.tier_for_flags(robustness=robustness, full=full, validation_deep=validation_deep)" in src
    assert "code_hash=_ladder.code_hash_for_class(type(strat))" in src
    assert "thresholds_hash=_ladder.thresholds_hash(_rcfg)" in src   # whole RobustnessConfig, not only thresholds


def test_full_command_is_allowed_for_jobs():
    argv = handlers._build_tradelab_argv("alpha", "run --full --validation-deep", symbols=["NVDA"])
    assert argv and argv[3:6] == ["run", "alpha", "--full"] and "--validation-deep" in argv


# ---- specialist review (S5) -------------------------------------------------------

def test_score_never_ranks_a_fragile_mix_above_inconclusive():
    """Engine rule: 2+ fragile (or 1 fragile with no robust) = FRAGILE. The
    presentation score is capped below 0.5 in exactly that case."""
    fragile_mix = ladder.score_from_signals(_sig("robust", "robust", "robust", "robust", "robust", "robust", "fragile", "fragile"))
    inconclusive = ladder.score_from_signals(_sig("inconclusive", "inconclusive", "inconclusive", "inconclusive"))
    assert fragile_mix < inconclusive and fragile_mix == 0.49
    assert ladder.score_from_signals(_sig("fragile", "inconclusive")) <= 0.49
    # one fragile with robusts present is INCONCLUSIVE by the engine → no cap
    assert ladder.score_from_signals(_sig("robust", "robust", "robust", "fragile")) == 0.75


def test_pick_representative_run_ignores_basic_and_prefers_valid_full():
    full_ok = {"tier": "full", "run_id": "f1", "timestamp_utc": "2026-09-01T00:00:00Z"}
    later_trial = {"tier": "trial", "run_id": "t2", "timestamp_utc": "2026-09-02T00:00:00Z"}
    later_basic = {"tier": "basic", "run_id": "b3", "timestamp_utc": "2026-09-03T00:00:00Z"}
    legacy = {"tier": None, "run_id": "l0", "timestamp_utc": "2026-08-01T00:00:00Z"}
    pick = board.pick_representative_run
    assert pick([later_basic, later_trial, full_ok, legacy], full_ok=lambda r: True)["run_id"] == "f1"
    assert pick([later_basic, later_trial, full_ok, legacy], full_ok=lambda r: False)["run_id"] == "t2"
    assert pick([later_basic], full_ok=lambda r: True) is None
    assert pick([later_basic, legacy], full_ok=lambda r: True)["run_id"] == "l0"
    assert pick([], full_ok=lambda r: True) is None


def test_pine_accept_and_one_click_activate_run_the_ladder_gate(tmp_path, monkeypatch, write_backtest_result):
    """Specialist S5 #1: every accept path. Both legacy routes must refuse a
    non-full run with the same {gate: full_trial} envelope."""
    run_id, folder, cards = _seed(tmp_path, monkeypatch, write_backtest_result, tier="trial")
    body, status = handlers.handle_post_with_status("/tradelab/accept", json.dumps({
        "base_name": "alpha", "symbol": "NVDA", "timeframe": "1D", "report_folder": str(folder),
        "verdict": "ROBUST", "scoring_run_id": run_id, "activate": False}).encode())
    assert status == 422 and json.loads(body).get("gate") == "full_trial", body
    body, status = handlers.handle_post_with_status("/tradelab/strategies/alpha/activate", b"{}")
    assert status == 422 and json.loads(body).get("gate") == "full_trial", body
    assert json.loads(cards.read_text()) == {}
    # and a pine accept with no run id at all is refused too
    body, status = handlers.handle_post_with_status("/tradelab/accept", json.dumps({
        "base_name": "alpha", "symbol": "NVDA", "timeframe": "1D", "report_folder": str(folder),
        "verdict": "ROBUST", "activate": False}).encode())
    assert status == 422 and "scoring_run_id required" in json.loads(body)["error"]


# ---- specialist re-review (S5, pass 2) --------------------------------------------

def test_canary_mismatch_keeps_the_full_trial_representative(tmp_path, monkeypatch, write_backtest_result):
    """#2: under a canary mismatch the valid Full trial must stay the row's run
    (Accept shown disabled with the canary reason), not fall back to a Trial
    with a live 'Full trial required' button."""
    run_id, folder, cards = _seed(tmp_path, monkeypatch, write_backtest_result)
    from tradelab.audit.history import record_run
    record_run("alpha", verdict="ROBUST", dsr_probability=0.8, tier="trial", code_hash="c1", thresholds_hash="t1",
               report_card_html_path=str(folder / "dashboard.html"), db_path=handlers._db_path())
    monkeypatch.setattr(handlers, "_canary_mismatch_now", lambda: True)
    import tradelab.registry as reg
    monkeypatch.setattr(reg, "list_registered_strategies", lambda: {"alpha": 1})
    monkeypatch.setattr(reg, "load_strategy_class", lambda name: type("S", (), {"symbols": []}))
    body, status = handlers.handle_get_with_status("/tradelab/board")
    row = json.loads(body)["data"]["rows"][0]
    assert row["run_id"] == run_id and row["tier"] == "full"
    assert row["next_action"]["kind"] == "accept" and row["next_action"]["enabled"] is False
    assert "integrity" in row["next_action"]["reason"]


def test_newer_worse_trial_is_surfaced_on_a_tried_row(tmp_path, monkeypatch, write_backtest_result):
    """#4: a later Trial that routes worse than the representative Full trial
    is reported as newer_trial (worse=True) on the Tried row."""
    run_id, folder, cards = _seed(tmp_path, monkeypatch, write_backtest_result)
    from tradelab.audit.history import record_run
    record_run("alpha", verdict="FRAGILE", dsr_probability=0.3, tier="trial", code_hash="c1", thresholds_hash="t1",
               report_card_html_path=str(folder / "dashboard.html"), db_path=handlers._db_path())
    import tradelab.registry as reg
    monkeypatch.setattr(reg, "list_registered_strategies", lambda: {"alpha": 1})
    monkeypatch.setattr(reg, "load_strategy_class", lambda name: type("S", (), {"symbols": []}))
    body, status = handlers.handle_get_with_status("/tradelab/board")
    row = json.loads(body)["data"]["rows"][0]
    assert row["run_id"] == run_id and row["next_action"]["kind"] == "accept"
    assert row["newer_trial"] and row["newer_trial"]["route"] == "ADVISORY" and row["newer_trial"]["worse"] is True


def test_activate_route_uses_the_representative_run(tmp_path, monkeypatch, write_backtest_result):
    """#3: a bare `run` after a valid Full trial must not make /activate refuse."""
    run_id, folder, cards = _seed(tmp_path, monkeypatch, write_backtest_result)
    from tradelab.audit.history import record_run
    record_run("alpha", verdict="ROBUST", dsr_probability=0.8, tier="basic",
               report_card_html_path=str(folder / "dashboard.html"), db_path=handlers._db_path())
    calls = []
    monkeypatch.setattr(handlers, "_ladder_gate_response", lambda rid, name: calls.append(rid) or json.dumps({"error": "stop", "data": None}))
    monkeypatch.setattr(handlers, "_pine_archive_root", lambda: tmp_path / "pine", raising=False)
    handlers.handle_post_with_status("/tradelab/strategies/alpha/activate", b"{}")
    assert calls == [run_id]   # the Full trial, not the newer bare run


def test_gate_refuses_an_unscorable_run(tmp_path, monkeypatch, write_backtest_result):
    """#5: a run whose folder cannot be scored is refused, never deferred."""
    run_id, folder, cards = _seed(tmp_path, monkeypatch, write_backtest_result)
    (folder / "backtest_result.json").unlink()
    resp = handlers._ladder_gate_response(run_id, "alpha")
    assert resp is not None and resp[1] == 422 and json.loads(resp[0])["code"] == "unscorable"


def test_pine_accept_ignores_client_verdict_and_folder(tmp_path, monkeypatch, write_backtest_result):
    """#1: the pine route is routed on the audit row like the python route."""
    run_id, folder, cards = _seed(tmp_path, monkeypatch, write_backtest_result, verdict="INCONCLUSIVE", dsr_probability=0.4)
    (folder / "strategy.pine").write_text("// pine")
    monkeypatch.setattr(handlers, "_pine_archive_root", lambda: tmp_path / "pine_archive")
    other = tmp_path / "reports" / "healthy"; other.mkdir(); write_backtest_result(other, net_pnl=900.0)
    body, status = handlers.handle_post_with_status("/tradelab/accept", json.dumps({
        "base_name": "alpha", "symbol": "NVDA", "timeframe": "1D", "report_folder": str(other),
        "verdict": "ROBUST", "scoring_run_id": run_id, "activate": True}).encode())
    assert status == 422 and "does not match" in body
    body, status = handlers.handle_post_with_status("/tradelab/accept", json.dumps({
        "base_name": "alpha", "symbol": "NVDA", "timeframe": "1D", "report_folder": str(folder),
        "verdict": "ROBUST", "scoring_run_id": run_id, "activate": True}).encode())
    assert status == 422 and json.loads(body).get("state") == "ADVISORY", body
    body, status = handlers.handle_post_with_status("/tradelab/accept", json.dumps({
        "base_name": "beta", "symbol": "NVDA", "timeframe": "1D", "report_folder": str(folder),
        "scoring_run_id": run_id}).encode())
    assert status == 422 and "belongs to" in body
    assert json.loads(cards.read_text()) == {}
