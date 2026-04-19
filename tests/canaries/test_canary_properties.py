"""Unit tests for canary strategies — synthetic OHLCV, no real data needed."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradelab.canaries import LeakCanary, OverfitCanary, RandCanary, SurvivorCanary
from tradelab.canaries.survivor_canary import CURATED_UNIVERSE


def _make_ohlcv(n_bars=500, start="2022-01-03", drift=0.0005, vol=0.015, seed=7):
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start=start, periods=n_bars, freq="B")
    returns = rng.normal(loc=drift, scale=vol, size=n_bars)
    close = 100.0 * np.exp(np.cumsum(returns))
    high = close * (1.0 + np.abs(rng.normal(0.0, 0.004, n_bars)))
    low = close * (1.0 - np.abs(rng.normal(0.0, 0.004, n_bars)))
    openp = np.concatenate([[close[0]], close[:-1]])
    volume = rng.integers(800_000, 5_000_000, n_bars)
    return pd.DataFrame({
        "Date": dates, "Open": openp,
        "High": np.maximum.reduce([openp, close, high]),
        "Low":  np.minimum.reduce([openp, close, low]),
        "Close": close, "Volume": volume,
    })


@pytest.fixture
def sample_data():
    return {"TEST": _make_ohlcv(n_bars=500, seed=1)}


@pytest.fixture
def multi_symbol_data():
    return {f"SYM{i}": _make_ohlcv(n_bars=500, seed=10 + i) for i in range(5)}


REQUIRED_COLUMNS = {"Date", "Open", "High", "Low", "Close", "Volume",
                    "ATR", "SMA50", "buy_signal", "entry_stop", "entry_score"}


@pytest.mark.parametrize("canary_cls", [RandCanary, OverfitCanary, LeakCanary, SurvivorCanary])
def test_canary_output_columns_present(canary_cls, sample_data):
    out = canary_cls().generate_signals(sample_data)
    df = out["TEST"]
    missing = REQUIRED_COLUMNS - set(df.columns)
    assert not missing
    assert df["buy_signal"].dtype == bool


def test_rand_canary_signal_frequency(sample_data):
    out = RandCanary(params={"seed": 42, "entry_probability": 0.02}).generate_signals(sample_data)
    n = int(out["TEST"]["buy_signal"].sum())
    assert 2 <= n <= 25


def test_rand_canary_is_deterministic(sample_data):
    a = RandCanary(params={"seed": 123}).generate_signals(sample_data)["TEST"]["buy_signal"]
    b = RandCanary(params={"seed": 123}).generate_signals(sample_data)["TEST"]["buy_signal"]
    assert a.equals(b)


def test_rand_canary_different_seeds_differ(sample_data):
    a = RandCanary(params={"seed": 1}).generate_signals(sample_data)["TEST"]["buy_signal"]
    b = RandCanary(params={"seed": 2}).generate_signals(sample_data)["TEST"]["buy_signal"]
    assert not a.equals(b)


def test_rand_canary_per_symbol_independence(multi_symbol_data):
    out = RandCanary(params={"seed": 42}).generate_signals(multi_symbol_data)
    series = [out[s]["buy_signal"].reset_index(drop=True) for s in sorted(out.keys())]
    any_differ = any(not series[0].equals(s) for s in series[1:])
    assert any_differ


def test_overfit_canary_respects_param_bounds(sample_data):
    out = OverfitCanary(params={"rsi_threshold": 0.0, "atr_low": 99.0, "atr_high": 99.5}).generate_signals(sample_data)
    assert out["TEST"]["buy_signal"].sum() == 0


def test_leak_canary_signal_predicts_future(sample_data):
    out = LeakCanary(params={"up_threshold": 0.01}).generate_signals(sample_data)
    df = out["TEST"].reset_index(drop=True)
    signals = df["buy_signal"].values
    close = df["Close"].values
    idx = np.where(signals[:-1])[0]
    if len(idx) == 0:
        pytest.skip("No leak signals on this fixture seed.")
    ret_next = (close[idx + 1] / close[idx]) - 1.0
    assert ret_next.mean() > 0.005


def test_leak_canary_signal_breaks_when_shifted(sample_data):
    out = LeakCanary().generate_signals(sample_data)
    df = out["TEST"].reset_index(drop=True)
    signals = df["buy_signal"].values
    close = df["Close"].values
    idx0 = np.where(signals[:-1])[0]
    if len(idx0) < 3:
        pytest.skip("Too few leak signals.")
    ret0 = (close[idx0 + 1] / close[idx0]) - 1.0
    shifted = np.concatenate([[False], signals[:-1]])
    idx1 = np.where(shifted[:-1])[0]
    ret1 = (close[idx1 + 1] / close[idx1]) - 1.0
    assert ret0.mean() > ret1.mean() + 0.005


def test_leak_canary_tail_bars_are_zero(sample_data):
    out = LeakCanary(params={"lookahead_bars": 3}).generate_signals(sample_data)
    assert not out["TEST"]["buy_signal"].iloc[-3:].any()


def test_survivor_canary_signals_only_on_golden_cross(sample_data):
    out = SurvivorCanary().generate_signals(sample_data)
    assert int(out["TEST"]["buy_signal"].sum()) <= 10


def test_survivor_canary_curated_universe_is_exposed():
    assert SurvivorCanary.CURATED_UNIVERSE == CURATED_UNIVERSE
    assert len(SurvivorCanary.CURATED_UNIVERSE) == 5


@pytest.mark.parametrize("canary_cls", [RandCanary, OverfitCanary, LeakCanary, SurvivorCanary])
def test_no_signals_during_atr_warmup(canary_cls, sample_data):
    out = canary_cls().generate_signals(sample_data)
    df = out["TEST"]
    assert not df.loc[df["ATR"].isna(), "buy_signal"].any()
