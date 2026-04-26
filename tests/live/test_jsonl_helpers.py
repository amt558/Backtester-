"""Tests for _jsonl_helpers shared by daily_summary.render()."""
from datetime import date

import pytest

from tradelab.live import _jsonl_helpers


def test_read_today_lines_missing_file_returns_empty(tmp_path):
    p = tmp_path / "absent.jsonl"
    assert _jsonl_helpers.read_today_lines(p, date(2026, 4, 27)) == []


def test_read_today_lines_empty_file_returns_empty(tmp_path):
    p = tmp_path / "empty.jsonl"
    p.write_text("", encoding="utf-8")
    assert _jsonl_helpers.read_today_lines(p, date(2026, 4, 27)) == []


def test_read_today_lines_filters_by_today_in_et(tmp_path):
    p = tmp_path / "log.jsonl"
    # Two entries today (in ET), one yesterday
    p.write_text(
        '{"ts":"2026-04-27T13:30:00+00:00","x":1}\n'      # 09:30 ET on 04-27
        '{"ts":"2026-04-27T20:00:00+00:00","x":2}\n'      # 16:00 ET on 04-27
        '{"ts":"2026-04-26T20:00:00+00:00","x":3}\n',     # 16:00 ET on 04-26 — yesterday
        encoding="utf-8",
    )
    out = _jsonl_helpers.read_today_lines(p, date(2026, 4, 27))
    assert len(out) == 2
    assert [e["x"] for e in out] == [1, 2]


def test_read_today_lines_skips_corrupt_lines(tmp_path):
    p = tmp_path / "log.jsonl"
    p.write_text(
        '{"ts":"2026-04-27T13:30:00+00:00","x":1}\n'
        '{garbage not json}\n'
        '{"ts":"2026-04-27T14:00:00+00:00","x":2}\n',
        encoding="utf-8",
    )
    out = _jsonl_helpers.read_today_lines(p, date(2026, 4, 27))
    assert len(out) == 2
    assert [e["x"] for e in out] == [1, 2]


def test_read_today_lines_skips_entries_missing_ts(tmp_path):
    p = tmp_path / "log.jsonl"
    p.write_text(
        '{"ts":"2026-04-27T13:30:00+00:00","x":1}\n'
        '{"no_ts_field":true}\n'
        '{"ts":"not a timestamp","x":2}\n',
        encoding="utf-8",
    )
    out = _jsonl_helpers.read_today_lines(p, date(2026, 4, 27))
    assert len(out) == 1
    assert out[0]["x"] == 1


def test_read_today_lines_handles_pre_market_et_boundary(tmp_path):
    """An entry at 23:00 ET on 04-27 is at 03:00 UTC on 04-28.
    Filter for `today=date(2026, 4, 27)` should still include it."""
    p = tmp_path / "log.jsonl"
    p.write_text('{"ts":"2026-04-28T03:00:00+00:00","x":1}\n', encoding="utf-8")
    out = _jsonl_helpers.read_today_lines(p, date(2026, 4, 27))
    assert len(out) == 1
