"""Tests for jsonl_rotation utility added in Slice 7a."""
import gzip
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from tradelab.live import jsonl_rotation


_ET = ZoneInfo("America/New_York")


def test_rotate_if_needed_missing_file_returns_none(tmp_path):
    p = tmp_path / "absent.jsonl"
    assert jsonl_rotation.rotate_if_needed(p) is None


def test_rotate_if_needed_under_threshold_returns_none(tmp_path):
    p = tmp_path / "small.jsonl"
    p.write_text('{"x":1}\n', encoding="utf-8")
    assert jsonl_rotation.rotate_if_needed(p, max_size_mb=1) is None
    # Original file untouched
    assert p.read_text(encoding="utf-8") == '{"x":1}\n'


def test_rotate_if_needed_oserror_returns_none_does_not_raise(tmp_path):
    p = tmp_path / "broken.jsonl"
    p.write_bytes(b"x" * (2 * 1024 * 1024))  # 2 MB
    with patch("tradelab.live.jsonl_rotation.os.replace", side_effect=OSError("simulated")):
        # Should not raise; should return None
        result = jsonl_rotation.rotate_if_needed(p, max_size_mb=1)
    assert result is None


def test_rotate_if_needed_over_threshold_creates_gz(tmp_path):
    p = tmp_path / "big.jsonl"
    payload = '{"a":1}\n' * 200_000  # ~1.6 MB
    p.write_text(payload, encoding="utf-8")

    archive = jsonl_rotation.rotate_if_needed(p, max_size_mb=1)

    assert archive is not None
    assert archive.exists()
    assert archive.suffix == ".gz"
    # Original file should now be empty (started fresh)
    assert p.read_text(encoding="utf-8") == ""
    # Archive should round-trip via gzip
    with gzip.open(archive, "rt", encoding="utf-8") as f:
        assert f.read() == payload


def test_rotate_if_needed_naming_collision_increments_n(tmp_path):
    p = tmp_path / "log.jsonl"
    p.write_text("a" * (2 * 1024 * 1024), encoding="utf-8")  # >1 MB

    # Pre-create today's N=0 archive so the rotator must pick N=1
    today = datetime.now(_ET).strftime("%Y-%m-%d")
    pre_existing = tmp_path / f"log.{today}.0.jsonl.gz"
    pre_existing.write_bytes(b"prior")

    archive = jsonl_rotation.rotate_if_needed(p, max_size_mb=1)
    assert archive is not None
    assert archive.name == f"log.{today}.1.jsonl.gz"
    # Pre-existing archive untouched
    assert pre_existing.read_bytes() == b"prior"


def test_rotate_if_needed_archive_cap_drops_oldest(tmp_path):
    p = tmp_path / "log.jsonl"

    # Create 4 fake old archives (pretend they exist from prior days)
    for i, day in enumerate(["2026-04-20", "2026-04-21", "2026-04-22", "2026-04-23"]):
        (tmp_path / f"log.{day}.0.jsonl.gz").write_bytes(b"old" + str(i).encode())

    # Now trigger a rotation that would create a 5th archive — keep_archives=3
    p.write_text("x" * (2 * 1024 * 1024), encoding="utf-8")
    archive = jsonl_rotation.rotate_if_needed(p, max_size_mb=1, keep_archives=3)

    assert archive is not None
    archives = sorted(tmp_path.glob("log.*.jsonl.gz"))
    # Should now have exactly 3 archives total (the cap)
    assert len(archives) == 3
    # The oldest two (2026-04-20, 2026-04-21) should be gone
    surviving_names = {a.name for a in archives}
    assert not any("2026-04-20" in n or "2026-04-21" in n for n in surviving_names)


def test_rotate_all_handles_three_files(tmp_path, monkeypatch):
    """rotate_all should call rotate_if_needed on alerts, notify_events, panic_events."""
    alerts = tmp_path / "alerts.jsonl"
    notify = tmp_path / "notify_events.jsonl"
    panic = tmp_path / "panic_events.jsonl"
    alerts.write_text("a\n", encoding="utf-8")
    notify.write_text("b\n", encoding="utf-8")
    # panic deliberately missing (no rotation needed)

    monkeypatch.setattr(jsonl_rotation, "ALERTS_PATH", alerts)
    monkeypatch.setattr(jsonl_rotation, "NOTIFY_PATH", notify)
    monkeypatch.setattr(jsonl_rotation, "PANIC_PATH", panic)

    result = jsonl_rotation.rotate_all()

    # All three keys present; values are None (under threshold or missing)
    assert set(result.keys()) == {"alerts", "notify_events", "panic_events"}
    assert all(v is None for v in result.values())


# ─── B3: _today_et_str must use America/New_York, not server-local TZ ────

def test_today_et_str_uses_et_not_local_tz(monkeypatch):
    """At 03:30 UTC on 2026-04-28 it is 23:30 ET on 2026-04-27.

    This test pins `_today_et_str` to ET regardless of where the server
    runs. Even if the local timezone happened to give the same answer
    (e.g. the box is in ET), this test still exercises the ET branch by
    forcing the wall-clock instant to a moment where UTC and ET disagree.
    """
    from datetime import datetime as _real_dt, timezone

    fixed_utc = _real_dt(2026, 4, 28, 3, 30, 0, tzinfo=timezone.utc)

    class _FrozenDatetime(_real_dt):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                # Mirror real datetime.now() returning naive local time.
                return fixed_utc.astimezone().replace(tzinfo=None)
            return fixed_utc.astimezone(tz)

    monkeypatch.setattr(jsonl_rotation, "datetime", _FrozenDatetime)

    # ET wall-clock for 03:30 UTC on 2026-04-28 is 23:30 on 2026-04-27 (EDT, UTC-4)
    assert jsonl_rotation._today_et_str() == "2026-04-27"


def test_today_et_str_returns_iso_date_format():
    """Sanity: the function returns YYYY-MM-DD shape so archive paths parse."""
    today = jsonl_rotation._today_et_str()
    # YYYY-MM-DD = 10 chars, two dashes
    assert len(today) == 10
    assert today[4] == "-" and today[7] == "-"
    # Must round-trip through fromisoformat
    datetime.fromisoformat(today)


# ─── B2: crash-recovery and orphan cleanup ──────────────────────────────

def test_rotate_cleans_up_orphan_truncate_tmp(tmp_path):
    """Pre-fix legacy: an `.jsonl.tmp` file from a prior crashed rotation
    must be removed on the next rotate_if_needed call, even if no
    rotation actually triggers."""
    p = tmp_path / "log.jsonl"
    p.write_text("{}\n", encoding="utf-8")  # under threshold
    orphan = tmp_path / "log.jsonl.tmp"
    orphan.write_bytes(b"")

    # Below threshold → no rotation, but cleanup should still run.
    result = jsonl_rotation.rotate_if_needed(p, max_size_mb=1)

    assert result is None
    assert not orphan.exists(), "orphan .tmp must be cleaned even when no rotation occurs"
    # Source untouched
    assert p.read_text(encoding="utf-8") == "{}\n"


def test_rotate_cleans_up_orphan_gz_tmp_from_prior_crash(tmp_path):
    """If a previous rotation crashed mid-flight, a `.jsonl.gz.tmp` orphan
    is left behind. The next rotate_if_needed call must remove it before
    proceeding so it does not collide with the next archive's tmp slot."""
    p = tmp_path / "log.jsonl"
    p.write_text("{}\n", encoding="utf-8")  # under threshold

    today = datetime.now(_ET).strftime("%Y-%m-%d")
    orphan = tmp_path / f"log.{today}.0.jsonl.gz.tmp"
    orphan.write_bytes(b"\x1f\x8bpartial")  # arbitrary bytes; not valid gzip

    result = jsonl_rotation.rotate_if_needed(p, max_size_mb=1)

    assert result is None
    assert not orphan.exists(), "orphan .gz.tmp must be cleaned up"


def test_rotate_mid_crash_leaves_no_gz_tmp_orphan(tmp_path):
    """If the truncate step raises mid-rotation, the in-flight `.gz.tmp`
    must be cleaned up so it does not become an orphan. This simulates the
    process being killed AFTER the gz.tmp write but BEFORE the source is
    truncated — the worst pre-fix scenario, which previously left the
    archive at its FINAL `.gz` path and produced duplicate archives on
    the next rotation."""
    p = tmp_path / "log.jsonl"
    payload = "x" * (2 * 1024 * 1024)
    p.write_text(payload, encoding="utf-8")

    # Make `os.replace` raise the FIRST time it is called (the truncate
    # step). This is exactly the crash window described in B2.
    with patch(
        "tradelab.live.jsonl_rotation.os.replace",
        side_effect=OSError("simulated mid-rotation crash"),
    ):
        result = jsonl_rotation.rotate_if_needed(p, max_size_mb=1)

    # Must return None (best-effort, never raise OSError).
    assert result is None

    # Source must still exist (could be truncated or original — both are
    # acceptable; the invariant is that no archive was published and no
    # orphan tmp remains).
    assert p.exists()

    # No `.gz.tmp` orphan
    gz_tmp_orphans = list(tmp_path.glob("*.jsonl.gz.tmp"))
    assert gz_tmp_orphans == [], f"expected no .gz.tmp orphans, found: {gz_tmp_orphans}"

    # Crucially: NO final `.gz` archive should be visible to ops, because
    # the rename to `.gz` happens AFTER truncate succeeds.
    final_archives = list(tmp_path.glob("*.jsonl.gz"))
    assert final_archives == [], (
        "no archive should be visible to ops when rotation crashed mid-flight; "
        f"found: {final_archives}"
    )


def test_rotate_recovers_without_duplicate_archive_after_prior_crash(tmp_path):
    """Simulate a prior-rotation crash: a `.gz.tmp` orphan exists in the
    dir AND the source was never truncated. The next rotate_if_needed
    must clean the orphan and produce ONE archive — not two with N=0 and
    N=1, which was the visible-to-ops duplication described in B2."""
    p = tmp_path / "log.jsonl"
    payload = "y" * (2 * 1024 * 1024)
    p.write_text(payload, encoding="utf-8")

    today = datetime.now(_ET).strftime("%Y-%m-%d")
    # Stale orphan from a prior crash at the next-archive slot.
    stale = tmp_path / f"log.{today}.0.jsonl.gz.tmp"
    stale.write_bytes(b"\x1f\x8bgarbage")

    archive = jsonl_rotation.rotate_if_needed(p, max_size_mb=1)

    assert archive is not None
    assert archive.exists()
    # The orphan cleanup runs first, so `_next_archive_path` correctly
    # picks N=0, NOT N=1.
    assert archive.name == f"log.{today}.0.jsonl.gz"

    # No leftover tmps of any kind.
    assert list(tmp_path.glob("*.tmp")) == []

    # Exactly one final archive.
    final_archives = list(tmp_path.glob("*.jsonl.gz"))
    assert len(final_archives) == 1

    # Archive content matches the source (proves no double-archive issue).
    with gzip.open(archive, "rt", encoding="utf-8") as f:
        assert f.read() == payload


# ─── B4: broader best-effort exception coverage ─────────────────────────


def test_rotate_returns_none_when_gzip_open_raises_oserror(tmp_path, monkeypatch):
    """gzip.open() failure (e.g. disk full, permissions) must be caught by
    the outer best-effort handler — return None, never propagate."""
    p = tmp_path / "log.jsonl"
    payload = "z" * (2 * 1024 * 1024)
    p.write_text(payload, encoding="utf-8")

    def _boom(*args, **kwargs):
        raise OSError("simulated gzip.open failure")

    monkeypatch.setattr(jsonl_rotation.gzip, "open", _boom)
    result = jsonl_rotation.rotate_if_needed(p, max_size_mb=1)

    assert result is None
    # Source intact (no truncate happened) and no .gz published.
    assert p.read_text(encoding="utf-8") == payload
    assert list(tmp_path.glob("*.jsonl.gz")) == []


def test_rotate_recovers_after_gzip_open_failure(tmp_path, monkeypatch):
    """After a gzip.open OSError, the next rotate_if_needed call (without
    the patch) must succeed, proving _cleanup_orphans gives us recovery."""
    p = tmp_path / "log.jsonl"
    payload = "q" * (2 * 1024 * 1024)
    p.write_text(payload, encoding="utf-8")

    monkeypatch.setattr(
        jsonl_rotation.gzip, "open", lambda *a, **kw: (_ for _ in ()).throw(OSError("boom"))
    )
    assert jsonl_rotation.rotate_if_needed(p, max_size_mb=1) is None

    # Drop the patch and retry — recovery must yield a real archive.
    monkeypatch.undo()
    archive = jsonl_rotation.rotate_if_needed(p, max_size_mb=1)
    assert archive is not None and archive.exists()
    # No leftover tmps either.
    assert list(tmp_path.glob("*.tmp")) == []


def test_rotate_cleans_gz_tmp_when_copyfileobj_fails_midstream(tmp_path, monkeypatch):
    """shutil.copyfileobj failure mid-stream must leave no published .gz,
    no truncated source, and the orphan .gz.tmp must be cleaned by the
    next rotate_if_needed invocation."""
    p = tmp_path / "log.jsonl"
    payload = "m" * (2 * 1024 * 1024)
    p.write_text(payload, encoding="utf-8")

    def _half_then_die(src, dst, *a, **kw):
        dst.write(b"partial-bytes")
        raise OSError("simulated source-vanished mid-stream")

    monkeypatch.setattr(jsonl_rotation.shutil, "copyfileobj", _half_then_die)
    assert jsonl_rotation.rotate_if_needed(p, max_size_mb=1) is None

    # Source intact; no .gz published. The inner BaseException handler
    # already removes the in-flight .gz.tmp before re-raise, so no orphan
    # exists for the next call to clean — but cleanup running again is a no-op.
    assert p.read_text(encoding="utf-8") == payload
    assert list(tmp_path.glob("*.jsonl.gz")) == []
    assert list(tmp_path.glob("*.jsonl.gz.tmp")) == []

    # Next call (without patch) succeeds — no stale state interferes.
    monkeypatch.undo()
    archive = jsonl_rotation.rotate_if_needed(p, max_size_mb=1)
    assert archive is not None and archive.exists()


def test_rotate_survives_archive_cap_stat_filenotfound(tmp_path, monkeypatch):
    """_enforce_archive_cap glob/stat race: on Windows, an archive can be
    deleted between the glob and the per-file stat. FileNotFoundError on
    stat must NOT crash rotation — the outer OSError handler catches it."""
    p = tmp_path / "log.jsonl"
    p.write_text("g" * (2 * 1024 * 1024), encoding="utf-8")

    # Pre-create archives so the cap helper has work to do.
    for day in ["2026-04-20", "2026-04-21", "2026-04-22"]:
        (tmp_path / f"log.{day}.0.jsonl.gz").write_bytes(b"x")

    real_stat = Path.stat
    victim_name = f"log.2026-04-20.0.jsonl.gz"

    def _racy_stat(self, *a, **kw):
        if self.name == victim_name:
            raise FileNotFoundError(f"simulated race: {self.name}")
        return real_stat(self, *a, **kw)

    monkeypatch.setattr(Path, "stat", _racy_stat)

    # Rotation itself should not crash. FileNotFoundError ∈ OSError, so the
    # outer handler swallows it and returns None.
    result = jsonl_rotation.rotate_if_needed(p, max_size_mb=1, keep_archives=2)

    # Either result is None (cap-stat raised before publish) or an archive
    # was published before cap ran. Both are acceptable; the invariant is
    # NO unhandled exception escapes.
    assert result is None or result.exists()
