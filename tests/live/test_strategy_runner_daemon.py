"""Tests for the strategy_runner daemon layer (Phase-4 Task 4).

SAFETY INVARIANT: _real_deps() must NEVER be called in any test here.
All tests inject fake deps/registry/run_tick_fn so no real Alpaca account
or network call is ever made.
"""
import time
from datetime import datetime, timezone

from tradelab.live import strategy_runner as sr


# ─────────────────────────────────────────────────────────────────────────────
# _bar_bucket
# ─────────────────────────────────────────────────────────────────────────────

def test_bar_bucket_daily_vs_intraday():
    now = datetime(2026, 5, 31, 14, 30, tzinfo=timezone.utc)
    assert sr._bar_bucket("1D", now) == "2026-05-31"
    assert sr._bar_bucket("1H", now) == "2026-05-31-14"


def test_bar_bucket_various_timeframes():
    now = datetime(2026, 5, 31, 9, 0, tzinfo=timezone.utc)
    # All daily variants → date-only bucket
    assert sr._bar_bucket("1D", now) == "2026-05-31"
    assert sr._bar_bucket("2D", now) == "2026-05-31"
    # Intraday → date + hour bucket
    assert sr._bar_bucket("1H", now) == "2026-05-31-09"
    assert sr._bar_bucket("5m", now) == "2026-05-31-09"
    assert sr._bar_bucket("15min", now) == "2026-05-31-09"


# ─────────────────────────────────────────────────────────────────────────────
# run_tick — grouping and delegation
# ─────────────────────────────────────────────────────────────────────────────

def test_run_tick_groups_by_timeframe_and_calls_run_once(monkeypatch):
    seen = []

    def _fake_run_once(cards, *, deps, bar_date):
        seen.append((sorted(cards), bar_date))
        return {k: {"action": "none"} for k in cards}

    monkeypatch.setattr(sr, "run_once", _fake_run_once)

    class _Reg:
        def all(self):
            return {
                "a": {"card_id": "a", "status": "enabled", "source": "python",
                      "mode": "paper", "timeframe": "1D"},
                "b": {"card_id": "b", "status": "enabled", "source": "python",
                      "mode": "paper", "timeframe": "1H"},
                "c": {"card_id": "c", "status": "disabled", "source": "python",
                      "mode": "paper", "timeframe": "1D"},
            }

    res = sr.run_tick(
        registry=_Reg(),
        deps={"_": None},
        now=datetime(2026, 5, 31, 14, 0, tzinfo=timezone.utc),
    )

    # disabled card 'c' must be excluded from results
    assert "c" not in res

    # Both time-buckets must have been seen
    buckets = {bd for _, bd in seen}
    assert "2026-05-31" in buckets       # 1D bucket
    assert "2026-05-31-14" in buckets    # 1H bucket

    # Enabled cards are present in results
    assert "a" in res
    assert "b" in res


def test_run_tick_excludes_non_python_and_non_paper(monkeypatch):
    """Cards with source!='python' or mode!='paper' must be silently skipped."""
    seen = []

    def _fake_run_once(cards, *, deps, bar_date):
        seen.extend(cards.keys())
        return {k: {"action": "none"} for k in cards}

    monkeypatch.setattr(sr, "run_once", _fake_run_once)

    class _Reg:
        def all(self):
            return {
                "py-paper":    {"card_id": "py-paper",    "status": "enabled",
                                "source": "python", "mode": "paper",  "timeframe": "1D"},
                "pine-paper":  {"card_id": "pine-paper",  "status": "enabled",
                                "source": "pine",   "mode": "paper",  "timeframe": "1D"},
                "py-live":     {"card_id": "py-live",     "status": "enabled",
                                "source": "python", "mode": "live",   "timeframe": "1D"},
            }

    res = sr.run_tick(registry=_Reg(), deps={}, now=datetime(2026, 5, 31, tzinfo=timezone.utc))
    assert "py-paper" in seen
    assert "pine-paper" not in seen
    assert "py-live" not in seen
    assert set(res.keys()) == {"py-paper"}


def test_run_tick_returns_empty_dict_on_registry_error(monkeypatch):
    """run_tick must never raise — a broken registry returns {}."""
    class _BrokenReg:
        def all(self):
            raise RuntimeError("registry exploded")

    res = sr.run_tick(
        registry=_BrokenReg(),
        deps={},
        now=datetime(2026, 5, 31, tzinfo=timezone.utc),
    )
    assert res == {}


# ─────────────────────────────────────────────────────────────────────────────
# start / stop daemon
# ─────────────────────────────────────────────────────────────────────────────

def test_start_stop_calls_tick_without_real_alpaca(monkeypatch):
    """_real_deps must NEVER be called when deps are injected.

    This test proves the safety invariant: if _real_deps were invoked it
    would raise AssertionError, causing the test to fail.
    """
    ticks = []

    # Poison _real_deps so any accidental call is a hard test failure.
    def _poison_real_deps():
        raise AssertionError("_real_deps must not be built in tests — would touch Alpaca")

    monkeypatch.setattr(sr, "_real_deps", _poison_real_deps)

    sr.start(
        deps={"fake": True},
        registry=object(),
        run_tick_fn=lambda *, registry, deps, now: ticks.append(now) or {},
        tick_seconds=0.05,
    )
    time.sleep(0.25)
    sr.stop()

    # Daemon must have fired at least one tick during the 0.25s window
    assert len(ticks) >= 1
    # All tick timestamps must be UTC-aware
    for ts in ticks:
        assert ts.tzinfo is not None


def test_daemon_is_idempotent_double_start(monkeypatch):
    """Calling start() twice must not launch a second thread."""
    monkeypatch.setattr(sr, "_real_deps", lambda: (_ for _ in ()).throw(
        AssertionError("_real_deps called")))

    ticks = []
    sr.start(
        deps={},
        registry=object(),
        run_tick_fn=lambda *, registry, deps, now: ticks.append(1) or {},
        tick_seconds=0.1,
    )
    thread_id_1 = sr._thread.ident if sr._thread else None

    # Second start() should be a no-op
    sr.start(
        deps={},
        registry=object(),
        run_tick_fn=lambda *, registry, deps, now: ticks.append(2) or {},
        tick_seconds=0.1,
    )
    thread_id_2 = sr._thread.ident if sr._thread else None

    sr.stop()

    # Same thread object (idempotent)
    assert thread_id_1 == thread_id_2


def test_stop_is_safe_when_not_running():
    """stop() when daemon is not running must not raise."""
    # Ensure stopped state
    sr.stop()
    # Second stop is also safe
    sr.stop()


def test_daemon_tick_fn_receives_utc_now(monkeypatch):
    """The now= passed to run_tick_fn must be UTC-aware."""
    monkeypatch.setattr(sr, "_real_deps", lambda: (_ for _ in ()).throw(
        AssertionError("_real_deps called")))

    received = []
    sr.start(
        deps={},
        registry=object(),
        run_tick_fn=lambda *, registry, deps, now: received.append(now) or {},
        tick_seconds=0.05,
    )
    time.sleep(0.15)
    sr.stop()

    assert len(received) >= 1
    for ts in received:
        assert ts.tzinfo == timezone.utc
