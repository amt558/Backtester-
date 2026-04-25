"""Tests for tradelab.web.preflight.

Each check is exercised in isolation with monkeypatched state. Aggregator is
tested via a single happy-path roundup.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from tradelab.web import preflight


def _seed_launcher_state(tmp_path: Path, universe: str) -> None:
    """Create .cache/launcher-state.json with a given activeUniverse."""
    cache = tmp_path / ".cache"
    cache.mkdir(exist_ok=True)
    (cache / "launcher-state.json").write_text(
        json.dumps({"activeUniverse": universe}), encoding="utf-8"
    )


def test_check_universe_red_when_no_launcher_state_and_no_yaml_universes(tmp_path, monkeypatch):
    # NB: preflight does `from tradelab.web.handlers import _resolve_active_universe`
    # at import time, which binds the symbol locally. Patching the original
    # location (tradelab.web.handlers._resolve_active_universe) leaves
    # preflight's binding pointing at the real function, which then leaks
    # config-cache state from prior tests. Patch the local binding instead.
    monkeypatch.chdir(tmp_path)
    with patch("tradelab.web.preflight._resolve_active_universe", return_value=""):
        result = preflight.check_universe()
    assert result["status"] == "red"
    assert "no universe" in result["label"].lower()


def test_check_universe_ok_when_symbols_present(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fake_cfg = type("Cfg", (), {"universes": {"nasdaq_100": ["AAPL", "MSFT"]}})()
    with patch("tradelab.web.preflight._resolve_active_universe", return_value="nasdaq_100"), \
         patch("tradelab.config.get_config", return_value=fake_cfg):
        result = preflight.check_universe()
    assert result["status"] == "ok"
    assert "nasdaq_100" in result["label"]


def test_check_cache_warn_when_parquet_is_old(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cache_dir = tmp_path / ".cache" / "ohlcv" / "1D"
    cache_dir.mkdir(parents=True)
    p = cache_dir / "AAPL.parquet"
    p.write_bytes(b"fake")
    old_ts = time.time() - (preflight.CACHE_WARN_HOURS + 1) * 3600
    os.utime(p, (old_ts, old_ts))
    fake_cfg = type("Cfg", (), {"universes": {"u": ["AAPL"]}})()
    with patch("tradelab.web.preflight._resolve_active_universe", return_value="u"), \
         patch("tradelab.config.get_config", return_value=fake_cfg):
        result = preflight.check_cache()
    assert result["status"] == "warn"


def test_check_cache_red_when_many_symbols_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".cache" / "ohlcv" / "1D").mkdir(parents=True)
    syms = [f"SYM{i}" for i in range(10)]
    fake_cfg = type("Cfg", (), {"universes": {"u": syms}})()
    with patch("tradelab.web.preflight._resolve_active_universe", return_value="u"), \
         patch("tradelab.config.get_config", return_value=fake_cfg):
        result = preflight.check_cache()
    assert result["status"] == "red"


def test_check_tdapi_red_when_env_missing(monkeypatch):
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    assert preflight.check_tdapi()["status"] == "red"


def test_compute_preflight_returns_all_four_keys(monkeypatch):
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    result = preflight.compute_preflight()
    assert set(result.keys()) == {"universe", "cache", "strategy", "tdapi"}
    for v in result.values():
        assert "status" in v and "label" in v and "detail" in v
