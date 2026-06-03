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
