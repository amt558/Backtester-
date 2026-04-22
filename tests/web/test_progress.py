"""Tests for the progress.jsonl tail loop."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from tradelab.web import progress


def test_tail_reads_existing_lines_and_calls_callback(tmp_path):
    log = tmp_path / "progress.jsonl"
    log.write_text(
        json.dumps({"type": "start", "stage": "backtest"}) + "\n"
        + json.dumps({"type": "done", "exit": 0}) + "\n"
    )
    received = []
    tailer = progress.ProgressTailer(log, on_event=received.append, poll_interval_s=0.05)
    tailer.start()
    # Allow a couple of poll cycles
    time.sleep(0.3)
    tailer.stop()
    assert len(received) == 2
    assert received[0]["type"] == "start"
    assert received[1]["type"] == "done"


def test_tail_picks_up_appended_lines_within_500ms(tmp_path):
    log = tmp_path / "progress.jsonl"
    log.touch()
    received = []
    tailer = progress.ProgressTailer(log, on_event=received.append, poll_interval_s=0.05)
    tailer.start()
    time.sleep(0.1)
    with log.open("a") as f:
        f.write(json.dumps({"type": "start", "stage": "backtest"}) + "\n")
    # Wait up to 600ms for the event
    deadline = time.time() + 0.6
    while time.time() < deadline and not received:
        time.sleep(0.02)
    tailer.stop()
    assert len(received) == 1


def test_tail_skips_corrupted_lines_does_not_crash(tmp_path):
    log = tmp_path / "progress.jsonl"
    log.write_text(
        '{"type":"start","stage":"backtest"}\n'
        'this is not json\n'
        '{"type":"done","exit":0}\n'
    )
    received = []
    tailer = progress.ProgressTailer(log, on_event=received.append, poll_interval_s=0.05)
    tailer.start()
    time.sleep(0.3)
    tailer.stop()
    # Bad line skipped, two valid events received
    assert len(received) == 2


def test_tail_silent_until_file_appears(tmp_path):
    log = tmp_path / "progress.jsonl"  # does not exist yet
    received = []
    tailer = progress.ProgressTailer(log, on_event=received.append, poll_interval_s=0.05)
    tailer.start()
    time.sleep(0.2)
    assert received == []
    log.write_text('{"type":"start","stage":"backtest"}\n')
    deadline = time.time() + 0.4
    while time.time() < deadline and not received:
        time.sleep(0.02)
    tailer.stop()
    assert len(received) == 1


def test_tail_partial_line_safe(tmp_path):
    """A line written without trailing newline should not be parsed until newline arrives."""
    log = tmp_path / "progress.jsonl"
    log.write_text('{"type":"start","stage":"backtest"')  # no newline yet, no closing }
    received = []
    tailer = progress.ProgressTailer(log, on_event=received.append, poll_interval_s=0.05)
    tailer.start()
    time.sleep(0.2)
    assert received == []  # partial line not parsed
    with log.open("a") as f:
        f.write('}\n')
    deadline = time.time() + 0.4
    while time.time() < deadline and not received:
        time.sleep(0.02)
    tailer.stop()
    assert len(received) == 1


def test_tail_stops_cleanly(tmp_path):
    log = tmp_path / "progress.jsonl"
    log.touch()
    received = []
    tailer = progress.ProgressTailer(log, on_event=received.append, poll_interval_s=0.05)
    tailer.start()
    # Capture the thread reference BEFORE stop() — stop() sets _thread = None
    # on success, so checking tailer._thread after the call would be vacuous.
    t = tailer._thread
    assert t is not None and t.is_alive()
    tailer.stop()
    assert not t.is_alive()
    assert tailer._thread is None
