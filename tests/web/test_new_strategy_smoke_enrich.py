"""Task A: _run_smoke_backtest must enrich raw OHLCV before backtesting.

Without enrichment the engine sees no ATR column, ATR is NaN on every bar,
every entry is skipped, and ANY strategy reports zero trades. This pins the
fix: the frames reaching run_backtest carry ATR/RSI/SMA50, and a permissive
strategy actually trades.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from tradelab.strategies.simple import SimpleStrategy
from tradelab.web import new_strategy


class _PermissiveRSI(SimpleStrategy):
    """Trivial strategy: enter on any sub-50 RSI bar. Needs enriched RSI/ATR."""

    name = "permissive_rsi_smoke"
    timeframe = "1D"
    requires_benchmark = False
    default_params = {
        "rsi_threshold": 50.0,
        "stop_atr_mult": 1.5,
        "trail_tight_mult": 1.0,
        "trail_wide_mult": 2.0,
        "trail_tighten_atr": 1.5,
    }

    def entry_signal(self, row, prev, params, prev2=None):
        return prev is not None and row["RSI"] < params["rsi_threshold"]


def _synthetic_ohlcv(n: int = 220) -> pd.DataFrame:
    """Oscillating price inside the config date window (2024-04-08..2026-04-14)
    so RSI crosses 50 and positions both open and close. Deterministic."""
    dates = pd.bdate_range("2024-05-01", periods=n)
    i = np.arange(n)
    close = 100.0 + 8.0 * np.sin(i / 6.0) + 5.0 * np.sin(i / 31.0)
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": close,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": np.full(n, 1_000_000.0),
        }
    )


def test_smoke_backtest_enriches_and_produces_trades(monkeypatch):
    # Every smoke_5 symbol returns the same deterministic oscillating frame.
    monkeypatch.setattr(
        "tradelab.marketdata.cache.read",
        lambda sym, tf: _synthetic_ohlcv(),
    )

    # Spy on run_backtest to capture the columns of the frames it receives.
    import tradelab.engines.backtest as bt

    real_run = bt.run_backtest
    seen: dict[str, set] = {}

    def _spy(strategy, ticker_data, **kw):
        first = next(iter(ticker_data.values()))
        seen["cols"] = set(first.columns)
        return real_run(strategy, ticker_data, **kw)

    monkeypatch.setattr(bt, "run_backtest", _spy)

    metrics, _equity_by_sym = new_strategy._run_smoke_backtest(
        _PermissiveRSI(name="permissive_rsi_smoke")
    )

    # The frames reaching run_backtest must be enriched.
    assert {"ATR", "RSI", "SMA50"} <= seen["cols"], (
        f"frames reaching run_backtest were not enriched; saw {sorted(seen.get('cols', []))}"
    )
    # A permissive strategy must actually trade on enriched data.
    assert metrics.get("total_trades", 0) > 0, "enriched smoke backtest produced zero trades"
