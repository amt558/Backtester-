"""Handler-level tests for POST /tradelab/score and POST /tradelab/accept."""
from __future__ import annotations

import json
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
    # New helpers (defined in handlers.py Task 5, Step 3)
    monkeypatch.setattr(handlers, "_pine_archive_root", lambda: tmp_path / "pine_archive")
    monkeypatch.setattr(handlers, "_cards_path", lambda: tmp_path / "cards.json")
    return tmp_path


def _post(path: str, payload: dict):
    body = json.dumps(payload).encode()
    raw, status = handlers.handle_post_with_status(path, body)
    return json.loads(raw), status


# ─── Score endpoint ────────────────────────────────────────────────

def test_score_happy(handlers_with_tmp_roots, smoke_csv_text):
    body, status = _post("/tradelab/score", {
        "csv_text": smoke_csv_text,
        "pine_source": "// pine",
        "symbol": "AMZN",
        "base_name": "smoke-amzn",
        "timeframe": "1H",
    })
    assert status == 200
    assert body["error"] is None
    data = body["data"]
    assert data["verdict"] in ("ROBUST", "INCONCLUSIVE", "FRAGILE")
    assert data["scoring_run_id"]
    assert data["report_folder"]


@pytest.mark.parametrize("missing", ["csv_text", "symbol", "base_name", "timeframe"])
def test_score_400_on_missing_field(handlers_with_tmp_roots, smoke_csv_text, missing):
    payload = {
        "csv_text": smoke_csv_text, "pine_source": None,
        "symbol": "AMZN", "base_name": "smoke-amzn", "timeframe": "1H",
    }
    payload.pop(missing)
    body, status = _post("/tradelab/score", payload)
    assert status == 400
    assert missing in body["error"]


@pytest.mark.parametrize("bad_name", ["Bad-Name", "x", "has space", "UPPER", "a" * 49])
def test_score_400_on_bad_base_name(handlers_with_tmp_roots, smoke_csv_text, bad_name):
    body, status = _post("/tradelab/score", {
        "csv_text": smoke_csv_text, "pine_source": None,
        "symbol": "AMZN", "base_name": bad_name, "timeframe": "1H",
    })
    assert status == 400
    assert "base_name" in body["error"]


@pytest.mark.parametrize("bad_sym", ["amzn", "AMZN1", "TOOLONGSYM", "A B"])
def test_score_400_on_bad_symbol(handlers_with_tmp_roots, smoke_csv_text, bad_sym):
    body, status = _post("/tradelab/score", {
        "csv_text": smoke_csv_text, "pine_source": None,
        "symbol": bad_sym, "base_name": "smoke", "timeframe": "1H",
    })
    assert status == 400
    assert "symbol" in body["error"]


def test_score_400_on_bad_timeframe(handlers_with_tmp_roots, smoke_csv_text):
    body, status = _post("/tradelab/score", {
        "csv_text": smoke_csv_text, "pine_source": None,
        "symbol": "AMZN", "base_name": "smoke", "timeframe": "2D",
    })
    assert status == 400
    assert "timeframe" in body["error"]


def test_score_400_on_unparseable_csv(handlers_with_tmp_roots):
    body, status = _post("/tradelab/score", {
        "csv_text": "not a csv",
        "pine_source": None,
        "symbol": "AMZN", "base_name": "smoke", "timeframe": "1H",
    })
    assert status == 400
    assert body["error"]


# ─── Accept endpoint ────────────────────────────────────────────────

def test_accept_happy(handlers_with_tmp_roots, smoke_csv_text):
    # First, score to produce a report folder
    score_body, _ = _post("/tradelab/score", {
        "csv_text": smoke_csv_text, "pine_source": "// pine",
        "symbol": "AMZN", "base_name": "smoke-amzn", "timeframe": "1H",
    })
    rf = score_body["data"]["report_folder"]

    body, status = _post("/tradelab/accept", {
        "base_name": "smoke-amzn", "symbol": "AMZN",
        "timeframe": "1H", "report_folder": rf,
    })
    assert status == 200
    assert body["error"] is None
    assert body["data"]["card_id"] == "smoke-amzn-v1"
    assert body["data"]["secret"]
    assert body["data"]["pine_archive_path"]


def test_accept_404_when_report_folder_missing(handlers_with_tmp_roots):
    body, status = _post("/tradelab/accept", {
        "base_name": "nonexistent-base", "symbol": "AMZN",
        "timeframe": "1H",
        "report_folder": str(handlers_with_tmp_roots / "reports" / "nonexistent_123"),
    })
    assert status == 404
    assert "report folder" in body["error"]


def test_accept_400_when_pine_missing(handlers_with_tmp_roots, smoke_csv_text):
    score_body, _ = _post("/tradelab/score", {
        "csv_text": smoke_csv_text, "pine_source": None,
        "symbol": "AMZN", "base_name": "smoke-amzn", "timeframe": "1H",
    })
    rf = score_body["data"]["report_folder"]
    body, status = _post("/tradelab/accept", {
        "base_name": "smoke-amzn", "symbol": "AMZN",
        "timeframe": "1H", "report_folder": rf,
    })
    assert status == 400
    assert "strategy.pine" in body["error"]


def test_accept_400_on_missing_field(handlers_with_tmp_roots):
    body, status = _post("/tradelab/accept", {
        "base_name": "smoke-amzn", "symbol": "AMZN", "timeframe": "1H",
        # missing report_folder
    })
    assert status == 400
    assert "report_folder" in body["error"]


def test_accept_two_accepts_bumps_version(handlers_with_tmp_roots, smoke_csv_text):
    """Accept after Accept → -v2."""
    for expected in ("smoke-amzn-v1", "smoke-amzn-v2"):
        score_body, _ = _post("/tradelab/score", {
            "csv_text": smoke_csv_text, "pine_source": "// pine",
            "symbol": "AMZN", "base_name": "smoke-amzn", "timeframe": "1H",
        })
        accept_body, status = _post("/tradelab/accept", {
            "base_name": "smoke-amzn", "symbol": "AMZN",
            "timeframe": "1H", "report_folder": score_body["data"]["report_folder"],
        })
        assert status == 200
        assert accept_body["data"]["card_id"] == expected
