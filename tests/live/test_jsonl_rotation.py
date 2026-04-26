"""Tests for jsonl_rotation utility added in Slice 7a."""
import gzip
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tradelab.live import jsonl_rotation


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
    from datetime import datetime
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
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
