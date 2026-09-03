"""S4 (2026-09-03) — the strategy board: one strategy, one state, one next action."""
from __future__ import annotations

import json

import pytest

from tradelab.live.cards import CardRegistry, RetiredLog
from tradelab.web import board, handlers


def _run(name, verdict="ROBUST", dsr=0.8, run_id="r1"):
    return {"strategy_name": name, "verdict": verdict, "dsr_probability": dsr, "run_id": run_id,
            "timestamp_utc": "2026-09-01T00:00:00Z", "universe": "declared:NVDA",
            "report_card_html_path": f"reports/{name}/dashboard.html"}


ROUTES = {"ROBUST": ("CLEAR", []), "INCONCLUSIVE": ("ADVISORY", []), "FRAGILE": ("ADVISORY", []),
          "BLOCKED": ("BLOCKED", ["DISQ_EXPECTANCY_NEGATIVE"])}


def _route(run):
    return ROUTES[run["verdict"]]


def _board(**kw):
    # S5: the S4 matrix assumes a Full trial of current code/thresholds exists
    # (full_trial_for → ok); test_s5_ladder.py covers the other cases.
    args = dict(registered=[], latest_runs={}, route_for_run=_route, cards={}, retired=[], jobs=[],
                symbols_for=lambda n: ["NVDA"], full_trial_for=lambda name, run: {"ok": True, "code": None, "reason": None})
    args.update(kw)
    return board.build_board(**args)


# ---- derivation matrix -------------------------------------------------------

def test_registered_without_runs_is_candidate_with_trial():
    b = _board(registered=["alpha"])
    r = b["rows"][0]
    assert r["state"] == "candidate" and r["next_action"]["kind"] == "trial" and r["next_action"]["enabled"]
    assert r["symbols"] == ["NVDA"] and r["verdict"] is None


def test_clear_run_is_tried_with_accept():
    b = _board(registered=["alpha"], latest_runs={"alpha": _run("alpha", "ROBUST")})
    r = b["rows"][0]
    assert r["state"] == "tried" and r["route"] == "CLEAR"
    assert r["next_action"] == {"kind": "accept", "label": "Accept", "enabled": True, "reason": None}


def test_advisory_run_is_tried_with_disabled_override_action():
    b = _board(registered=["alpha"], latest_runs={"alpha": _run("alpha", "INCONCLUSIVE")})
    a = b["rows"][0]["next_action"]
    assert a["kind"] == "accept_override" and a["enabled"] is False and "S6" in a["reason"]


def test_blocked_run_is_tried_with_retrial_and_blockers_named():
    b = _board(registered=["alpha"], latest_runs={"alpha": _run("alpha", "BLOCKED")})
    r = b["rows"][0]
    assert r["route"] == "BLOCKED" and r["blockers"] == ["DISQ_EXPECTANCY_NEGATIVE"]
    assert r["next_action"]["kind"] == "retrial" and "DISQ_EXPECTANCY_NEGATIVE" in r["next_action"]["reason"]


def test_run_without_verdict_or_unscorable_folder_is_not_a_trial():
    b = _board(registered=["alpha"], latest_runs={"alpha": _run("alpha", verdict=None)})
    assert b["rows"][0]["state"] == "candidate"
    b = _board(registered=["alpha"], latest_runs={"alpha": _run("alpha", "ROBUST")},
               route_for_run=lambda run: (None, []))
    assert b["rows"][0]["state"] == "candidate"
    b = _board(registered=["alpha"], latest_runs={"alpha": _run("alpha", "ROBUST")},
               route_for_run=lambda run: (_ for _ in ()).throw(RuntimeError("no folder")))
    assert b["rows"][0]["state"] == "candidate"


def test_card_wins_over_run_and_shows_mode():
    cards = {"alpha-v2": {"card_id": "alpha-v2", "strategy": "alpha", "version": 2, "status": "enabled",
                          "allocation_usd": 300},
             "alpha-v1": {"card_id": "alpha-v1", "strategy": "alpha", "version": 1, "status": "disabled"}}
    b = _board(registered=["alpha"], latest_runs={"alpha": _run("alpha", "BLOCKED")}, cards=cards)
    r = b["rows"][0]
    assert r["state"] == "accepted" and r["card_id"] == "alpha-v2" and r["card_status"] == "enabled"
    assert r["allocation_usd"] == 300 and r["next_action"]["kind"] == "open_tab"
    assert "Paper" in r["next_action"]["label"]


def test_retired_without_card_is_retired_with_trial_again():
    retired = [{"card": {"card_id": "alpha-v1", "strategy": "alpha"}, "retired_at": "2026-09-02T00:00:00+00:00"}]
    b = _board(registered=["alpha"], retired=retired)
    r = b["rows"][0]
    assert r["state"] == "retired" and r["retired_at"].startswith("2026-09-02")
    assert r["next_action"] == {"kind": "trial", "label": "Trial again", "enabled": True, "reason": None}


def test_retired_then_retried_is_tried_not_retired():
    """A trial NEWER than the retirement moves the strategy back to Tried;
    the old run it was accepted from does not (specialist note #4)."""
    retired = [{"card": {"card_id": "alpha-v1", "strategy": "alpha", "scoring_run_id": "r1"},
                "retired_at": "2026-09-02T00:00:00+00:00"}]
    old_run = _run("alpha", "ROBUST")                                # r1 @ 2026-09-01
    b = _board(registered=["alpha"], retired=retired, latest_runs={"alpha": old_run})
    assert b["rows"][0]["state"] == "retired"
    new_run = {**_run("alpha", "ROBUST", run_id="r2"), "timestamp_utc": "2026-09-03T00:00:00Z"}
    b = _board(registered=["alpha"], retired=retired, latest_runs={"alpha": new_run})
    assert b["rows"][0]["state"] == "tried"


def test_orphan_card_is_on_the_board_flagged_unregistered():
    cards = {"ghost-v1": {"card_id": "ghost-v1", "strategy": "ghost", "version": 1, "status": "enabled"}}
    b = _board(registered=["alpha"], cards=cards)
    ghost = next(r for r in b["rows"] if r["strategy"] == "ghost")
    assert ghost["state"] == "accepted" and ghost["unregistered"] is True
    assert next(r for r in b["rows"] if r["strategy"] == "alpha")["unregistered"] is False


def test_newer_worse_trial_on_accepted_card_is_surfaced():
    cards = {"alpha-v1": {"card_id": "alpha-v1", "strategy": "alpha", "version": 1, "status": "enabled",
                          "scoring_run_id": "r1", "created_at": "2026-09-01T12:00:00+00:00",
                          "promotion_route": "CLEAR"}}
    newer = {**_run("alpha", "BLOCKED", run_id="r9"), "timestamp_utc": "2026-09-03T00:00:00Z"}
    b = _board(registered=["alpha"], cards=cards, latest_runs={"alpha": newer})
    r = b["rows"][0]
    assert r["state"] == "accepted" and r["newer_trial"]["route"] == "BLOCKED" and r["newer_trial"]["worse"] is True
    # the card's own run is not a "newer trial"
    b = _board(registered=["alpha"], cards=cards, latest_runs={"alpha": {**_run("alpha", "ROBUST", run_id="r1"), "timestamp_utc": "2026-09-01T00:00:00Z"}})
    assert b["rows"][0]["newer_trial"] is None


def test_data_end_is_carried_when_available():
    b = _board(registered=["alpha"], latest_runs={"alpha": _run("alpha")}, data_end_for=lambda run: "2026-06-02")
    assert b["rows"][0]["data_end"] == "2026-06-02"
    b = _board(registered=["alpha"], latest_runs={"alpha": _run("alpha")},
               data_end_for=lambda run: (_ for _ in ()).throw(OSError("x")))
    assert b["rows"][0]["data_end"] is None


def test_bulk_delete_logs_retirements(tmp_path, monkeypatch):
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps({"a-v1": {"card_id": "a-v1", "strategy": "a", "secret": "S"},
                                 "b-v1": {"card_id": "b-v1", "strategy": "b", "secret": "S"}}))
    monkeypatch.setattr(handlers, "_cards_path", lambda: cards)
    body, status = handlers.handle_post_with_status(
        "/tradelab/cards/bulk-delete", json.dumps({"ids": ["a-v1", "b-v1"], "confirm": "DELETE"}).encode())
    assert status == 200
    got = RetiredLog(cards).all()
    assert sorted(x["card"]["card_id"] for x in got) == ["a-v1", "b-v1"] and all("secret" not in x["card"] for x in got)


def test_busy_job_replaces_the_action_but_keeps_the_state():
    jobs = [{"id": "j1", "status": "running", "strategy": "alpha", "command": "run --robustness",
             "started_at": "2026-09-03T00:00:00Z", "summary": "fold 3/6"},
            {"id": "j0", "status": "done", "strategy": "alpha", "command": "run"}]
    b = _board(registered=["alpha"], jobs=jobs)
    r = b["rows"][0]
    assert r["state"] == "candidate" and r["busy"]["job_id"] == "j1"
    assert r["next_action"]["kind"] == "busy" and r["next_action"]["enabled"] is False


def test_every_registered_strategy_appears_exactly_once_in_spine_order():
    b = _board(registered=["zeta", "alpha", "mid"],
               latest_runs={"alpha": _run("alpha", "ROBUST")},
               cards={"mid-v1": {"card_id": "mid-v1", "strategy": "mid", "version": 1, "status": "disabled"}})
    assert [r["strategy"] for r in b["rows"]] == ["zeta", "alpha", "mid"]
    assert [r["state"] for r in b["rows"]] == ["candidate", "tried", "accepted"]
    assert b["counts"] == {"candidate": 1, "tried": 1, "accepted": 1, "paper_qualified": 0, "live": 0, "retired": 0}


def test_symbols_failure_is_empty_not_fatal():
    b = _board(registered=["alpha"], symbols_for=lambda n: (_ for _ in ()).throw(ImportError("x")))
    assert b["rows"][0]["symbols"] == []


def test_board_never_emits_s7_or_s9_states():
    b = _board(registered=["a", "b"], latest_runs={"a": _run("a")},
               cards={"b-v1": {"card_id": "b-v1", "strategy": "b", "status": "enabled", "version": 1}})
    assert {r["state"] for r in b["rows"]} <= {"candidate", "tried", "accepted", "retired"}


# ---- retired log --------------------------------------------------------------

def test_retired_log_drops_secret_and_appends(tmp_path):
    log = RetiredLog(tmp_path / "cards.json")
    assert log.all() == []
    e = log.append({"card_id": "a-v1", "secret": "SHH", "strategy": "a"}, retired_at="2026-09-03T00:00:00+00:00")
    assert "secret" not in e["card"] and log.path.name == "cards_retired.json"
    log.append({"card_id": "a-v2", "strategy": "a"})
    assert [x["card"]["card_id"] for x in log.all()] == ["a-v1", "a-v2"]


def test_delete_card_route_logs_retirement(tmp_path, monkeypatch):
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps({"a-v1": {"card_id": "a-v1", "strategy": "a", "secret": "SHH", "status": "disabled"}}))
    monkeypatch.setattr(handlers, "_cards_path", lambda: cards)
    body, status = handlers.handle_delete_with_status_with_body("/tradelab/cards/a-v1", json.dumps({"confirm": "DELETE"}).encode())
    assert status == 200
    assert json.loads(cards.read_text()) == {}
    retired = RetiredLog(cards).all()
    assert len(retired) == 1 and retired[0]["card"]["card_id"] == "a-v1" and "secret" not in retired[0]["card"]
    body, status = handlers.handle_get_with_status("/tradelab/cards/retired")
    assert status == 200 and json.loads(body)["data"]["retired"][0]["card"]["card_id"] == "a-v1"


# ---- route agreement with Accept ------------------------------------------------

def test_route_for_run_uses_accepts_own_gate(tmp_path, write_backtest_result):
    folder = tmp_path / "reports" / "alpha_x"
    folder.mkdir(parents=True)
    write_backtest_result(folder)
    run = {"verdict": "ROBUST", "dsr_probability": 0.9, "report_card_html_path": str(folder / "dashboard.html")}
    assert handlers._route_for_run(run) == ("CLEAR", [])
    run["verdict"] = "INCONCLUSIVE"
    assert handlers._route_for_run(run) == ("ADVISORY", [])
    run["dsr_probability"] = -0.2
    route, blockers = handlers._route_for_run(run)
    assert route == "BLOCKED" and blockers


def test_route_for_run_fails_closed_without_metrics(tmp_path):
    folder = tmp_path / "reports" / "alpha_x"
    folder.mkdir(parents=True)
    assert handlers._route_for_run({"verdict": "ROBUST", "report_card_html_path": str(folder)}) == (None, [])
    assert handlers._route_for_run({"verdict": "ROBUST", "report_card_html_path": None}) == (None, [])


# ---- the accept hole (S4 finding) -------------------------------------------------

def test_accept_off_stores_route_and_refuses_blocked(tmp_path, write_backtest_result):
    """Before S4, accept with activate=False skipped the route gate, so a
    BLOCKED run could become a card with no promotion_route to refuse on."""
    from tradelab.web.approve_strategy import accept_python_run, PromotionBlocked
    folder = tmp_path / "reports" / "alpha_x"
    folder.mkdir(parents=True)
    write_backtest_result(folder)
    reg = CardRegistry(tmp_path / "cards.json")
    card = accept_python_run(base_name="alpha", symbol="NVDA", timeframe="1D", report_folder=str(folder),
                             verdict="ROBUST", dsr_probability=0.9, scoring_run_id="r", strategy="alpha",
                             registry=reg, reports_root=tmp_path / "reports", activate=False)
    assert card["promotion_route"] == "CLEAR" and card["status"] == "disabled"
    with pytest.raises(PromotionBlocked):
        accept_python_run(base_name="beta", symbol="NVDA", timeframe="1D", report_folder=str(folder),
                          verdict="ROBUST", dsr_probability=-0.5, scoring_run_id="r", strategy="beta",
                          registry=reg, reports_root=tmp_path / "reports", activate=False)
    assert reg.get("beta-v1") is None


def test_board_route_uses_registry_db_cards_and_jobs(tmp_path, monkeypatch):
    """The handler wires real inputs; here we stub each source and check the
    envelope shape end-to-end."""
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps({"mid-v1": {"card_id": "mid-v1", "strategy": "mid", "version": 1,
                                            "status": "disabled", "promotion_route": "CLEAR"}}))
    monkeypatch.setattr(handlers, "_cards_path", lambda: cards)
    import tradelab.registry as reg
    monkeypatch.setattr(reg, "list_registered_strategies", lambda: {"alpha": object(), "mid": object()})
    monkeypatch.setattr(reg, "load_strategy_class", lambda name: type("S", (), {"symbols": ["NVDA"]}))
    monkeypatch.setattr(handlers.audit_reader, "list_runs", lambda **kw: [_run("alpha", "ROBUST")])
    monkeypatch.setattr(handlers, "_route_for_run", lambda run: ("CLEAR", []))
    body, status = handlers.handle_get_with_status("/tradelab/board")
    assert status == 200
    d = json.loads(body)["data"]
    assert {r["strategy"]: r["state"] for r in d["rows"]} == {"alpha": "tried", "mid": "accepted"}
    assert d["counts"]["tried"] == 1 and d["generated_at"]


def test_excluded_names_are_reported_not_rows():
    b = _board(registered=["alpha", "rand_canary", "simple"],
               excluded={"rand_canary": "canary", "simple": "abstract base", "ghost": "not registered"})
    assert [r["strategy"] for r in b["rows"]] == ["alpha"]
    assert b["excluded"] == [{"strategy": "rand_canary", "reason": "canary"},
                             {"strategy": "simple", "reason": "abstract base"}]


def test_board_route_excludes_canaries_and_abstract_bases(tmp_path, monkeypatch):
    cards = tmp_path / "cards.json"; cards.write_text("{}")
    monkeypatch.setattr(handlers, "_cards_path", lambda: cards)
    import tradelab.registry as reg
    monkeypatch.setattr(reg, "list_registered_strategies",
                        lambda: {"alpha": 1, "rand_canary": 1, "simple": 1})
    class Abstract:
        _tradelab_abstract = True
        symbols = []
    class Concrete(Abstract):
        pass
    monkeypatch.setattr(reg, "load_strategy_class", lambda name: Abstract if name == "simple" else Concrete)
    monkeypatch.setattr(handlers.audit_reader, "list_runs", lambda **kw: [])
    body, status = handlers.handle_get_with_status("/tradelab/board")
    d = json.loads(body)["data"]
    assert [r["strategy"] for r in d["rows"]] == ["alpha"]
    assert {e["strategy"] for e in d["excluded"]} == {"rand_canary", "simple"}


# ---- failed trials leave a trail ----------------------------------------------

def test_failed_job_newer_than_last_run_is_reported_on_the_card():
    jobs = [{"id": "j1", "status": "failed", "strategy": "alpha", "command": "run --robustness",
             "started_at": "2026-09-03T03:04:21Z", "failure_hint": "Python exception (see log)"}]
    b = _board(registered=["alpha"], jobs=jobs)
    r = b["rows"][0]
    assert r["state"] == "candidate" and r["last_failure"]["job_id"] == "j1"
    assert "Python exception" in r["last_failure"]["hint"]
    # an older failure than the latest good run is not surfaced
    b = _board(registered=["alpha"], jobs=jobs, latest_runs={"alpha": {**_run("alpha"), "timestamp_utc": "2026-09-04T00:00:00Z"}})
    assert b["rows"][0]["last_failure"] is None
    # a running job hides the stale failure
    b = _board(registered=["alpha"], jobs=jobs + [{"id": "j2", "status": "running", "strategy": "alpha",
                                                    "command": "run", "started_at": "2026-09-05T00:00:00Z"}])
    assert b["rows"][0]["last_failure"] is None and b["rows"][0]["busy"]["job_id"] == "j2"


def test_every_job_gets_a_log_path(tmp_path, monkeypatch):
    from tradelab.web.jobs import JobManager
    jm = JobManager(cache_root=tmp_path / ".cache")
    monkeypatch.setattr(jm, "_spawn", lambda *a, **k: None, raising=False)
    import subprocess
    class P:
        pid = 1; returncode = 0
        def poll(self): return 0
        def communicate(self, *a, **k): return b"hello\n", b"boom\n"
        def wait(self, *a, **k): return 0
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: P())
    job_id, _ = jm.submit("alpha", "run", ["python", "-c", "pass"])
    job = jm.get(job_id)
    assert job.log_path and job.log_path.endswith("run.log")
    assert str(tmp_path / ".cache" / "jobs" / job_id) in job.log_path


def test_job_log_route_tails_run_log(tmp_path, monkeypatch):
    from tradelab.web.jobs import JobManager
    jm = JobManager(cache_root=tmp_path / ".cache")
    monkeypatch.setattr(handlers, "_get_job_manager", lambda: jm)
    jid = "a" * 32
    d = tmp_path / ".cache" / "jobs" / jid
    d.mkdir(parents=True)
    (d / "run.log").write_text("Traceback...\nValueError: no symbols\n")
    body, status = handlers.handle_get_with_status(f"/tradelab/jobs/{jid}/log")
    assert status == 200 and "ValueError: no symbols" in json.loads(body)["data"]["tail"]
    assert handlers.handle_get_with_status(f"/tradelab/jobs/{'b' * 32}/log")[1] == 404
    assert handlers.handle_get_with_status("/tradelab/jobs/../x/log")[1] in (400, 404)


# ---- accept is routed on the audit row, never the payload (specialist #2) ----

def _seed_run(tmp_path, monkeypatch, write_backtest_result, *, verdict="ROBUST", dsr=0.9, net_pnl=240.0):
    from tradelab.audit.history import record_run
    reports = tmp_path / "reports"
    folder = reports / "alpha_x"
    folder.mkdir(parents=True)
    write_backtest_result(folder, net_pnl=net_pnl, strategy="alpha")
    db = tmp_path / "hist.db"
    # S5: a Full trial of the current file under the current thresholds
    from tradelab import ladder
    from tradelab.config import get_config
    code, thr = handlers._current_hashes_for("alpha")
    run_id = record_run("alpha", verdict=verdict, dsr_probability=dsr,
                        report_card_html_path=str(folder / "dashboard.html"), db_path=db,
                        tier="full", code_hash=code or "nocode", thresholds_hash=thr)
    if code is None:   # "alpha" is not a real registered strategy: pin the hash the handler will compute
        monkeypatch.setattr(handlers, "_current_hashes_for", lambda name: ("nocode", thr))
    cards = tmp_path / "cards.json"; cards.write_text("{}")
    monkeypatch.setattr(handlers, "_db_path", lambda: db)
    monkeypatch.setattr(handlers, "_cards_path", lambda: cards)
    monkeypatch.setattr(handlers, "_reports_root", lambda: reports)
    monkeypatch.chdir(tmp_path)
    return run_id, folder, cards


def _accept(payload):
    return handlers.handle_post_with_status("/tradelab/strategies/accept", json.dumps(payload).encode())


def _payload(run_id, folder, **over):
    p = {"base_name": "alpha", "strategy": "alpha", "symbol": "NVDA", "timeframe": "1D",
         "report_folder": str(folder), "scoring_run_id": run_id, "activate": False}
    p.update(over)
    return p


def test_accept_requires_a_run_id(tmp_path, monkeypatch, write_backtest_result):
    run_id, folder, cards = _seed_run(tmp_path, monkeypatch, write_backtest_result)
    body, status = _accept(_payload(run_id, folder, scoring_run_id=""))
    assert status == 422 and "scoring_run_id" in body
    assert _accept(_payload("no-such-run", folder))[1] == 404


def test_accept_ignores_client_verdict_and_dsr(tmp_path, monkeypatch, write_backtest_result):
    """Audit row says INCONCLUSIVE (ADVISORY). Posting verdict=ROBUST must not
    upgrade it to a CLEAR card."""
    run_id, folder, cards = _seed_run(tmp_path, monkeypatch, write_backtest_result, verdict="INCONCLUSIVE", dsr=0.4)
    body, status = _accept(_payload(run_id, folder, verdict="ROBUST", dsr_probability=0.99))
    assert status == 422 and json.loads(body).get("state") == "ADVISORY"
    assert json.loads(cards.read_text()) == {}


def test_accept_ignores_client_folder_and_uses_the_runs_own(tmp_path, monkeypatch, write_backtest_result):
    """A negative-expectancy run (BLOCKED) cannot be laundered by pointing
    report_folder at some other, healthy folder."""
    run_id, folder, cards = _seed_run(tmp_path, monkeypatch, write_backtest_result, net_pnl=-50.0)
    other = tmp_path / "reports" / "healthy"; other.mkdir()
    write_backtest_result(other, net_pnl=500.0, strategy="alpha")
    body, status = _accept(_payload(run_id, other))
    assert status == 422 and "does not match" in body
    body, status = _accept(_payload(run_id, folder))
    assert status == 422 and json.loads(body).get("state") == "BLOCKED"
    assert json.loads(cards.read_text()) == {}


def test_accept_clear_run_creates_off_card_with_route(tmp_path, monkeypatch, write_backtest_result):
    run_id, folder, cards = _seed_run(tmp_path, monkeypatch, write_backtest_result)
    body, status = _accept(_payload(run_id, folder, verdict="FRAGILE"))   # client lie is ignored
    assert status == 200, body
    card = json.loads(cards.read_text())["alpha-v1"]
    assert card["status"] == "disabled" and card["promotion_route"] == "CLEAR" and card["verdict"] == "ROBUST"


def test_accept_refuses_run_of_another_strategy(tmp_path, monkeypatch, write_backtest_result):
    run_id, folder, cards = _seed_run(tmp_path, monkeypatch, write_backtest_result)
    body, status = _accept(_payload(run_id, folder, strategy="beta", base_name="beta"))
    assert status == 422 and "belongs to" in body


def test_job_manager_broadcasts_settled_state_after_exit(tmp_path, monkeypatch):
    """The reaper announces the FINAL status (after the flip), even for a
    process that never wrote a 'done' progress line (specialist #7)."""
    import subprocess
    from tradelab.web.jobs import JobManager
    jm = JobManager(cache_root=tmp_path / ".cache")
    seen = []
    jm._on_state_change = lambda jid, ev: seen.append((jid, ev))
    class P:
        pid = 1; returncode = 3
        def poll(self): return 3
        def communicate(self, *a, **k): return b"", b"ImportError: boom\n"
        def wait(self, *a, **k): return 3
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: P())
    job_id, _ = jm.submit("alpha", "run", ["python", "-c", "pass"])
    assert jm.wait_for_terminal(job_id, timeout=10)
    settled = [ev for jid, ev in seen if jid == job_id and ev.get("settled")]
    assert settled and settled[-1]["status"] == "failed" and settled[-1]["exit"] == 3
    assert jm.get(job_id).status.value == "failed"


def test_data_end_reads_actual_last_bar_not_requested_window(tmp_path):
    """Specialist re-review #1: end_date is the REQUESTED window; on a
    stale-cache run it would read 'today' while the bars stop months earlier.
    Only data_last_bar may feed the marker; older results yield None."""
    folder = tmp_path / "r"; folder.mkdir()
    (folder / "backtest_result.json").write_text(json.dumps({"end_date": "2026-09-03"}))
    assert handlers._data_end_for_run({"report_card_html_path": str(folder / "dashboard.html")}) is None
    (folder / "backtest_result.json").write_text(json.dumps({"end_date": "2026-09-03", "data_last_bar": "2026-06-02"}))
    assert handlers._data_end_for_run({"report_card_html_path": str(folder / "dashboard.html")}) == "2026-06-02"


def test_iso_key_orders_mixed_suffixes_correctly():
    k = board._iso_key
    assert k("2026-09-03T03:04:21Z") < k("2026-09-03T03:04:22+00:00")
    assert k("2026-09-03T03:04:21Z") == k("2026-09-03T03:04:21+00:00")
    assert k("2026-09-03T05:04:21+02:00") == k("2026-09-03T03:04:21Z")
    assert k(None) == "" and k("garbage") == ""


def test_backtest_result_carries_data_last_bar():
    from tradelab.results import BacktestResult
    bt = BacktestResult(strategy="s", start_date="2024-01-01", end_date="2026-09-03")
    assert bt.data_last_bar is None
    bt.data_last_bar = "2026-06-02"
    assert json.loads(bt.model_dump_json())["data_last_bar"] == "2026-06-02"
