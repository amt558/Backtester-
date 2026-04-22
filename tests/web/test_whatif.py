"""Tests for What-If single-symbol backtest runner."""
from __future__ import annotations

import pytest

from tradelab.web import whatif


def test_whatif_rejects_unknown_strategy():
    with pytest.raises(whatif.WhatIfError) as exc:
        whatif.run_whatif(strategy_name="does_not_exist", symbol="AAPL", params={})
    assert "not registered" in str(exc.value).lower()


def test_whatif_returns_metrics_and_equity_curve(monkeypatch):
    """Integration test — uses a registered strategy against real Twelve Data cache.

    Skipped if the cache doesn't have AAPL (e.g. fresh dev checkout).
    """
    from pathlib import Path
    cache = Path(".cache") / "ohlcv" / "1D" / "AAPL.parquet"
    if not cache.exists():
        pytest.skip("AAPL parquet missing — run tradelab refresh first")
    result = whatif.run_whatif(
        strategy_name="s4_inside_day_breakout",
        symbol="AAPL",
        params={},
    )
    assert "metrics" in result
    assert "equity_curve" in result
    assert "profit_factor" in result["metrics"]
