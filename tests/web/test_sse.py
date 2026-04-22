"""Tests for the SSE broadcaster."""
from __future__ import annotations

import io
import json
import threading
import time

from tradelab.web import sse


class FakeWfile:
    """Minimal wfile substitute that captures writes."""
    def __init__(self, raise_after_n: int | None = None):
        self.buffer = io.BytesIO()
        self.writes = 0
        self.raise_after_n = raise_after_n

    def write(self, data: bytes) -> int:
        self.writes += 1
        if self.raise_after_n is not None and self.writes > self.raise_after_n:
            raise BrokenPipeError("simulated client disconnect")
        return self.buffer.write(data)

    def flush(self) -> None:
        pass


def test_broadcaster_starts_with_no_clients():
    b = sse.Broadcaster()
    assert b.client_count() == 0


def test_subscribe_returns_connection_token_increments_count():
    b = sse.Broadcaster()
    wf = FakeWfile()
    token = b.subscribe(wf)
    assert b.client_count() == 1
    b.unsubscribe(token)
    assert b.client_count() == 0


def test_broadcast_writes_sse_formatted_event_to_all_clients():
    b = sse.Broadcaster()
    wf1 = FakeWfile()
    wf2 = FakeWfile()
    b.subscribe(wf1)
    b.subscribe(wf2)
    b.broadcast({"job_id": "abc", "event": {"type": "start", "stage": "backtest"}})
    out1 = wf1.buffer.getvalue().decode()
    out2 = wf2.buffer.getvalue().decode()
    assert out1.startswith("data: ")
    assert out1.endswith("\n\n")
    assert "abc" in out1 and "backtest" in out1
    assert out1 == out2


def test_broken_pipe_removes_client_from_list():
    b = sse.Broadcaster()
    wf_good = FakeWfile()
    wf_bad = FakeWfile(raise_after_n=0)  # raises on first write
    b.subscribe(wf_good)
    b.subscribe(wf_bad)
    assert b.client_count() == 2
    b.broadcast({"job_id": "abc", "event": {"type": "start"}})
    # Bad client should be pruned; good one remains
    assert b.client_count() == 1


def test_initial_state_replay_sends_one_event_per_active_job():
    b = sse.Broadcaster()
    wf = FakeWfile()
    b.subscribe(wf, initial_state=[
        {"job_id": "a", "event": {"type": "state", "status": "running", "summary": "MC 100/500"}},
        {"job_id": "b", "event": {"type": "state", "status": "queued"}},
    ])
    out = wf.buffer.getvalue().decode()
    # retry hint at top, then 2 data events
    assert out.startswith("retry: 3000\n\n")
    assert out.count("data: ") == 2


def test_is_subscribed_returns_true_for_active_token():
    b = sse.Broadcaster()
    wf = FakeWfile()
    token = b.subscribe(wf)
    assert b.is_subscribed(token) is True
    b.unsubscribe(token)
    assert b.is_subscribed(token) is False


def test_concurrent_broadcast_modification_safe():
    """Subscribing while broadcast iterates must not raise."""
    b = sse.Broadcaster()
    for _ in range(10):
        b.subscribe(FakeWfile())
    errs = []
    def writer():
        try:
            for _ in range(100):
                b.broadcast({"job_id": "a", "event": {"type": "tick"}})
        except Exception as e:
            errs.append(e)
    def subscriber():
        try:
            for _ in range(100):
                b.subscribe(FakeWfile())
                time.sleep(0.001)
        except Exception as e:
            errs.append(e)
    t1 = threading.Thread(target=writer)
    t2 = threading.Thread(target=subscriber)
    t1.start(); t2.start()
    t1.join(); t2.join()
    assert errs == []
