"""
Tier-3 validation tests (engine re-runs): cost_sensitivity, random_entry_benchmark.

Uses a small deterministic strategy with a high entry rate so the random-entry
sims reliably produce trades — the percentile path is exercised without
depending on a real strategy firing on synthetic data. Kept fast: 2 symbols,
~260 bars, few sims.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from tradelab.engines.backtest import run_backtest
from tradelab.strategies.base import Strategy
from tradelab.validation.deep import (
    cost_sensitivity,
    gate_contribution_isolation,
    random_entry_benchmark,
    run_validation_suite_deep,
)
from tradelab.validation.suite import ValidationSignal


class _FreqStrat(Strategy):
    """Deterministic, high-frequency test strategy. Enters on up-days that also
    clear a param-controlled RSI-ish floor (so a gate can be ablated). Provides
    the ATR / entry_stop columns and trail params the engine needs."""
    name = "freqstrat"
    timeframe = "1D"
    requires_benchmark = False
    default_params = {
        "gain_floor": 0.0,   # entry gate: only enter when 1-bar return >= floor
        "stop_atr_mult": 2.0, "trail_tight_mult": 1.0,
        "trail_wide_mult": 2.0, "trail_tighten_atr": 1.5,
    }
    # opt-in gate map: neutralise the gain floor
    ablatable_gates = {"gain_floor": {"gain_floor": -1e9}}

    def generate_signals(self, data, spy_close=None):
        p = self.params
        out = {}
        for sym, df in data.items():
            df = df.copy()
            pc = df["Close"].shift(1)
            tr = pd.concat([df["High"] - df["Low"],
                            (df["High"] - pc).abs(),
                            (df["Low"] - pc).abs()], axis=1).max(axis=1)
            df["ATR"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
            ret1 = (df["Close"] / pc - 1.0) * 100.0
            df["buy_signal"] = ((df["Close"] > df["Open"]) &
                                (ret1 >= float(p["gain_floor"]))).fillna(False)
            df["entry_stop"] = df["Close"] - 2.0 * df["ATR"]
            df["entry_score"] = 1.0
            out[sym] = df
        return out


def _ohlcv(sym_seed: int, n: int = 260) -> pd.DataFrame:
    rng = np.random.default_rng(sym_seed)
    dates = pd.date_range("2022-01-03", periods=n, freq="B")
    rets = rng.normal(0.0015, 0.012, n)
    close = 100.0 * np.exp(np.cumsum(rets))
    high = close * (1 + np.abs(rng.normal(0, 0.005, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.005, n)))
    openp = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame({
        "Date": dates, "Open": openp, "High": high, "Low": low,
        "Close": close, "Volume": rng.integers(1_000_000, 5_000_000, n),
    })


@pytest.fixture(scope="module")
def universe():
    return {"AAA": _ohlcv(1), "BBB": _ohlcv(2)}


@pytest.fixture(scope="module")
def strat():
    return _FreqStrat()


@pytest.fixture(scope="module")
def baseline(universe, strat):
    return run_backtest(strat, universe)


# ── Cost sensitivity ─────────────────────────────────────────────────────────

def test_cost_sensitivity_returns_table(universe, strat):
    sig = cost_sensitivity(universe and strat and strat, universe)
    assert sig.name == "cost_sensitivity"
    assert sig.outcome in {"robust", "inconclusive", "fragile"}
    pts = sig.detail["points"]
    assert len(pts) >= 3
    # multipliers strictly increasing, each row has a pf
    mults = [p["multiplier"] for p in pts]
    assert mults == sorted(mults)
    # JSON-safe (PF can be inf when gross_loss==0)
    raw = sig.model_dump_json()
    for bad in ("Infinity", "-Infinity", "NaN"):
        assert bad not in raw


def test_cost_sensitivity_higher_cost_never_helps(universe, strat):
    sig = cost_sensitivity(strat, universe)
    pts = {p["multiplier"]: p for p in sig.detail["points"]}
    # more commission can only reduce (or hold) net return
    if 0.0 in pts and max(pts) in pts:
        assert pts[max(pts)]["pct_return"] <= pts[0.0]["pct_return"] + 1e-6


# ── Random entry benchmark ───────────────────────────────────────────────────

def test_random_entry_benchmark_percentile(universe, strat, baseline):
    sig = random_entry_benchmark(strat, universe, baseline, n_sims=20, seed=7)
    assert sig.name == "random_entry_benchmark"
    assert sig.outcome in {"robust", "inconclusive", "fragile"}
    if sig.value is not None:
        assert 0.0 <= sig.value <= 100.0
        assert sig.detail["n_sims_productive"] >= 10
        assert "real_pf" in sig.detail
    raw = sig.model_dump_json()
    for bad in ("Infinity", "-Infinity", "NaN"):
        assert bad not in raw


def test_random_entry_benchmark_is_deterministic(universe, strat, baseline):
    a = random_entry_benchmark(strat, universe, baseline, n_sims=15, seed=99)
    b = random_entry_benchmark(strat, universe, baseline, n_sims=15, seed=99)
    assert a.value == b.value
    assert a.detail.get("random_pf_mean") == b.detail.get("random_pf_mean")


def test_random_entry_wrapper_preserves_exit_params(universe, strat):
    # the wrapper must carry the real strategy's params so exits are identical
    from tradelab.validation.deep import _RandomEntryWrapper, _entry_rates
    rates = _entry_rates(strat, universe, None)
    w = _RandomEntryWrapper(strat, rates, seed=1)
    assert w.params == strat.params
    # and it still emits the engine's required columns
    sig = w.generate_signals(universe)
    df = next(iter(sig.values()))
    for col in ("buy_signal", "entry_stop", "ATR", "entry_score"):
        assert col in df.columns


def test_no_entries_is_inconclusive(universe, baseline):
    class _NeverStrat(_FreqStrat):
        def generate_signals(self, data, spy_close=None):
            sig = super().generate_signals(data, spy_close=spy_close)
            for df in sig.values():
                df["buy_signal"] = False
            return sig
    sig = random_entry_benchmark(_NeverStrat(), universe, baseline, n_sims=12)
    assert sig.outcome == "inconclusive"


# ── Orchestrator + invariants ────────────────────────────────────────────────

# ── Gate contribution isolation ──────────────────────────────────────────────

def test_gate_isolation_runs_per_declared_gate(universe, strat, baseline):
    sig = gate_contribution_isolation(strat, universe, baseline)
    assert sig.name == "gate_contribution_isolation"
    assert sig.outcome in {"robust", "inconclusive", "fragile"}
    gate_names = [g["gate"] for g in sig.detail["gates"]]
    assert gate_names == list(strat.ablatable_gates.keys())
    for g in sig.detail["gates"]:
        assert "ablated_pf" in g and "delta_pf" in g
    raw = sig.model_dump_json()
    for bad in ("Infinity", "-Infinity", "NaN"):
        assert bad not in raw


def test_gate_isolation_inconclusive_without_map(universe, baseline):
    class _NoGates(_FreqStrat):
        ablatable_gates = {}
    sig = gate_contribution_isolation(_NoGates(), universe, baseline)
    assert sig.outcome == "inconclusive"
    assert "no ablatable" in sig.reason.lower()


def test_gate_isolation_ablation_uses_override(universe, strat, baseline):
    # ablating gain_floor (-1e9) should let MORE bars qualify -> ablated run
    # trades at least as much as baseline on at least one gate.
    sig = gate_contribution_isolation(strat, universe, baseline)
    base_trades = baseline.metrics.total_trades
    assert any(g["ablated_trades"] >= base_trades for g in sig.detail["gates"])


# ── Orchestrator + invariants ────────────────────────────────────────────────

def test_run_validation_suite_deep_returns_three_signals(universe, strat, baseline):
    sigs = run_validation_suite_deep(strat, universe, baseline, n_sims=12)
    assert [s.name for s in sigs] == [
        "cost_sensitivity", "gate_contribution_isolation", "random_entry_benchmark"]
    for s in sigs:
        assert isinstance(s, ValidationSignal)


def test_deep_layer_does_not_import_verdict_engine():
    import ast

    import tradelab.validation.deep as deep_mod

    tree = ast.parse(open(deep_mod.__file__, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert "verdict" not in (node.module or "")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert "verdict" not in alias.name
        elif isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            assert name != "compute_verdict"
