"""Tests for the GET endpoints registered by Slice 7a daily_summary.

T9 — /tradelab/live/digest/preview (renders today's digest HTML for the FE)
T10 — /tradelab/live/digest/state (last-sent + attempts state for the FE)

NOTE: spec template for these tests was written against an older dispatcher
signature (`handle_get(path, kwargs)`). The actual signature is
`handle_get_with_status(path_with_query) -> Tuple[str, int]` — these tests
exercise that real signature, not the planned-but-nonexistent one.
"""
import json
from unittest.mock import patch

import pytest

from tradelab.web import handlers


# ─── T9: GET /tradelab/live/digest/preview ───────────────────────────


def test_digest_preview_returns_html_200():
    with patch("tradelab.live.daily_summary.render",
               return_value=("test subject", "<div>preview body</div>")):
        body, status = handlers.handle_digest_preview_get()
    assert status == 200
    assert "<div>preview body</div>" in body


def test_digest_preview_render_error_returns_500_with_envelope():
    with patch("tradelab.live.daily_summary.render",
               side_effect=RuntimeError("simulated render failure")):
        body, status = handlers.handle_digest_preview_get()
    assert status == 500
    payload = json.loads(body)
    # _err() envelope shape: {"error": msg, "data": None}
    assert payload["error"] is not None
    assert "RuntimeError" in payload["error"]
    assert "simulated render failure" in payload["error"]
    assert payload["data"] is None


def test_get_dispatcher_routes_preview():
    """The dispatcher (handle_get_with_status) must route the preview path."""
    with patch("tradelab.live.daily_summary.render",
               return_value=("s", "<x>html body</x>")):
        body, status = handlers.handle_get_with_status("/tradelab/live/digest/preview")
    assert status == 200
    assert "<x>html body</x>" in body


def test_digest_preview_passes_aware_now_to_render():
    """render() requires an aware datetime per daily_summary.tick contract.
    Preview endpoint must build one in ET, not naive."""
    captured = {}

    def fake_render(now):
        captured["now"] = now
        return ("s", "<p>ok</p>")

    with patch("tradelab.live.daily_summary.render", side_effect=fake_render):
        body, status = handlers.handle_digest_preview_get()
    assert status == 200
    assert captured["now"].tzinfo is not None
    # ET zone string ends with "America/New_York" or DST abbreviation
    assert str(captured["now"].tzinfo) == "America/New_York"


# ─── T10: GET /tradelab/live/digest/state ────────────────────────────


def test_digest_state_returns_envelope_with_state(tmp_path, monkeypatch):
    """State file present → envelope wraps the parsed dict."""
    state_file = tmp_path / "digest_state.json"
    state_file.write_text(json.dumps({
        "last_sent_date": "2026-04-27",
        "last_sent_failed": False,
        "last_attempted_at": "2026-04-27T16:30:00-04:00",
        "attempts_today": 1,
    }), encoding="utf-8")
    from tradelab.live import daily_summary
    monkeypatch.setattr(daily_summary, "STATE_PATH", state_file)

    body, status = handlers.handle_digest_state_get()
    assert status == 200
    payload = json.loads(body)
    assert payload["error"] is None
    assert payload["data"]["last_sent_date"] == "2026-04-27"
    assert payload["data"]["attempts_today"] == 1


def test_digest_state_missing_file_returns_null_data(tmp_path, monkeypatch):
    """Missing state file → 200 with data=None (missing is not an error)."""
    from tradelab.live import daily_summary
    monkeypatch.setattr(daily_summary, "STATE_PATH", tmp_path / "does_not_exist.json")

    body, status = handlers.handle_digest_state_get()
    assert status == 200
    payload = json.loads(body)
    assert payload["error"] is None
    assert payload["data"] is None


def test_digest_state_corrupt_file_returns_null_data(tmp_path, monkeypatch):
    """Corrupt JSON in state file → 200 with data=None.

    `_read_state()` catches JSONDecodeError and returns {}; the handler
    surfaces that as null. This test pins the contract so a future change
    that surfaces corrupt-state as a 500 won't slip in unnoticed.
    """
    state_file = tmp_path / "digest_state.json"
    state_file.write_text("{not valid json", encoding="utf-8")
    from tradelab.live import daily_summary
    monkeypatch.setattr(daily_summary, "STATE_PATH", state_file)

    body, status = handlers.handle_digest_state_get()
    assert status == 200
    payload = json.loads(body)
    assert payload["error"] is None
    assert payload["data"] is None


def test_get_dispatcher_routes_state(tmp_path, monkeypatch):
    """The dispatcher (handle_get_with_status) must route the state path."""
    state_file = tmp_path / "digest_state.json"
    state_file.write_text(json.dumps({
        "last_sent_date": "2026-04-27",
        "last_sent_failed": False,
        "last_attempted_at": "2026-04-27T16:30:00-04:00",
        "attempts_today": 2,
    }), encoding="utf-8")
    from tradelab.live import daily_summary
    monkeypatch.setattr(daily_summary, "STATE_PATH", state_file)

    body, status = handlers.handle_get_with_status("/tradelab/live/digest/state")
    assert status == 200
    payload = json.loads(body)
    assert payload["error"] is None
    assert payload["data"]["last_sent_date"] == "2026-04-27"
    assert payload["data"]["attempts_today"] == 2
