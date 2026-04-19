"""SimpleStrategy base class tests."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradelab.engines.backtest import run_backtest
from tradelab.marketdata import enrich_universe
from tradelab.strategies.simple import SimpleStrategy


class _RSIStrategy(SimpleStrategy):
    """Trivial worked example: enter when RSI < threshold."""
    name = "rsi_test"
    timeframe = "1D"
    requires_benchmark = False

    default_params = {
        "rsi_threshold": 35.0,
        "stop_atr_mult": 1.5,
        "trail_tight_mult": 1.0,
        "trail_wide_mult": 2.0,
        "trail_tighten_atr": 1.5,
    }
    tunable_params = {"rsi_threshold": (20.0, 50.0)}

    def entry_signal(self, row, prev, params):
        return prev is not None and row["RSI"] < params["rsi_threshold"]

    def entry_score(self, row, prev, params):
        return 100.0 - float(row["RSI"])   # lower RSI = higher score


def _raw_ohlcv(n=300, seed=0, drift=0.001, vol=0.012):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2023-01-02", periods=n, freq="B")
    returns = rng.normal(drift, vol, size=n)
    close = 100.0 * np.exp(np.cumsum(returns))
    high = close * (1.0 + np.abs(rng.normal(0.0, 0.004, n)))
    low = close * (1.0 - np.abs(rng.normal(0.0, 0.004, n)))
    openp = np.concatenate([[close[0]], close[:-1]])
    volume = rng.integers(800_000, 5_000_000, n)
    return pd.DataFrame({
        "Date": dates, "Open": openp,
        "High": np.maximum.reduce([openp, close, high]),
        "Low":  np.minimum.reduce([openp, close, low]),
        "Close": close, "Volume": volume,
    })


@pytest.fixture
def enriched():
    raw = {
        "SPY":  _raw_ohlcv(seed=1, drift=0.0005),
        "AAPL": _raw_ohlcv(seed=2, drift=0.0008),
        "MSFT": _raw_ohlcv(seed=3, drift=0.0006),
    }
    return enrich_universe(raw, benchmark="SPY")


def test_simple_strategy_produces_required_columns(enriched):
    out = _RSIStrategy().generate_signals(enriched)
    df = out["AAPL"]
    for col in ("buy_signal", "entry_stop", "entry_score"):
        assert col in df.columns, f"missing {col}"
    assert df["buy_signal"].dtype == bool


def test_simple_strategy_no_signal_during_atr_warmup(enriched):
    """ATR isn't valid until ~14 bars in; SimpleStrategy must respect that."""
    out = _RSIStrategy().generate_signals(enriched)
    df = out["AAPL"]
    assert not df.loc[df["ATR"].isna(), "buy_signal"].any()


def test_simple_strategy_runs_through_backtest(enriched):
    """End-to-end: a SimpleStrategy works with run_backtest unchanged."""
    strat = _RSIStrategy()
    bt = run_backtest(strat, enriched, start="2023-01-02", end="2024-12-31")
    # Should produce valid metrics (may be 0 trades on flat synthetic data, that's ok)
    assert bt.metrics.total_trades >= 0
    assert bt.strategy == "rsi_test"


def test_simple_strategy_subclass_bug_does_not_crash():
    """If entry_signal raises, the backtest must still complete (no signal that bar)."""
    class _BadStrategy(SimpleStrategy):
        name = "bad"
        default_params = {
            "stop_atr_mult": 1.5, "trail_tight_mult": 1.0,
            "trail_wide_mult": 2.0, "trail_tighten_atr": 1.5,
        }
        def entry_signal(self, row, prev, params):
            raise ValueError("oops")

    raw = {"SPY": _raw_ohlcv(seed=10), "AAPL": _raw_ohlcv(seed=11)}
    enriched = enrich_universe(raw, benchmark="SPY")
    out = _BadStrategy().generate_signals(enriched)
    # All signals False (because every call raised)
    assert not out["AAPL"]["buy_signal"].any()


def test_simple_strategy_entry_score_default_is_one():
    """If a subclass doesn't override entry_score, default is 1.0 across the board."""
    class _MinStrategy(SimpleStrategy):
        name = "min"
        default_params = {
            "stop_atr_mult": 1.5, "trail_tight_mult": 1.0,
            "trail_wide_mult": 2.0, "trail_tighten_atr": 1.5,
        }
        def entry_signal(self, row, prev, params):
            return True

    raw = {"SPY": _raw_ohlcv(seed=20), "AAPL": _raw_ohlcv(seed=21)}
    enriched = enrich_universe(raw, benchmark="SPY")
    out = _MinStrategy().generate_signals(enriched)
    # All bars after warmup get entry_score = 1.0 (default)
    df = out["AAPL"]
    valid = df["ATR"].notna() & (df["ATR"] > 0)
    assert (df.loc[valid, "entry_score"] == 1.0).all()


def test_simple_strategy_entry_stop_uses_atr_mult():
    """entry_stop column must equal Close - stop_atr_mult * ATR."""
    class _T(SimpleStrategy):
        name = "t"
        default_params = {
            "stop_atr_mult": 2.0, "trail_tight_mult": 1.0,
            "trail_wide_mult": 2.0, "trail_tighten_atr": 1.5,
        }
        def entry_signal(self, row, prev, params):
            return False

    raw = {"AAPL": _raw_ohlcv(seed=30)}
    enriched = enrich_universe(raw, benchmark="SPY")
    out = _T().generate_signals(enriched)
    df = out["AAPL"]
    valid = df["ATR"].notna() & (df["ATR"] > 0)
    expected = df.loc[valid, "Close"] - 2.0 * df.loc[valid, "ATR"]
    assert np.allclose(df.loc[valid, "entry_stop"].values, expected.values)
