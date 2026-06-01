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


# Code carrying an em-dash + curly quotes in a comment. On Windows, write_text()
# without encoding= writes cp1252 (em-dash → byte 0x97), which the UTF-8 source
# importer then rejects with "invalid start byte". The staged write must be UTF-8.
UNICODE_COMMENT_CODE = (
    '# strategy notes — entry on a pullback to the “demand” zone\n'
    'from tradelab.strategies.base import Strategy\n'
    'import pandas as pd\n'
    '\n'
    'class MyUnicode(Strategy):\n'
    '    default_params = {}\n'
    '    def generate_signals(self, data, spy_close=None):\n'
    '        return {}\n'
)


def test_staged_write_uses_utf8_encoding(
    fake_tradelab_root: Path, monkeypatch
):
    """Task B: the staged write must pass encoding='utf-8' explicitly.

    Asserted at the write contract (not via a decode symptom) so it fails on
    any platform: on a cp1252-default box the missing encoding corrupts the
    em-dash; this test catches the omission even where the default is UTF-8.
    """
    monkeypatch.setattr(new_strategy, "_is_registered", lambda n: False)

    import pathlib

    orig_write_text = pathlib.Path.write_text
    encodings: list = []

    def _record(self, data, *args, **kwargs):
        encodings.append(kwargs.get("encoding"))
        return orig_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "write_text", _record)

    new_strategy.validate_and_stage(
        name="my_unicode",
        code=UNICODE_COMMENT_CODE,
        staging_root=fake_tradelab_root / ".cache" / "new_strategy_staging",
        src_root=fake_tradelab_root / "src",
    )

    assert encodings, "validate_and_stage never wrote the staged file"
    assert encodings[0] == "utf-8", (
        f"staged write used encoding={encodings[0]!r}; must be 'utf-8' so non-ASCII "
        f"source survives a cp1252-default Windows host"
    )


# A pasted strategy that imports its base class by its real name. Stage 3 must
# count only the subclass DEFINED in the staged module, not the imported base.
IMPORTED_BASE_CODE = (
    'from tradelab.strategies.simple import SimpleStrategy\n'
    'import pandas as pd\n'
    '\n'
    'class MyDip(SimpleStrategy):\n'
    '    default_params = {\n'
    '        "stop_atr_mult": 1.5, "trail_tight_mult": 1.0,\n'
    '        "trail_wide_mult": 2.0, "trail_tighten_atr": 1.5,\n'
    '    }\n'
    '    def entry_signal(self, row, prev, params, prev2=None):\n'
    '        return False\n'
)


def test_stage3_excludes_imported_base_class(
    fake_tradelab_root: Path, monkeypatch
):
    """Task C: `from ...simple import SimpleStrategy` must not make discovery
    report two Strategy subclasses — only the module-defined one counts."""
    monkeypatch.setattr(new_strategy, "_is_registered", lambda n: False)
    result = new_strategy.validate_and_stage(
        name="my_dip",
        code=IMPORTED_BASE_CODE,
        staging_root=fake_tradelab_root / ".cache" / "new_strategy_staging",
        src_root=fake_tradelab_root / "src",
    )
    # Must get PAST discover with exactly one subclass — not the "found 2" error.
    assert result["stage"] != "discover", result
    assert "expected exactly one" not in (result.get("error") or ""), result
