"""WP4 Slice A — verdict-ledger logging at the accept chokepoint.

One durable row per *activate-path* promote decision, written at the accept
chokepoint (accept_scored / accept_python_run), keyed off the route that
route_promotion already returned. Capture-only: these tests read the rows back
via raw sqlite (mirroring tests/web/conftest.py's runs-table seeding) — the
production module stays write-only.

Decisions (settled with the human at stop point 1, 2026-06-06):
  (A) new `verdict_ledger` table in the existing audit DB.
  (B) log ALL activate-path decisions: CLEAR, ADVISORY, BLOCKED.
  (C) append-only — one row per accept attempt, no upsert.
  (D) columns: id, created_at, scoring_run_id, strategy_name, path, verdict,
      promotion_route, blockers_json, override_used, activated.

The routing logic itself (route_promotion, the floor, verdict.py) is fenced and
unchanged; these tests assert only that the decision is RECORDED.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tradelab.web import approve_strategy
from tradelab.web.approve_strategy import (
    ActivationGateFailed,
    PromotionBlocked,
)

SMOKE_CSV = Path("tests/io/fixtures/tv_export_amzn_smoke.csv")


# ─── helpers ────────────────────────────────────────────────────────────

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


def _read_ledger(db_path: Path) -> list[dict]:
    """Read every verdict_ledger row, ordered by id. Raw sqlite so the read
    path lives in the test, not in the capture-only production module."""
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute(
            "SELECT id, created_at, scoring_run_id, strategy_name, path, "
            "verdict, promotion_route, blockers_json, override_used, activated "
            "FROM verdict_ledger ORDER BY id"
        )
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        conn.close()
    return rows


def _py_folder(tmp_path, write_backtest_result, *, net_pnl=240.0) -> Path:
    rf = tmp_path / "reports" / "frog_run"
    write_backtest_result(rf, net_pnl=net_pnl)
    return rf


# ─── CLEAR (Pine, accept_scored) ────────────────────────────────────────

def test_clear_activation_writes_one_row(tmp_path):
    """A CLEAR activation writes exactly one ledger row: verdict ROBUST,
    promotion_route=CLEAR, empty blockers, override_used=False, activated=True."""
    scored = _score_once(tmp_path)
    reg = _registry(tmp_path)
    approve_strategy.accept_scored(
        base_name="smoke-amzn", symbol="AMZN", timeframe="1H",
        report_folder=scored["report_folder"], verdict="ROBUST",
        dsr_probability=scored["dsr_probability"],
        scoring_run_id=scored["scoring_run_id"], registry=reg,
        pine_archive_root=tmp_path / "pine_archive",
        reports_root=tmp_path / "reports", activate=True,
        db_path=tmp_path / "audit.db",
    )
    rows = _read_ledger(tmp_path / "audit.db")
    assert len(rows) == 1
    row = rows[0]
    assert row["strategy_name"] == "smoke-amzn"
    assert row["scoring_run_id"] == scored["scoring_run_id"]
    assert row["path"] == "pine"
    assert row["verdict"] == "ROBUST"
    assert row["promotion_route"] == "CLEAR"
    assert json.loads(row["blockers_json"]) == []
    assert row["override_used"] == 0
    assert row["activated"] == 1
    assert row["created_at"]  # non-empty timestamp


def test_non_activating_accept_writes_no_row(tmp_path):
    """A park-as-disabled accept (activate=False) computes no route, so it is
    out of scope for Slice A — no ledger row is written (table may not exist)."""
    scored = _score_once(tmp_path)
    reg = _registry(tmp_path)
    approve_strategy.accept_scored(
        base_name="smoke-amzn", symbol="AMZN", timeframe="1H",
        report_folder=scored["report_folder"], verdict="ROBUST",
        dsr_probability=scored["dsr_probability"],
        scoring_run_id=scored["scoring_run_id"], registry=reg,
        pine_archive_root=tmp_path / "pine_archive",
        reports_root=tmp_path / "reports", activate=False,
        db_path=tmp_path / "audit.db",
    )
    # Table created lazily on first write; with no activate-path write the
    # table is absent → zero rows.
    conn = sqlite3.connect(str(tmp_path / "audit.db"))
    try:
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='verdict_ledger'"
        ).fetchone()
    finally:
        conn.close()
    if exists:
        assert _read_ledger(tmp_path / "audit.db") == []


# ─── ADVISORY (Python, accept_python_run) ───────────────────────────────

def test_advisory_python_override_writes_row(tmp_path, write_backtest_result):
    """ADVISORY accept on the Python path WITH confirm_non_robust=True writes a
    row with promotion_route=ADVISORY, override_used=True, activated=True."""
    rf = _py_folder(tmp_path, write_backtest_result, net_pnl=240.0)
    reg = _registry(tmp_path)
    approve_strategy.accept_python_run(
        base_name="frog", symbol="AAPL", timeframe="1D",
        report_folder=str(rf), verdict="FRAGILE",
        dsr_probability=None, scoring_run_id="run-1", strategy="frog",
        registry=reg, reports_root=tmp_path / "reports",
        activate=True, confirm_non_robust=True,
        db_path=tmp_path / "audit.db",
    )
    rows = _read_ledger(tmp_path / "audit.db")
    assert len(rows) == 1
    row = rows[0]
    assert row["path"] == "python"
    assert row["verdict"] == "FRAGILE"
    assert row["promotion_route"] == "ADVISORY"
    assert row["override_used"] == 1
    assert row["activated"] == 1
    assert json.loads(row["blockers_json"]) == []


def test_advisory_pine_refused_writes_row(tmp_path):
    """ADVISORY on the Pine path is hard-blocked (no override). The refusal is
    still a decision: a row with promotion_route=ADVISORY, activated=False."""
    scored = _score_once(tmp_path)
    reg = _registry(tmp_path)
    with pytest.raises(ActivationGateFailed):
        approve_strategy.accept_scored(
            base_name="smoke-amzn", symbol="AMZN", timeframe="1H",
            report_folder=scored["report_folder"], verdict="FRAGILE",
            dsr_probability=scored["dsr_probability"],
            scoring_run_id=scored["scoring_run_id"], registry=reg,
            pine_archive_root=tmp_path / "pine_archive",
            reports_root=tmp_path / "reports", activate=True,
            db_path=tmp_path / "audit.db",
        )
    rows = _read_ledger(tmp_path / "audit.db")
    assert len(rows) == 1
    assert rows[0]["promotion_route"] == "ADVISORY"
    assert rows[0]["activated"] == 0
    assert rows[0]["override_used"] == 0


# ─── BLOCKED ────────────────────────────────────────────────────────────

def test_blocked_writes_row_with_blockers(tmp_path, write_backtest_result):
    """A tripped floor → PromotionBlocked. A row is written first:
    promotion_route=BLOCKED, the tripped blockers, activated=False. The
    blockers list round-trips through JSON serialization."""
    scored = _score_once(tmp_path)
    reg = _registry(tmp_path)
    write_backtest_result(Path(scored["report_folder"]), net_pnl=-100.0)
    with pytest.raises(PromotionBlocked):
        approve_strategy.accept_scored(
            base_name="smoke-amzn", symbol="AMZN", timeframe="1H",
            report_folder=scored["report_folder"], verdict="ROBUST",
            dsr_probability=0.5,
            scoring_run_id=scored["scoring_run_id"], registry=reg,
            pine_archive_root=tmp_path / "pine_archive",
            reports_root=tmp_path / "reports", activate=True,
            db_path=tmp_path / "audit.db",
        )
    rows = _read_ledger(tmp_path / "audit.db")
    assert len(rows) == 1
    row = rows[0]
    assert row["promotion_route"] == "BLOCKED"
    assert row["activated"] == 0
    # blockers round-trip: list in, equal list out.
    assert json.loads(row["blockers_json"]) == ["NEG_NET_EXPECTANCY"]


def test_blocked_handler_envelope_unchanged_and_row_written(
    tmp_path, monkeypatch, write_backtest_result,
):
    """BLOCKED logged on the 422 path leaves the response envelope byte-shape
    intact ({"error","data":null,"state":"BLOCKED","blockers":[...]}) AND a
    ledger row exists for the block."""
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
    write_backtest_result(Path(scored["report_folder"]), net_pnl=-100.0,
                          symbol="AMZN", timeframe="1H")

    raw, status = handlers.handle_post_with_status(
        "/tradelab/strategies/smoke-amzn/activate", b"{}")
    body = json.loads(raw)
    assert status == 422
    assert body["error"]
    assert body["data"] is None
    assert body["state"] == "BLOCKED"
    assert "NEG_NET_EXPECTANCY" in body["blockers"]

    rows = _read_ledger(tmp_path / "audit.db")
    assert len(rows) == 1
    assert rows[0]["promotion_route"] == "BLOCKED"
    assert json.loads(rows[0]["blockers_json"]) == ["NEG_NET_EXPECTANCY"]


# ─── Fail-open ──────────────────────────────────────────────────────────

def test_ledger_write_failure_is_fail_open(tmp_path, monkeypatch, caplog):
    """When the ledger write raises, the activation still SUCCEEDS — the
    exception does not propagate — and the failure is logged (loud, not
    swallowed). Observability must never become a promote-path failure mode."""
    import tradelab.audit.verdict_ledger as vl

    def _boom(**kwargs):
        raise RuntimeError("ledger DB exploded")

    monkeypatch.setattr(vl, "log_decision", _boom)

    scored = _score_once(tmp_path)
    reg = _registry(tmp_path)
    with caplog.at_level("ERROR"):
        result = approve_strategy.accept_scored(
            base_name="smoke-amzn", symbol="AMZN", timeframe="1H",
            report_folder=scored["report_folder"], verdict="ROBUST",
            dsr_probability=scored["dsr_probability"],
            scoring_run_id=scored["scoring_run_id"], registry=reg,
            pine_archive_root=tmp_path / "pine_archive",
            reports_root=tmp_path / "reports", activate=True,
            db_path=tmp_path / "audit.db",
        )
    # Activation succeeded despite the ledger blowing up.
    assert reg.get(result["card_id"]) is not None
    assert reg.get(result["card_id"])["status"] == "enabled"
    # And it was logged, not silently swallowed.
    assert "ledger" in caplog.text.lower()


# ─── Append-only (decision C) ───────────────────────────────────────────

def test_reaccept_appends_second_row(tmp_path):
    """Append-only: accepting twice writes TWO rows (registry bumps v1→v2;
    each accept is its own decision)."""
    scored = _score_once(tmp_path)
    reg = _registry(tmp_path)
    for _ in range(2):
        approve_strategy.accept_scored(
            base_name="smoke-amzn", symbol="AMZN", timeframe="1H",
            report_folder=scored["report_folder"], verdict="ROBUST",
            dsr_probability=scored["dsr_probability"],
            scoring_run_id=scored["scoring_run_id"], registry=reg,
            pine_archive_root=tmp_path / "pine_archive",
            reports_root=tmp_path / "reports", activate=True,
            db_path=tmp_path / "audit.db",
        )
    rows = _read_ledger(tmp_path / "audit.db")
    assert len(rows) == 2
    assert all(r["promotion_route"] == "CLEAR" for r in rows)
    assert rows[0]["scoring_run_id"] == rows[1]["scoring_run_id"]
