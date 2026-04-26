"""Tests for daily_summary state file (digest_state.json)."""
import json
from pathlib import Path

import pytest

from tradelab.live import daily_summary


def test_read_state_missing_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(daily_summary, "STATE_PATH", tmp_path / "digest_state.json")
    state = daily_summary._read_state()
    assert state == {}


def test_read_state_corrupt_returns_empty(tmp_path, monkeypatch):
    p = tmp_path / "digest_state.json"
    p.write_text("not valid json", encoding="utf-8")
    monkeypatch.setattr(daily_summary, "STATE_PATH", p)
    assert daily_summary._read_state() == {}


def test_write_state_atomic(tmp_path, monkeypatch):
    p = tmp_path / "digest_state.json"
    monkeypatch.setattr(daily_summary, "STATE_PATH", p)
    daily_summary._write_state({"last_sent_date": "2026-04-27", "attempts_today": 0})
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["last_sent_date"] == "2026-04-27"
    assert data["attempts_today"] == 0


def test_write_state_then_read_roundtrip(tmp_path, monkeypatch):
    p = tmp_path / "digest_state.json"
    monkeypatch.setattr(daily_summary, "STATE_PATH", p)
    payload = {
        "last_sent_date": "2026-04-27",
        "last_sent_failed": False,
        "last_attempted_at": "2026-04-27T20:00:14+00:00",
        "attempts_today": 0,
    }
    daily_summary._write_state(payload)
    assert daily_summary._read_state() == payload
