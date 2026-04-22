"""Tests for the --progress-log JSONL emitter contract.

Owned by tradelab.web.progress_events but tested here because the CLI is
the consumer. Backward-compat (no flag) tested via integration in
tests/web/test_handlers_jobs.py.
"""
from __future__ import annotations

import json

from tradelab.web.progress_events import ProgressEmitter, parse_event


def test_emitter_writes_jsonl_and_each_line_is_parseable(tmp_path):
    log = tmp_path / "progress.jsonl"
    em = ProgressEmitter(log)
    em.start("backtest")
    em.complete("backtest", duration_s=1.4)
    em.start("monte_carlo")
    em.progress("monte_carlo", i=100, total=500)
    em.done(exit_code=0)
    em.close()

    lines = log.read_text().splitlines()
    assert len(lines) == 5
    for ln in lines:
        ev = parse_event(ln)
        assert ev is not None
        assert "type" in ev
        assert "ts" in ev


def test_emitter_with_empty_path_is_noop_no_file_created(tmp_path):
    """Backward compat: when --progress-log is absent (empty string), emit() does nothing."""
    em = ProgressEmitter("")
    em.start("backtest")
    em.done()
    em.close()

    # No new files in tmp_path (we passed empty string, not a tmp path)
    assert list(tmp_path.iterdir()) == []


def test_emitter_is_line_buffered_event_visible_before_close(tmp_path):
    """Tail loop should see each event immediately, not at process exit."""
    log = tmp_path / "progress.jsonl"
    em = ProgressEmitter(log)
    em.start("backtest")
    # Read while emitter is still open — would fail if buffered until close()
    content = log.read_text()
    assert "backtest" in content
    em.close()


def test_parse_event_tolerates_corrupted_lines():
    assert parse_event('{"type":"start","stage":"backtest"}') is not None
    assert parse_event('not json at all') is None
    assert parse_event('{"missing_type":true}') is None
    assert parse_event('') is None
    assert parse_event('   ') is None
    # Forward-compat: unknown type + extra fields still parse
    ev = parse_event('{"type":"future_thing","extra":42}')
    assert ev is not None
    assert ev["type"] == "future_thing"


def test_parse_event_rejects_non_object_json():
    """JSON arrays/scalars at top level should be rejected."""
    assert parse_event('[1,2,3]') is None
    assert parse_event('"string"') is None
    assert parse_event('42') is None
