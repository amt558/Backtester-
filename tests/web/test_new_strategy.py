"""Tests for paste-a-strategy flow."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from tradelab.web import new_strategy


MINIMAL_VALID_CODE = '''
from tradelab.strategies.base import Strategy
import pandas as pd

class MyTest(Strategy):
    default_params = {"lookback": 10}
    def generate_signals(self, data, spy_close=None):
        out = {}
        for sym, df in data.items():
            df = df.copy()
            df["buy_signal"] = False
            out[sym] = df
        return out
'''


def test_validate_rejects_bad_name_format(fake_tradelab_root: Path):
    result = new_strategy.validate_and_stage(
        name="Bad-Name!",
        code=MINIMAL_VALID_CODE,
        staging_root=fake_tradelab_root / ".cache" / "new_strategy_staging",
        src_root=fake_tradelab_root / "src",
    )
    assert result["error"]
    assert result["stage"] == "name"


def test_validate_rejects_name_collision(fake_tradelab_root: Path, monkeypatch):
    # Pretend s4_inside_day_breakout is already registered
    monkeypatch.setattr(
        new_strategy,
        "_is_registered",
        lambda n: n == "taken_name",
    )
    result = new_strategy.validate_and_stage(
        name="taken_name",
        code=MINIMAL_VALID_CODE,
        staging_root=fake_tradelab_root / ".cache" / "new_strategy_staging",
        src_root=fake_tradelab_root / "src",
    )
    assert result["error"]
    assert "already" in result["error"].lower()
    assert result["stage"] == "name"


def test_validate_rejects_syntax_error(fake_tradelab_root: Path, monkeypatch):
    monkeypatch.setattr(new_strategy, "_is_registered", lambda n: False)
    result = new_strategy.validate_and_stage(
        name="my_test",
        code="this is not valid python :::",
        staging_root=fake_tradelab_root / ".cache" / "new_strategy_staging",
        src_root=fake_tradelab_root / "src",
    )
    assert result["error"]
    assert result["stage"] == "import"


def test_validate_rejects_no_strategy_class(fake_tradelab_root: Path, monkeypatch):
    monkeypatch.setattr(new_strategy, "_is_registered", lambda n: False)
    result = new_strategy.validate_and_stage(
        name="my_test",
        code="x = 1\n",
        staging_root=fake_tradelab_root / ".cache" / "new_strategy_staging",
        src_root=fake_tradelab_root / "src",
    )
    assert result["error"]
    assert result["stage"] == "discover"


def test_discard_removes_staging_file(fake_tradelab_root: Path):
    staging = fake_tradelab_root / ".cache" / "new_strategy_staging"
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "my_test.py").write_text("pass")
    new_strategy.discard_staging("my_test", staging_root=staging)
    assert not (staging / "my_test.py").exists()


def test_cleanup_removes_old_files(fake_tradelab_root: Path):
    staging = fake_tradelab_root / ".cache" / "new_strategy_staging"
    staging.mkdir(parents=True, exist_ok=True)
    old = staging / "old.py"
    old.write_text("pass")
    import os, time
    old_ts = time.time() - (48 * 3600)  # 48h old
    os.utime(old, (old_ts, old_ts))
    fresh = staging / "fresh.py"
    fresh.write_text("pass")
    removed = new_strategy.cleanup_old_staging(staging_root=staging, max_age_hours=24)
    assert removed == 1
    assert not old.exists()
    assert fresh.exists()


def test_normalize_name_handles_hyphens_and_case():
    assert new_strategy._normalize_name("TEST-A5") == "test_a5"
    assert new_strategy._normalize_name("My-Strategy_V2") == "my_strategy_v2"
    assert new_strategy._normalize_name("  spaced  ") == "spaced"
    assert new_strategy._normalize_name("already_snake") == "already_snake"


def test_validate_accepts_hyphen_and_uppercase_input(
    fake_tradelab_root: Path, monkeypatch
):
    """TEST-A5 passes name-stage validation and progresses to discover stage."""
    monkeypatch.setattr(new_strategy, "_is_registered", lambda n: False)
    result = new_strategy.validate_and_stage(
        name="TEST-A5",
        code="x = 1\n",  # no Strategy subclass → fails at discover, not name
        staging_root=fake_tradelab_root / ".cache" / "new_strategy_staging",
        src_root=fake_tradelab_root / "src",
    )
    # Past name stage (no name error) — failed at discover stage
    assert result["stage"] == "discover"
