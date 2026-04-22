"""Tests for parquet cache freshness reader."""
from __future__ import annotations

import os
import time
from pathlib import Path

from tradelab.web import freshness


def test_freshness_reports_oldest_and_newest(fake_parquet_cache: Path):
    f = freshness.get_freshness(cache_root=fake_parquet_cache)
    assert f["symbol_count"] == 3
    # AAPL was set to 7200s old, NVDA 3600s, SPY ~now
    assert f["oldest_age_hours"] >= 1.9  # AAPL ~2h
    assert f["newest_age_hours"] < 0.1   # SPY < 6 min
    assert f["status"] == "fresh"  # <24h


def test_freshness_missing_cache_returns_unknown(tmp_path: Path):
    missing = tmp_path / "no-such-cache"
    f = freshness.get_freshness(cache_root=missing)
    assert f["status"] == "unknown"
    assert f["symbol_count"] == 0


def test_freshness_status_buckets(fake_parquet_cache: Path):
    # Backdate AAPL by 100 hours -> status should flip to "stale"
    old_ts = time.time() - (100 * 3600)
    os.utime(fake_parquet_cache / "AAPL.parquet", (old_ts, old_ts))
    f = freshness.get_freshness(cache_root=fake_parquet_cache)
    assert f["status"] == "stale"  # >72h
