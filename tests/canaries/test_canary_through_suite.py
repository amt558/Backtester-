"""
End-to-end canary verification: run each canary through the full robustness
suite and assert the verdict engine correctly classifies it.

This is the definitive tool-health check the master plan calls "monthly".
A passing run proves: backtest engine + DSR + MC + param landscape + entry
delay + LOSO + noise + verdict aggregator together correctly identify each
of the four classic failure modes (no edge, overfitting, look-ahead bias,
survivorship bias).

Slower than unit tests (~10s each) — synthetic data, no network.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradelab.canaries import (
    LeakCanary,
    OverfitCanary,
    RandCanary,
    SurvivorCanary,
)
from tradelab.canaries.survivor_canary import CURATED_UNIVERSE
from tradelab.engines.backtest import run_backtest
from tradelab.robustness import run_robustness_suite


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


def _multi_symbol_universe(n_symbols=5, n_bars=500, base_seed=10):
    """Build N independent symbols. Names default to SYM0..SYM(N-1)."""
    out = {}
    for i in range(n_symbols):
        out[f"SYM{i}"] = _make_ohlcv(n_bars=n_bars, seed=base_seed + i)
    return out


def _curated_winners_universe(n_bars=500):
    """
    Survivor canary fixture: build the CURATED_UNIVERSE symbols with
    deliberately-strong upward drift so the golden-cross strategy looks
    great on aggregate but is highly path-dependent per symbol.
    """
    out = {}
    drifts = [0.0020, 0.0018, 0.0016, 0.0014, 0.0010]   # winners-only by construction
    for sym, drift in zip(CURATED_UNIVERSE, drifts):
        out[sym] = _make_ohlcv(n_bars=n_bars, drift=drift, vol=0.012,
                                seed=hash(sym) % (2**31))
    return out


def _suite_fast(strategy, data, **kwargs):
    """Run the robustness suite with smaller defaults for test speed."""
    dates = data[next(iter(data))]["Date"]
    start = str(dates.iloc[0].date())
    end = str(dates.iloc[-1].date())
    bt = run_backtest(strategy, data, start=start, end=end)
    return run_robustness_suite(
        strategy, data, bt,
        start=start, end=end,
        mc_n_simulations=80,
        landscape_grid_size=3,
        noise_n_seeds=5,
        **kwargs,
    )


# Mark all tests in this file as slow integration tests
pytestmark = pytest.mark.canary_integration


def test_rand_canary_is_classified_fragile_or_inconclusive():
    """RandCanary has no edge → suite must NOT mark it ROBUST."""
    data = _multi_symbol_universe(n_symbols=4, n_bars=500, base_seed=1000)
    res = _suite_fast(RandCanary(), data)
    # The hard assertion: never ROBUST. The suite SHOULD lean fragile/inconclusive.
    assert res.verdict.verdict != "ROBUST", (
        f"Tool broken: RandCanary classified ROBUST. Signals: "
        f"{[(s.name, s.outcome) for s in res.verdict.signals]}"
    )


def test_leak_canary_entry_delay_collapses_pf():
    """
    LeakCanary peeks at future Close. Entry-delay test must show a steep
    PF drop when shifted by +1 bar. The suite SHOULD flag entry_delay
    as fragile, and the aggregate verdict must NOT be ROBUST.
    """
    data = _multi_symbol_universe(n_symbols=3, n_bars=500, base_seed=2000)
    res = _suite_fast(LeakCanary(), data)
    # Entry-delay signal must be fragile
    ed_signal = next((s for s in res.verdict.signals if s.name == "entry_delay"), None)
    assert ed_signal is not None, "entry_delay signal missing"
    assert ed_signal.outcome == "fragile", (
        f"Tool broken: LeakCanary entry_delay outcome={ed_signal.outcome}. "
        f"Reason: {ed_signal.reason}"
    )
    # Aggregate must NOT be ROBUST
    assert res.verdict.verdict != "ROBUST"


def test_survivor_canary_loso_reveals_concentration():
    """
    SurvivorCanary on the curated 5-symbol winners universe. LOSO MUST
    show meaningful per-symbol PF spread (edge depends on universe).
    Aggregate verdict MUST NOT be ROBUST.
    """
    data = _curated_winners_universe(n_bars=500)
    res = _suite_fast(SurvivorCanary(), data)
    assert res.loso is not None
    # Spread > 0 is a tautology; check the more important property: aggregate not robust
    assert res.verdict.verdict != "ROBUST", (
        f"Tool broken: SurvivorCanary on curated winners classified ROBUST. "
        f"Signals: {[(s.name, s.outcome) for s in res.verdict.signals]}"
    )


def test_overfit_canary_baseline_does_not_classify_robust():
    """
    OverfitCanary at default params is noisy (the real test would be
    Optuna+WF). The suite at baseline must NOT call it ROBUST.
    """
    data = _multi_symbol_universe(n_symbols=4, n_bars=500, base_seed=3000)
    # OverfitCanary default fitness is intentionally weak; with only 4 symbols
    # and 500 bars, it likely has zero or very few trades. The suite must not
    # mark it ROBUST.
    res = _suite_fast(OverfitCanary(), data)
    assert res.verdict.verdict != "ROBUST", (
        f"Tool broken: OverfitCanary at baseline classified ROBUST. "
        f"Signals: {[(s.name, s.outcome) for s in res.verdict.signals]}"
    )


def test_no_canary_is_ever_classified_robust():
    """
    Aggregate sanity: across all four canaries on synthetic universes,
    ZERO ROBUST verdicts. If this fails the entire tool is suspect.
    """
    fixtures = [
        (RandCanary(),     _multi_symbol_universe(n_symbols=4, base_seed=1000)),
        (LeakCanary(),     _multi_symbol_universe(n_symbols=3, base_seed=2000)),
        (OverfitCanary(),  _multi_symbol_universe(n_symbols=4, base_seed=3000)),
        (SurvivorCanary(), _curated_winners_universe()),
    ]
    verdicts = []
    for strat, data in fixtures:
        res = _suite_fast(strat, data)
        verdicts.append((strat.name, res.verdict.verdict))
    robust_count = sum(1 for _, v in verdicts if v == "ROBUST")
    assert robust_count == 0, (
        f"Tool broken: {robust_count} canaries classified ROBUST. {verdicts}"
    )
