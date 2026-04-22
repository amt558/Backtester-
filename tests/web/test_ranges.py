"""Tests for claude_ranges.json sidecar reader."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tradelab.web import ranges


def test_ranges_returns_none_when_missing(fake_strategies_dir: Path) -> None:
    """When strategy has no claude_ranges.json, return None."""
    src_root = fake_strategies_dir.parent.parent
    result = ranges.get_ranges("does_not_exist", src_root=src_root)
    assert result is None


def test_ranges_reads_sidecar_json(fake_strategies_dir: Path) -> None:
    """Read valid sidecar JSON with param definitions."""
    # Create strategy directory
    strategy_dir = fake_strategies_dir / "my_strategy"
    strategy_dir.mkdir()

    # Write valid JSON with expected schema
    ranges_data = {
        "atr_period": {
            "min": 5,
            "max": 50,
            "default": 14,
            "step": 1,
            "claude_note": "ATR lookback period"
        },
        "rsi_threshold": {
            "min": 20,
            "max": 80,
            "default": 50,
            "step": 5,
            "claude_note": "RSI overbought/oversold level"
        }
    }
    ranges_file = strategy_dir / "claude_ranges.json"
    ranges_file.write_text(json.dumps(ranges_data))

    # Call get_ranges with src_root pointing to the src directory
    src_root = fake_strategies_dir.parent.parent
    result = ranges.get_ranges("my_strategy", src_root=src_root)

    # Assert dict returned with expected fields
    assert result is not None
    assert isinstance(result, dict)
    assert "atr_period" in result
    assert "rsi_threshold" in result
    assert result["atr_period"]["min"] == 5
    assert result["atr_period"]["max"] == 50
    assert result["atr_period"]["default"] == 14
    assert result["atr_period"]["step"] == 1
    assert result["atr_period"]["claude_note"] == "ATR lookback period"


def test_ranges_returns_none_on_invalid_json(fake_strategies_dir: Path) -> None:
    """When claude_ranges.json is malformed, return None."""
    # Create strategy directory
    strategy_dir = fake_strategies_dir / "broken"
    strategy_dir.mkdir()

    # Write invalid JSON
    ranges_file = strategy_dir / "claude_ranges.json"
    ranges_file.write_text("{ not valid json")

    # Should return None, not raise
    src_root = fake_strategies_dir.parent.parent
    result = ranges.get_ranges("broken", src_root=src_root)
    assert result is None
