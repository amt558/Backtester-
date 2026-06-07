"""Step 3 — three-way promotion routing (BLOCKED / ADVISORY / CLEAR).

Tests that the promote-path chokepoint CONSUMES the hard-disqualifier floor
correctly. The floor itself (hard_disqualifiers) is fenced and tested in
tests/robustness/test_hard_disqualifiers.py; here we only verify the routing:

  - route_promotion (pure)
  - accept_scored / accept_python_run gates (activate=True)
  - handler-level BLOCKED -> 422 with state + blockers
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tradelab.results import BacktestMetrics
from tradelab.web import approve_strategy
from tradelab.web.approve_strategy import (
    ActivationGateFailed,
    PromotionBlocked,
    ROUTE_ADVISORY,
    ROUTE_BLOCKED,
    ROUTE_CLEAR,
    route_promotion,
)

SMOKE_CSV = Path("tests/io/fixtures/tv_export_amzn_smoke.csv")


def _registry(tmp_path: Path):
    from tradelab.live.cards import CardRegistry
    return CardRegistry(tmp_path / "cards.json")


def _score_once(tmp_path: Path, base_name: str = "smoke-amzn") -> dict:
    return approve_strategy.score_csv(
        csv_text=SMOKE_CSV.read_text(encoding="utf-8-sig"),
        pine_source="// pine stub",
        symbol="AMZN", base_name=base_name, timeframe="1H",
        reports_root=tmp_path / "reports",
        db_path=tmp_path / "audit.db",
    )


# ─── route_promotion (pure) ─────────────────────────────────────────────

def test_route_blocked_on_non_positive_net_pnl():
    route, blockers = route_promotion("FRAGILE", BacktestMetrics(net_pnl=-100.0), 0.5)
    assert route == ROUTE_BLOCKED
    assert blockers == ["NEG_NET_EXPECTANCY"]


def test_route_blocked_on_negative_dsr():
    route, blockers = route_promotion("FRAGILE", BacktestMetrics(net_pnl=500.0), -0.01)
    assert route == ROUTE_BLOCKED
    assert blockers == ["DSR_NEGATIVE"]


def test_route_blocked_even_when_verdict_robust():
    """The floor outranks the verdict — a ROBUST verdict cannot paper over a
    tripped disqualifier."""
    route, blockers = route_promotion("ROBUST", BacktestMetrics(net_pnl=-1.0), 0.9)
    assert route == ROUTE_BLOCKED
    assert "NEG_NET_EXPECTANCY" in blockers


def test_route_clear_for_robust_and_clean_floor():
    route, blockers = route_promotion("ROBUST", BacktestMetrics(net_pnl=500.0), 0.8)
    assert route == ROUTE_CLEAR
    assert blockers == []


def test_route_advisory_for_fragile_and_clean_floor():
    route, blockers = route_promotion("FRAGILE", BacktestMetrics(net_pnl=500.0), 0.8)
    assert route == ROUTE_ADVISORY
    assert blockers == []


def test_route_advisory_for_inconclusive_and_clean_floor():
    route, blockers = route_promotion("INCONCLUSIVE", BacktestMetrics(net_pnl=500.0), 0.8)
    assert route == ROUTE_ADVISORY
    assert blockers == []


def test_route_dsr_none_does_not_trip():
    route, blockers = route_promotion("ROBUST", BacktestMetrics(net_pnl=500.0), None)
    assert route == ROUTE_CLEAR
    assert blockers == []


def test_route_dsr_zero_does_not_trip():
    route, blockers = route_promotion("ROBUST", BacktestMetrics(net_pnl=500.0), 0.0)
    assert route == ROUTE_CLEAR
    assert blockers == []


# ─── accept_scored (Pine path) ──────────────────────────────────────────

def test_accept_scored_clear_stamps_promotion_route(tmp_path):
    scored = _score_once(tmp_path)
    reg = _registry(tmp_path)
    result = approve_strategy.accept_scored(
        base_name="smoke-amzn", symbol="AMZN", timeframe="1H",
        report_folder=scored["report_folder"], verdict="ROBUST",
        dsr_probability=scored["dsr_probability"],
        scoring_run_id=scored["scoring_run_id"], registry=reg,
        pine_archive_root=tmp_path / "pine_archive",
        reports_root=tmp_path / "reports", activate=True,
        db_path=tmp_path / "audit.db",
    )
    card = reg.get(result["card_id"])
    assert card["promotion_route"] == "CLEAR"
    archive = Path(result["pine_archive_path"])
    vj = json.loads((archive / "verdict.json").read_text(encoding="utf-8"))
    assert vj["promotion_route"] == "CLEAR"


def test_accept_scored_advisory_raises_gate_not_blocked(tmp_path):
    """FRAGILE + clean floor → ADVISORY → ActivationGateFailed, NOT
    PromotionBlocked (the Pine path hard-blocks ADVISORY)."""
    scored = _score_once(tmp_path)
    reg = _registry(tmp_path)
    with pytest.raises(ActivationGateFailed) as exc:
        approve_strategy.accept_scored(
            base_name="smoke-amzn", symbol="AMZN", timeframe="1H",
            report_folder=scored["report_folder"], verdict="FRAGILE",
            dsr_probability=scored["dsr_probability"],
            scoring_run_id=scored["scoring_run_id"], registry=reg,
            pine_archive_root=tmp_path / "pine_archive",
            reports_root=tmp_path / "reports", activate=True,
            db_path=tmp_path / "audit.db",
        )
    assert not isinstance(exc.value, PromotionBlocked)


def test_accept_scored_blocked_raises_promotion_blocked(tmp_path, write_backtest_result):
    """Tripped floor → PromotionBlocked even with a ROBUST verdict; no card."""
    scored = _score_once(tmp_path)
    reg = _registry(tmp_path)
    write_backtest_result(Path(scored["report_folder"]), net_pnl=-100.0)
    with pytest.raises(PromotionBlocked) as exc:
        approve_strategy.accept_scored(
            base_name="smoke-amzn", symbol="AMZN", timeframe="1H",
            report_folder=scored["report_folder"], verdict="ROBUST",
            dsr_probability=0.5,
            scoring_run_id=scored["scoring_run_id"], registry=reg,
            pine_archive_root=tmp_path / "pine_archive",
            reports_root=tmp_path / "reports", activate=True,
            db_path=tmp_path / "audit.db",
        )
    assert "NEG_NET_EXPECTANCY" in exc.value.blockers
    assert reg.get("smoke-amzn-v1") is None


def test_accept_scored_missing_backtest_result_fails_closed(tmp_path):
    scored = _score_once(tmp_path)
    reg = _registry(tmp_path)
    (Path(scored["report_folder"]) / "backtest_result.json").unlink()
    with pytest.raises(ActivationGateFailed, match="backtest_result.json"):
        approve_strategy.accept_scored(
            base_name="smoke-amzn", symbol="AMZN", timeframe="1H",
            report_folder=scored["report_folder"], verdict="ROBUST",
            dsr_probability=scored["dsr_probability"],
            scoring_run_id=scored["scoring_run_id"], registry=reg,
            pine_archive_root=tmp_path / "pine_archive",
            reports_root=tmp_path / "reports", activate=True,
        )


# ─── accept_python_run (Python path) ────────────────────────────────────

def _py_folder(tmp_path, write_backtest_result, *, net_pnl=240.0) -> Path:
    rf = tmp_path / "reports" / "frog_run"
    write_backtest_result(rf, net_pnl=net_pnl)
    return rf


def test_accept_python_confirm_does_not_pass_blocked(tmp_path, write_backtest_result):
    """confirm_non_robust=True is powerless against a tripped floor."""
    rf = _py_folder(tmp_path, write_backtest_result, net_pnl=-100.0)
    reg = _registry(tmp_path)
    with pytest.raises(PromotionBlocked) as exc:
        approve_strategy.accept_python_run(
            base_name="frog", symbol="AAPL", timeframe="1D",
            report_folder=str(rf), verdict="FRAGILE",
            dsr_probability=None, scoring_run_id="run-1", strategy="frog",
            registry=reg, reports_root=tmp_path / "reports",
            activate=True, confirm_non_robust=True,
            db_path=tmp_path / "audit.db",
        )
    assert "NEG_NET_EXPECTANCY" in exc.value.blockers
    assert reg.get("frog-v1") is None


def test_accept_python_confirm_passes_advisory_and_stamps_route(tmp_path, write_backtest_result):
    """confirm_non_robust=True still overrides ADVISORY; card carries the route."""
    rf = _py_folder(tmp_path, write_backtest_result, net_pnl=240.0)
    reg = _registry(tmp_path)
    card = approve_strategy.accept_python_run(
        base_name="frog", symbol="AAPL", timeframe="1D",
        report_folder=str(rf), verdict="FRAGILE",
        dsr_probability=None, scoring_run_id="run-1", strategy="frog",
        registry=reg, reports_root=tmp_path / "reports",
        activate=True, confirm_non_robust=True,
        db_path=tmp_path / "audit.db",
    )
    assert card["status"] == "enabled"
    assert card["promotion_route"] == "ADVISORY"


def test_accept_python_missing_backtest_result_fails_closed(tmp_path):
    rf = tmp_path / "reports" / "frog_empty"
    rf.mkdir(parents=True)
    reg = _registry(tmp_path)
    with pytest.raises(ActivationGateFailed, match="backtest_result.json"):
        approve_strategy.accept_python_run(
            base_name="frog", symbol="AAPL", timeframe="1D",
            report_folder=str(rf), verdict="ROBUST",
            dsr_probability=None, scoring_run_id="run-1", strategy="frog",
            registry=reg, reports_root=tmp_path / "reports",
            activate=True, confirm_non_robust=True,
        )


# ─── Handler level ──────────────────────────────────────────────────────

def test_handler_blocked_returns_422_with_state_and_blockers(
    tmp_path, monkeypatch, write_backtest_result,
):
    """POST .../activate on a strategy whose floor trips → 422 with
    state=='BLOCKED' and the DISQ_* tokens in body['blockers']. The audit
    verdict is forced ROBUST so the floor (not the verdict) must do the
    blocking."""
    from tradelab.web import handlers
    monkeypatch.setattr(handlers, "_db_path", lambda: tmp_path / "audit.db")
    monkeypatch.setattr(handlers, "_reports_root", lambda: tmp_path / "reports")
    monkeypatch.setattr(handlers, "_pine_archive_root", lambda: tmp_path / "pine_archive")
    monkeypatch.setattr(handlers, "_cards_path", lambda: tmp_path / "cards.json")

    raw, status = handlers.handle_post_with_status(
        "/tradelab/score",
        json.dumps({
            "csv_text": SMOKE_CSV.read_text(encoding="utf-8-sig"),
            "pine_source": "// pine source",
            "symbol": "AMZN", "base_name": "smoke-amzn", "timeframe": "1H",
        }).encode(),
    )
    assert status == 200, raw
    scored = json.loads(raw)["data"]

    conn = sqlite3.connect(str(tmp_path / "audit.db"))
    conn.execute("UPDATE runs SET verdict = ? WHERE run_id = ?",
                 ("ROBUST", scored["scoring_run_id"]))
    conn.commit()
    conn.close()

    # Trip the floor while keeping symbol/timeframe the endpoint reads.
    write_backtest_result(Path(scored["report_folder"]), net_pnl=-100.0,
                          symbol="AMZN", timeframe="1H")

    raw, status = handlers.handle_post_with_status(
        "/tradelab/strategies/smoke-amzn/activate", b"{}")
    body = json.loads(raw)
    assert status == 422
    assert body["state"] == "BLOCKED"
    assert "NEG_NET_EXPECTANCY" in body["blockers"]


# ─── Step 3.5: server-side DSR resolution (close the floor bypass) ───────
#
# /tradelab/accept and /tradelab/strategies/accept take dsr_probability from
# the CLIENT payload. The floor's DSR_NEGATIVE blocker trips only on dsr < 0;
# dsr=None legitimately does NOT trip (missing-data semantics). So a payload
# that OMITS dsr_probability (-> None) or SPOOFS a clean value bypasses the
# floor. Fix: on the activation gate path, resolve dsr server-side from the
# audit row keyed by scoring_run_id and route on THAT — never the client value
# when a stored value exists (decision (b): on lookup failure fall back to
# None, never the client value). These assert at the HANDLER level because P1
# (handler-side placement) is where the wiring lives.


def _score_via_handler(tmp_path, monkeypatch, base_name="smoke-amzn"):
    """POST /tradelab/score through the handler; returns (handlers, data)."""
    from tradelab.web import handlers
    monkeypatch.setattr(handlers, "_db_path", lambda: tmp_path / "audit.db")
    monkeypatch.setattr(handlers, "_reports_root", lambda: tmp_path / "reports")
    monkeypatch.setattr(handlers, "_pine_archive_root", lambda: tmp_path / "pine_archive")
    monkeypatch.setattr(handlers, "_cards_path", lambda: tmp_path / "cards.json")
    raw, status = handlers.handle_post_with_status(
        "/tradelab/score",
        json.dumps({
            "csv_text": SMOKE_CSV.read_text(encoding="utf-8-sig"),
            "pine_source": "// pine source",
            "symbol": "AMZN", "base_name": base_name, "timeframe": "1H",
        }).encode(),
    )
    assert status == 200, raw
    return handlers, json.loads(raw)["data"]


def _set_stored_dsr(db_path: Path, run_id: str, dsr, verdict="ROBUST"):
    """Force the audit row's stored dsr_probability (and verdict so the floor,
    not the verdict, does the blocking). dsr=None writes SQL NULL."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE runs SET dsr_probability = ?, verdict = ? WHERE run_id = ?",
        (dsr, verdict, run_id),
    )
    conn.commit()
    conn.close()


def _accept_body(scored, *, include_dsr=None, **overrides):
    body = {
        "base_name": "smoke-amzn", "symbol": "AMZN", "timeframe": "1H",
        "report_folder": scored["report_folder"],
        "verdict": "ROBUST",
        "scoring_run_id": scored["scoring_run_id"],
        "activate": True,
    }
    if include_dsr is not None:
        body["dsr_probability"] = include_dsr
    body.update(overrides)
    return json.dumps(body).encode()


def test_accept_omission_bypass_dead(tmp_path, monkeypatch, write_backtest_result):
    """THE test: POST /tradelab/accept with activate=True, a scoring_run_id
    whose audit row stores dsr=-0.2, and dsr_probability OMITTED -> 422,
    state==BLOCKED, DSR_NEGATIVE in blockers. net_pnl is positive so ONLY the
    server-resolved dsr can block."""
    handlers, scored = _score_via_handler(tmp_path, monkeypatch)
    _set_stored_dsr(tmp_path / "audit.db", scored["scoring_run_id"], -0.2)
    write_backtest_result(Path(scored["report_folder"]), net_pnl=500.0,
                          symbol="AMZN", timeframe="1H")

    raw, status = handlers.handle_post_with_status(
        "/tradelab/accept", _accept_body(scored))  # dsr OMITTED
    body = json.loads(raw)
    assert status == 422, raw
    assert body["state"] == "BLOCKED"
    assert "DSR_NEGATIVE" in body["blockers"]


def test_accept_spoofing_bypass_dead(tmp_path, monkeypatch, write_backtest_result, caplog):
    """Client SPOOFS a clean dsr=0.5 over a stored -0.2 -> still BLOCKED on the
    stored value; a warning is logged that the client value was discarded."""
    handlers, scored = _score_via_handler(tmp_path, monkeypatch)
    _set_stored_dsr(tmp_path / "audit.db", scored["scoring_run_id"], -0.2)
    write_backtest_result(Path(scored["report_folder"]), net_pnl=500.0,
                          symbol="AMZN", timeframe="1H")

    with caplog.at_level("WARNING"):
        raw, status = handlers.handle_post_with_status(
            "/tradelab/accept", _accept_body(scored, include_dsr=0.5))
    body = json.loads(raw)
    assert status == 422, raw
    assert body["state"] == "BLOCKED"
    assert "DSR_NEGATIVE" in body["blockers"]
    assert "dsr" in caplog.text.lower()


def test_accept_clean_stored_value_passes(tmp_path, monkeypatch, write_backtest_result):
    """Stored dsr=0.8, ROBUST verdict, clean floor -> CLEAR, activation
    proceeds (200, card enabled)."""
    handlers, scored = _score_via_handler(tmp_path, monkeypatch)
    _set_stored_dsr(tmp_path / "audit.db", scored["scoring_run_id"], 0.8)
    write_backtest_result(Path(scored["report_folder"]), net_pnl=500.0,
                          symbol="AMZN", timeframe="1H")

    raw, status = handlers.handle_post_with_status(
        "/tradelab/accept", _accept_body(scored))
    assert status == 200, raw
    data = json.loads(raw)["data"]
    assert data["card_id"] == "smoke-amzn-v1"
    assert "activated_at" in data


def test_accept_missing_stored_dsr_preserves_none_semantics(
    tmp_path, monkeypatch, write_backtest_result,
):
    """No stored dsr anywhere (NULL) -> floor sees None, does NOT trip
    DSR_NEGATIVE; ROBUST + clean floor -> CLEAR (200). Decision (b): legitimate
    missing data still passes."""
    handlers, scored = _score_via_handler(tmp_path, monkeypatch)
    _set_stored_dsr(tmp_path / "audit.db", scored["scoring_run_id"], None)
    write_backtest_result(Path(scored["report_folder"]), net_pnl=500.0,
                          symbol="AMZN", timeframe="1H")

    raw, status = handlers.handle_post_with_status(
        "/tradelab/accept", _accept_body(scored))
    assert status == 200, raw
    data = json.loads(raw)["data"]
    assert data["card_id"] == "smoke-amzn-v1"


# ── Python accept path (/tradelab/strategies/accept) — same treatment ───
#
# accept_python_run also takes a client scoring_run_id; condition (a) of the
# placement decision requires identical server-side resolution so the Python
# path is not a residual bypass surface. The runs-table row is seeded via
# score_csv (any path that writes an audit row works — get_run keys on run_id,
# not on how the row was created).


def _py_accept_body(scored, *, include_dsr=None, scoring_run_id=None, **overrides):
    body = {
        "base_name": "frog", "symbol": "AMZN", "timeframe": "1H",
        "report_folder": scored["report_folder"],
        "strategy": "frog",
        "verdict": "ROBUST",
        "scoring_run_id": scored["scoring_run_id"] if scoring_run_id is None else scoring_run_id,
        "activate": True,
    }
    if include_dsr is not None:
        body["dsr_probability"] = include_dsr
    body.update(overrides)
    return json.dumps(body).encode()


def test_accept_python_spoofing_bypass_dead(tmp_path, monkeypatch, write_backtest_result, caplog):
    """Python path: spoofed clean client dsr=0.5 over a stored -0.2 -> BLOCKED
    on the stored value (no residual surface on /tradelab/strategies/accept)."""
    handlers, scored = _score_via_handler(tmp_path, monkeypatch)
    _set_stored_dsr(tmp_path / "audit.db", scored["scoring_run_id"], -0.2)
    write_backtest_result(Path(scored["report_folder"]), net_pnl=500.0,
                          symbol="AMZN", timeframe="1H")

    with caplog.at_level("WARNING"):
        raw, status = handlers.handle_post_with_status(
            "/tradelab/strategies/accept", _py_accept_body(scored, include_dsr=0.5))
    body = json.loads(raw)
    assert status == 422, raw
    assert body["state"] == "BLOCKED"
    assert "DSR_NEGATIVE" in body["blockers"]
    assert "dsr" in caplog.text.lower()


def test_accept_python_unknown_run_id_drops_client_value(
    tmp_path, monkeypatch, write_backtest_result, caplog,
):
    """Decision (b), no-row half: scoring_run_id NOT in the runs table ->
    get_run returns None -> client dsr is DISCARDED (warning logged), floor
    sees None, ROBUST + clean floor -> CLEAR (200). The spoofed clean client
    value never reaches the floor — proven by the discard warning, not the
    (None-equivalent) 200."""
    handlers, scored = _score_via_handler(tmp_path, monkeypatch)
    write_backtest_result(Path(scored["report_folder"]), net_pnl=500.0,
                          symbol="AMZN", timeframe="1H")

    with caplog.at_level("WARNING"):
        raw, status = handlers.handle_post_with_status(
            "/tradelab/strategies/accept",
            _py_accept_body(scored, include_dsr=0.5, scoring_run_id="no-such-run-id"))
    assert status == 200, raw
    data = json.loads(raw)["data"]
    assert data["card_id"] == "frog-v1"
    assert "dsr" in caplog.text.lower()


def test_accept_omitted_run_id_blocks_activation(tmp_path, monkeypatch, write_backtest_result):
    """The other bypass door: OMITTING scoring_run_id on an activating accept
    skips server-side resolution entirely. The handler rejects it BEFORE
    resolution -> 422 with a plain {error} envelope (NOT the BLOCKED shape):
    'scoring_run_id required for activation'. Stored dsr=-0.2 must never get a
    chance to be dodged this way. (Mid-session scope addition, reviewing
    session 2026-06-03.)"""
    handlers, scored = _score_via_handler(tmp_path, monkeypatch)
    _set_stored_dsr(tmp_path / "audit.db", scored["scoring_run_id"], -0.2)
    write_backtest_result(Path(scored["report_folder"]), net_pnl=500.0,
                          symbol="AMZN", timeframe="1H")

    body = json.dumps({
        "base_name": "smoke-amzn", "symbol": "AMZN", "timeframe": "1H",
        "report_folder": scored["report_folder"],
        "verdict": "ROBUST",
        "activate": True,
        # scoring_run_id AND dsr_probability BOTH omitted
    }).encode()
    raw, status = handlers.handle_post_with_status("/tradelab/accept", body)
    parsed = json.loads(raw)
    assert status == 422, raw
    assert "scoring_run_id required for activation" in (parsed.get("error") or "")
    assert "state" not in parsed  # plain {error}, not the BLOCKED envelope


def test_accept_python_omitted_run_id_blocks_activation(tmp_path, monkeypatch, write_backtest_result):
    """Same omitted-run-id door closed on the Python path (condition a)."""
    handlers, scored = _score_via_handler(tmp_path, monkeypatch)
    write_backtest_result(Path(scored["report_folder"]), net_pnl=500.0,
                          symbol="AMZN", timeframe="1H")

    body = json.dumps({
        "base_name": "frog", "symbol": "AMZN", "timeframe": "1H",
        "report_folder": scored["report_folder"], "strategy": "frog",
        "verdict": "ROBUST", "activate": True,
        # scoring_run_id omitted
    }).encode()
    raw, status = handlers.handle_post_with_status("/tradelab/strategies/accept", body)
    parsed = json.loads(raw)
    assert status == 422, raw
    assert "scoring_run_id required for activation" in (parsed.get("error") or "")


# ─── WP5: ADVISORY gets its own 422 envelope (AdvisoryRefused) ───────────
#
# Step 3 routed ADVISORY distinctly but the gate still raised a plain
# ActivationGateFailed, so the handler returned a bare {error} 422 that a
# fail-closed refusal also produced — indistinguishable to the FE. WP5 adds
# AdvisoryRefused(ActivationGateFailed) so the handler can stamp
# state=="ADVISORY" ADDITIVELY (parallel to BLOCKED) while gate-message strings
# stay BYTE-IDENTICAL. _load_bt_metrics fail-closed refusals MUST stay plain
# ActivationGateFailed so they are never mislabeled reviewable.

# byte-frozen gate strings — must never drift:
_PINE_ADVISORY_MSG = "Activation requires ROBUST verdict; got FRAGILE"
_PY_ADVISORY_MSG = (
    "Verdict is FRAGILE (not ROBUST). "
    "Re-submit with confirm_non_robust=true to accept anyway."
)


def test_advisory_refused_is_activation_gate_subclass():
    cls = approve_strategy.AdvisoryRefused
    assert issubclass(cls, ActivationGateFailed)
    # sibling of PromotionBlocked — neither is an ancestor of the other
    assert not issubclass(cls, PromotionBlocked)
    assert not issubclass(PromotionBlocked, cls)


def test_accept_scored_advisory_raises_advisory_refused_byte_identical(tmp_path):
    scored = _score_once(tmp_path)
    reg = _registry(tmp_path)
    with pytest.raises(approve_strategy.AdvisoryRefused) as exc:
        approve_strategy.accept_scored(
            base_name="smoke-amzn", symbol="AMZN", timeframe="1H",
            report_folder=scored["report_folder"], verdict="FRAGILE",
            dsr_probability=scored["dsr_probability"],
            scoring_run_id=scored["scoring_run_id"], registry=reg,
            pine_archive_root=tmp_path / "pine_archive",
            reports_root=tmp_path / "reports", activate=True,
            db_path=tmp_path / "audit.db",
        )
    assert str(exc.value) == _PINE_ADVISORY_MSG


def test_accept_python_advisory_raises_advisory_refused_byte_identical(tmp_path, write_backtest_result):
    rf = _py_folder(tmp_path, write_backtest_result, net_pnl=240.0)
    reg = _registry(tmp_path)
    with pytest.raises(approve_strategy.AdvisoryRefused) as exc:
        approve_strategy.accept_python_run(
            base_name="frog", symbol="AAPL", timeframe="1D",
            report_folder=str(rf), verdict="FRAGILE",
            dsr_probability=None, scoring_run_id="run-1", strategy="frog",
            registry=reg, reports_root=tmp_path / "reports",
            activate=True, confirm_non_robust=False,
            db_path=tmp_path / "audit.db",
        )
    assert str(exc.value) == _PY_ADVISORY_MSG


def test_fail_closed_refusal_is_not_advisory(tmp_path):
    """The guard: a missing backtest_result.json is a FAIL-CLOSED refusal, not
    the ADVISORY route. It must raise plain ActivationGateFailed and must NOT be
    an AdvisoryRefused — else the handler would mislabel it state=='ADVISORY'."""
    scored = _score_once(tmp_path)
    reg = _registry(tmp_path)
    (Path(scored["report_folder"]) / "backtest_result.json").unlink()
    with pytest.raises(ActivationGateFailed) as exc:
        approve_strategy.accept_scored(
            base_name="smoke-amzn", symbol="AMZN", timeframe="1H",
            report_folder=scored["report_folder"], verdict="FRAGILE",
            dsr_probability=scored["dsr_probability"],
            scoring_run_id=scored["scoring_run_id"], registry=reg,
            pine_archive_root=tmp_path / "pine_archive",
            reports_root=tmp_path / "reports", activate=True,
            db_path=tmp_path / "audit.db",
        )
    assert not isinstance(exc.value, approve_strategy.AdvisoryRefused)


def test_handler_python_advisory_422_state_advisory(tmp_path, monkeypatch, write_backtest_result):
    """/tradelab/strategies/accept: FRAGILE + clean floor, no confirm -> 422
    state=='ADVISORY', NO blockers key, message byte-identical to the frozen
    Python-path gate string."""
    handlers, scored = _score_via_handler(tmp_path, monkeypatch)
    _set_stored_dsr(tmp_path / "audit.db", scored["scoring_run_id"], 0.5, verdict="FRAGILE")
    write_backtest_result(Path(scored["report_folder"]), net_pnl=500.0,
                          symbol="AMZN", timeframe="1H")
    raw, status = handlers.handle_post_with_status(
        "/tradelab/strategies/accept", _py_accept_body(scored, verdict="FRAGILE"))
    body = json.loads(raw)
    assert status == 422, raw
    assert body["state"] == "ADVISORY"
    assert "blockers" not in body
    assert body["error"] == _PY_ADVISORY_MSG


def test_handler_pine_advisory_422_state_advisory(tmp_path, monkeypatch, write_backtest_result):
    """/tradelab/accept (Pine path): FRAGILE + clean floor -> 422
    state=='ADVISORY' with the byte-identical Pine gate string."""
    handlers, scored = _score_via_handler(tmp_path, monkeypatch)
    _set_stored_dsr(tmp_path / "audit.db", scored["scoring_run_id"], 0.5, verdict="FRAGILE")
    write_backtest_result(Path(scored["report_folder"]), net_pnl=500.0,
                          symbol="AMZN", timeframe="1H")
    raw, status = handlers.handle_post_with_status(
        "/tradelab/accept", _accept_body(scored, verdict="FRAGILE"))
    body = json.loads(raw)
    assert status == 422, raw
    assert body["state"] == "ADVISORY"
    assert "blockers" not in body
    assert body["error"] == _PINE_ADVISORY_MSG


def test_handler_blocked_envelope_unchanged_by_wp5(tmp_path, monkeypatch, write_backtest_result):
    """Regression guard: BLOCKED still returns state=='BLOCKED' WITH blockers —
    WP5's ADVISORY addition must not alter the BLOCKED shape."""
    handlers, scored = _score_via_handler(tmp_path, monkeypatch)
    _set_stored_dsr(tmp_path / "audit.db", scored["scoring_run_id"], -0.2, verdict="ROBUST")
    write_backtest_result(Path(scored["report_folder"]), net_pnl=500.0,
                          symbol="AMZN", timeframe="1H")
    raw, status = handlers.handle_post_with_status(
        "/tradelab/strategies/accept", _py_accept_body(scored))
    body = json.loads(raw)
    assert status == 422, raw
    assert body["state"] == "BLOCKED"
    assert "DSR_NEGATIVE" in body["blockers"]
