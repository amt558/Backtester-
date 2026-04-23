"""Tests for tradelab.web.failure_hint."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tradelab.web.failure_hint import extract_failure_hint


def _write_progress(tmp_path: Path, job_id: str, events: list) -> None:
    d = tmp_path / ".cache" / "jobs" / job_id
    d.mkdir(parents=True)
    (d / "progress.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events), encoding="utf-8"
    )


def test_no_progress_log_falls_back_to_exit_code(tmp_path):
    hint = extract_failure_hint("nonexistent", exit_code=1, cache_root=tmp_path / ".cache")
    assert "Python exception" in hint


def test_parses_last_error_event(tmp_path):
    _write_progress(tmp_path, "j1", [
        {"event": "stage", "stage": "download", "ok": True},
        {"event": "error", "error_type": "KeyError", "message": "missing 'close' column"},
    ])
    hint = extract_failure_hint("j1", exit_code=1, cache_root=tmp_path / ".cache")
    assert hint is not None
    assert "KeyError" in hint
    assert "missing 'close'" in hint


def test_nosymbolsprovided_maps_to_preflight_hint(tmp_path):
    _write_progress(tmp_path, "j2", [
        {"event": "error", "error_type": "NoSymbolsProvided", "message": "pass --symbols or --universe"},
    ])
    hint = extract_failure_hint("j2", exit_code=2, cache_root=tmp_path / ".cache")
    assert "preflight" in hint.lower()


def test_exit_code_cancelled(tmp_path):
    hint = extract_failure_hint("nonexistent", exit_code=-1073741510, cache_root=tmp_path / ".cache")
    assert "cancelled" in hint.lower()
