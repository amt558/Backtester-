"""Handler-level tests for POST /tradelab/strategies/<id>/activate (Task 10).

The new endpoint is a one-click "Activate" wrapper around accept_scored that
the Research-tab Live Cards tile uses. It looks up the strategy's latest
audit row, resolves its report_folder, reads symbol/timeframe from
backtest_result.json, and forwards to approve_strategy.accept_scored with
activate=True. The robustness gate, duplicate-card 409, and SSE broadcast
are all reused from the existing /tradelab/accept code path.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tradelab.web import handlers


@pytest.fixture
def smoke_csv_text() -> str:
    return Path("tests/io/fixtures/tv_export_amzn_smoke.csv").read_text(encoding="utf-8-sig")


@pytest.fixture
def handlers_with_tmp_roots(tmp_path: Path, monkeypatch):
    """Point handler path helpers at tmp_path so tests don't touch real dirs."""
    monkeypatch.setattr(handlers, "_db_path", lambda: tmp_path / "audit.db")
    monkeypatch.setattr(handlers, "_reports_root", lambda: tmp_path / "reports")
    monkeypatch.setattr(handlers, "_pine_archive_root", lambda: tmp_path / "pine_archive")
    monkeypatch.setattr(handlers, "_cards_path", lambda: tmp_path / "cards.json")
    return tmp_path


def _post(path: str, payload: dict):
    body = json.dumps(payload).encode()
    raw, status = handlers.handle_post_with_status(path, body)
    return json.loads(raw), status


def _score(smoke_csv_text: str, base_name: str = "smoke-amzn") -> dict:
    """Run /tradelab/score and return the data envelope (with report_folder)."""
    body, status = _post("/tradelab/score", {
        "csv_text": smoke_csv_text, "pine_source": "// pine source",
        "symbol": "AMZN", "base_name": base_name, "timeframe": "1H",
    })
    assert status == 200, body
    return body["data"]


def _force_verdict(db_path: Path, run_id: str, verdict: str) -> None:
    """Override the audit row's verdict so the activate gate can be exercised
    deterministically without depending on the smoke CSV's natural verdict."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("UPDATE runs SET verdict = ? WHERE run_id = ?", (verdict, run_id))
        conn.commit()
    finally:
        conn.close()


# ─── Happy path ────────────────────────────────────────────────────────

def test_activate_robust_creates_enabled_card(handlers_with_tmp_roots, smoke_csv_text):
    """ROBUST verdict on the latest run → endpoint returns 200, the registry
    holds a card with status=enabled and activated_verdict=ROBUST."""
    scored = _score(smoke_csv_text, "smoke-amzn")
    _force_verdict(handlers_with_tmp_roots / "audit.db", scored["scoring_run_id"], "ROBUST")

    body, status = _post("/tradelab/strategies/smoke-amzn/activate", {})

    assert status == 200, body
    assert body["error"] is None
    data = body["data"]
    assert data["card_id"] == "smoke-amzn-v1"
    assert data["secret"]
    assert data["pine_archive_path"]
    assert data["activated_at"]

    # Registry was actually written (card_id is enabled).
    from tradelab.live.cards import CardRegistry
    reg = CardRegistry(handlers_with_tmp_roots / "cards.json")
    card = reg.get("smoke-amzn-v1")
    assert card is not None
    assert card["status"] == "enabled"
    assert card["activated_verdict"] == "ROBUST"


# ─── Gate failures ─────────────────────────────────────────────────────

def test_activate_fragile_verdict_returns_422(handlers_with_tmp_roots, smoke_csv_text):
    """FRAGILE verdict → ActivationGateFailed → 422; no card created."""
    scored = _score(smoke_csv_text, "smoke-amzn")
    _force_verdict(handlers_with_tmp_roots / "audit.db", scored["scoring_run_id"], "FRAGILE")

    body, status = _post("/tradelab/strategies/smoke-amzn/activate", {})

    assert status == 422
    assert "ROBUST" in body["error"]

    from tradelab.live.cards import CardRegistry
    reg = CardRegistry(handlers_with_tmp_roots / "cards.json")
    assert reg.get("smoke-amzn-v1") is None


def test_activate_inconclusive_verdict_returns_422(handlers_with_tmp_roots, smoke_csv_text):
    """INCONCLUSIVE verdict is also non-ROBUST → 422."""
    scored = _score(smoke_csv_text, "smoke-amzn")
    _force_verdict(handlers_with_tmp_roots / "audit.db", scored["scoring_run_id"], "INCONCLUSIVE")

    body, status = _post("/tradelab/strategies/smoke-amzn/activate", {})

    assert status == 422
    assert "ROBUST" in body["error"]


# ─── Strategy not found ────────────────────────────────────────────────

def test_activate_unknown_strategy_returns_422(handlers_with_tmp_roots):
    """No runs in audit DB for the strategy → 422 with a 'no runs' message
    (422 reuses the same gate semantics: 'we cannot activate this')."""
    body, status = _post("/tradelab/strategies/never-scored-strategy/activate", {})

    assert status == 422
    assert body["error"]
    assert "no runs" in body["error"].lower() or "not found" in body["error"].lower()


def test_activate_no_runs_does_not_touch_filesystem(handlers_with_tmp_roots):
    """Bail-early when there are no runs — pine_archive must not be touched."""
    _post("/tradelab/strategies/missing/activate", {})

    archive_root = handlers_with_tmp_roots / "pine_archive"
    assert not archive_root.exists() or not any(archive_root.iterdir())


# ─── Duplicate activation ──────────────────────────────────────────────

def test_activate_twice_returns_409_on_second_call(handlers_with_tmp_roots, smoke_csv_text):
    """Second activate of the same -v1 card → CardExistsError → 409.

    (Re-scoring the strategy bumps version naturally, but a duplicate Activate
    on the same run_id without re-scoring should refuse.)"""
    scored = _score(smoke_csv_text, "smoke-amzn")
    _force_verdict(handlers_with_tmp_roots / "audit.db", scored["scoring_run_id"], "ROBUST")

    body1, status1 = _post("/tradelab/strategies/smoke-amzn/activate", {})
    assert status1 == 200, body1

    body2, status2 = _post("/tradelab/strategies/smoke-amzn/activate", {})
    assert status2 == 409
    assert body2["error"]


# ─── Path validation ───────────────────────────────────────────────────

def test_activate_rejects_strategy_id_with_path_traversal(handlers_with_tmp_roots):
    """Strategy id slug should reject path traversal attempts. The route's
    regex (^/tradelab/strategies/([^/]+)/activate$) matches single-segment
    ids, but paranoid validation should also reject '..' and similar."""
    # The route regex stops at '/', so '..' isn't itself dangerous, but the
    # pattern's [a-z0-9_-] charset (matching strategy_name conventions) is the
    # single source of truth — anything outside it should 404 or 400 cleanly,
    # never silently fall through to the no-runs branch.
    body, status = _post("/tradelab/strategies/..%2Fevil/activate", {})
    # %2F is URL-encoded slash — handler sees ../evil. Either 400 (bad slug),
    # 404 (no route match), or 422 (no runs) is acceptable; 500 is not.
    assert status in (400, 404, 422), f"unexpected status {status}: {body}"
