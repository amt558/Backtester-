"""Smart screener tests."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradelab.engines.screener import (
    ScreenResult,
    _composite_score,
    render_screen_html,
    run_screener,
)
from tradelab.marketdata import enrich_universe
from tradelab.results import BacktestMetrics
from tradelab.strategies.s2_pocket_pivot import S2PocketPivot


def _raw_ohlcv(n=200, seed=0, drift=0.001, vol=0.012):
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
        "AAPL": _raw_ohlcv(seed=2, drift=0.0011),
        "MSFT": _raw_ohlcv(seed=3, drift=0.0008),
        "NVDA": _raw_ohlcv(seed=4, drift=0.0014),
    }
    return enrich_universe(raw, benchmark="SPY")


def test_composite_score_zero_when_too_few_trades():
    m = BacktestMetrics(total_trades=2, profit_factor=2.0, max_drawdown_pct=-5.0)
    assert _composite_score(m, min_trades=5) == 0.0


def test_composite_score_negative_when_pf_below_one():
    m = BacktestMetrics(total_trades=20, profit_factor=0.7, max_drawdown_pct=-10.0)
    assert _composite_score(m) < 0


def test_composite_score_positive_for_winners():
    m = BacktestMetrics(total_trades=50, profit_factor=1.8, max_drawdown_pct=-8.0)
    assert _composite_score(m) > 0


def test_run_screener_returns_one_row_per_non_benchmark(enriched):
    spy = enriched["SPY"].set_index("Date")["Close"]
    res = run_screener(S2PocketPivot(), enriched, benchmark="SPY",
                        spy_close=spy, start="2023-01-02", end="2024-06-30")
    assert isinstance(res, ScreenResult)
    # 4 input symbols (SPY + 3 traded) → 3 rows (SPY excluded)
    assert res.n_symbols == 3
    assert len(res.rows) == 3
    syms = {r.symbol for r in res.rows}
    assert syms == {"AAPL", "MSFT", "NVDA"}


def test_run_screener_results_sorted_descending(enriched):
    spy = enriched["SPY"].set_index("Date")["Close"]
    res = run_screener(S2PocketPivot(), enriched, benchmark="SPY",
                        spy_close=spy, start="2023-01-02", end="2024-06-30")
    scores = [r.composite_score for r in res.rows]
    assert scores == sorted(scores, reverse=True)


def test_screen_result_top_returns_n_symbols(enriched):
    spy = enriched["SPY"].set_index("Date")["Close"]
    res = run_screener(S2PocketPivot(), enriched, benchmark="SPY",
                        spy_close=spy, start="2023-01-02", end="2024-06-30")
    top2 = res.top(2)
    assert len(top2) == 2
    assert top2[0] in {"AAPL", "MSFT", "NVDA"}


def test_screen_result_filter_drops_low_quality(enriched):
    spy = enriched["SPY"].set_index("Date")["Close"]
    res = run_screener(S2PocketPivot(), enriched, benchmark="SPY",
                        spy_close=spy, start="2023-01-02", end="2024-06-30")
    # Filter so aggressive nothing passes
    filtered = res.filter(min_trades=10000, min_pf=99)
    assert filtered.n_symbols == 0
    assert len(filtered.rows) == 0


def test_screen_result_progress_callback_invoked(enriched):
    spy = enriched["SPY"].set_index("Date")["Close"]
    calls = []
    def cb(sym, idx, total):
        calls.append((sym, idx, total))
    run_screener(S2PocketPivot(), enriched, benchmark="SPY",
                  spy_close=spy, start="2023-01-02", end="2024-06-30",
                  progress_cb=cb)
    assert len(calls) == 3
    assert all(c[2] == 3 for c in calls)


def test_render_screen_html_writes_file(enriched, tmp_path):
    spy = enriched["SPY"].set_index("Date")["Close"]
    res = run_screener(S2PocketPivot(), enriched, benchmark="SPY",
                        spy_close=spy, start="2023-01-02", end="2024-06-30")
    out = tmp_path / "screen.html"
    render_screen_html(res, out)
    assert out.exists()
    content = out.read_text()
    assert "<table" in content
    assert "AAPL" in content
    assert "Composite score" in content
