"""Fuzzy strategy-name suggestion tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from tradelab.registry import StrategyNotRegistered, get_strategy_entry


def _make_yaml(tmp_path: Path, strategies_block: str = "") -> Path:
    yaml_content = f"""
paths:
  data_dir: "./_d"
  reports_dir: "./_r"
  cache_dir: "./_c"
strategies:
{strategies_block}
"""
    p = tmp_path / "tradelab.yaml"
    p.write_text(yaml_content)
    return p


@pytest.fixture
def clean_config(tmp_path, monkeypatch):
    _make_yaml(tmp_path, """
  s2_pocket_pivot:
    module: "x"
    class_name: "X"
    status: "ported"
  rand_canary:
    module: "y"
    class_name: "Y"
    status: "canary"
""")
    monkeypatch.chdir(tmp_path)
    from tradelab import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "_config", None)
    yield


def test_fuzzy_suggestion_for_typo(clean_config):
    with pytest.raises(StrategyNotRegistered) as exc_info:
        get_strategy_entry("s2_pocket_pivit")   # typo
    msg = str(exc_info.value)
    assert "Did you mean" in msg
    assert "s2_pocket_pivot" in msg


def test_fuzzy_suggestion_for_short_prefix(clean_config):
    with pytest.raises(StrategyNotRegistered) as exc_info:
        get_strategy_entry("rand")   # short
    msg = str(exc_info.value)
    assert "Did you mean" in msg
    assert "rand_canary" in msg


def test_no_suggestion_for_unrelated_name(clean_config):
    with pytest.raises(StrategyNotRegistered) as exc_info:
        get_strategy_entry("completely_unrelated_gibberish_xyz")
    msg = str(exc_info.value)
    # No close match → no "Did you mean" snippet, but still helpful available list
    assert "Available" in msg
