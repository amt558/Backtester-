"""
Tier-1 validation suite tests.

The validation suite is a PARALLEL, REPORT-ONLY layer. These tests assert two
things above all:

  1. The numeric facts each test reports (streaks, monthly PF, rolling
     expectancy) are computed correctly off the real `trades[]` ledger.
  2. The layer is verdict-neutral and JSON-safe — it never imports the verdict
     engine, and its serialized form round-trips through `json.loads` with no
     `Infinity`/`NaN` tokens (which would break the dashboard's JSON.parse).

Cosmetic outcome thresholds (robust/inconclusive/fragile) only colour a future
panel; they can never move a verdict. They are asserted loosely.
"""
from __future__ import annotations

import json

import pytest

import pandas as pd

from tradelab.results import BacktestResult, Trade
from tradelab.validation.suite import (
    ValidationReport,
    ValidationSignal,
    drawdown_stress,
    expectancy_stability,
    pf_by_month,
    run_validation_suite,
    volatility_bucketing,
    win_loss_streak,
)


def _trade(entry_date: str, pnl: float, pnl_pct: float | None = None,
           ticker: str = "TEST", exit_date: str | None = None) -> Trade:
    """Minimal Trade with only the fields the validation suite reads."""
    return Trade(
        ticker=ticker,
        entry_date=entry_date,
        exit_date=exit_date or entry_date,
        entry_price=100.0,
        exit_price=100.0 + pnl,
        shares=1,
        pnl=pnl,
        pnl_pct=pnl_pct if pnl_pct is not None else pnl,
        bars_held=1,
        exit_reason="test",
    )


def _bt(trades: list[Trade], equity_curve: list[dict] | None = None,
        timeframe: str = "1D") -> BacktestResult:
    return BacktestResult(
        strategy="unit-test",
        timeframe=timeframe,
        start_date="2024-01-01",
        end_date="2024-12-31",
        trades=trades,
        equity_curve=equity_curve or [],
    )


# ── Win/Loss Streak ──────────────────────────────────────────────────────────

def test_streak_basic_max_runs():
    # Sequence: + + + - - + - - - -   (chronological by entry_date)
    pnls = [10, 10, 10, -5, -5, 10, -5, -5, -5, -5]
    trades = [_trade(f"2024-01-{i+1:02d}", p) for i, p in enumerate(pnls)]
    sig = win_loss_streak(_bt(trades))
    assert sig.name == "win_loss_streak"
    assert sig.detail["max_win_streak"] == 3
    assert sig.detail["max_loss_streak"] == 4
    # current streak ends on the trailing 4-loss run
    assert sig.detail["current_streak"] == -4
    # `value` surfaces the fragility-relevant number (max loss streak)
    assert sig.value == 4
    # the number must be embedded in `reason` so the existing FE regex picks it
    assert "4" in sig.reason


def test_streak_unsorted_input_is_sorted_chronologically():
    # Same data, shuffled order — result must be identical to the sorted case.
    pnls = [10, 10, 10, -5, -5, 10, -5, -5, -5, -5]
    trades = [_trade(f"2024-01-{i+1:02d}", p) for i, p in enumerate(pnls)]
    shuffled = [trades[i] for i in (5, 0, 9, 2, 7, 1, 4, 8, 3, 6)]
    assert win_loss_streak(_bt(shuffled)).detail == win_loss_streak(_bt(trades)).detail


def test_streak_empty_ledger_is_inconclusive():
    sig = win_loss_streak(_bt([]))
    assert sig.outcome == "inconclusive"


# ── PF by Month ──────────────────────────────────────────────────────────────

def test_pf_by_month_grouping_and_values():
    trades = [
        _trade("2024-01-05", 100), _trade("2024-01-10", 50), _trade("2024-01-20", -60),
        _trade("2024-02-05", 30), _trade("2024-02-10", -10), _trade("2024-02-20", -20),
        _trade("2024-03-05", 40), _trade("2024-03-10", 60),  # no losses
    ]
    sig = pf_by_month(_bt(trades))
    months = {m["month"]: m for m in sig.detail["months"]}
    assert set(months) == {"2024-01", "2024-02", "2024-03"}
    assert months["2024-01"]["pf"] == pytest.approx(2.5)      # 150 / 60
    assert months["2024-02"]["pf"] == pytest.approx(1.0)      # 30 / 30
    assert months["2024-03"]["no_losses"] is True            # capped, flagged
    assert months["2024-03"]["pf"] < float("inf")            # never raw inf
    # all three months are profitable (pf >= 1)
    assert sig.value == pytest.approx(1.0)


def test_pf_by_month_uses_entry_month_not_exit_month():
    # entry in Jan, exit in Feb -> counts under Jan
    trades = [_trade("2024-01-28", 100, exit_date="2024-02-03")]
    sig = pf_by_month(_bt(trades))
    assert [m["month"] for m in sig.detail["months"]] == ["2024-01"]


def test_pf_by_month_empty_is_inconclusive():
    assert pf_by_month(_bt([])).outcome == "inconclusive"


# ── Expectancy Stability (rolling 20-trade) ──────────────────────────────────

def test_expectancy_stability_all_positive_is_robust():
    trades = [_trade(f"2024-01-{i+1:02d}", 5, pnl_pct=1.0) for i in range(25)]
    sig = expectancy_stability(_bt(trades))
    assert sig.detail["window"] == 20
    assert sig.detail["n_windows"] == 6           # 25 - 20 + 1
    assert sig.value == pytest.approx(1.0)        # every window positive
    assert sig.outcome == "robust"


def test_expectancy_stability_too_few_trades_is_inconclusive():
    trades = [_trade(f"2024-01-{i+1:02d}", 5, pnl_pct=1.0) for i in range(19)]
    sig = expectancy_stability(_bt(trades))
    assert sig.outcome == "inconclusive"
    assert sig.detail["n_windows"] == 0


def test_expectancy_stability_negative_overall_is_fragile():
    trades = [_trade(f"2024-02-{i+1:02d}", -5, pnl_pct=-1.0) for i in range(25)]
    sig = expectancy_stability(_bt(trades))
    assert sig.outcome == "fragile"


# ── Report wiring + invariants ───────────────────────────────────────────────

def test_run_validation_suite_returns_all_five_signals():
    trades = [_trade(f"2024-01-{(i % 28)+1:02d}", 5 if i % 2 else -5, pnl_pct=1.0 if i % 2 else -1.0)
              for i in range(40)]
    # No OHLCV loader injected -> volatility_bucketing falls back to the parquet
    # cache, which is absent here, so it must degrade to inconclusive (never fetch).
    report = run_validation_suite(_bt(trades))
    assert isinstance(report, ValidationReport)
    names = {s.name for s in report.signals}
    assert names == {"win_loss_streak", "expectancy_stability", "pf_by_month",
                     "drawdown_stress", "volatility_bucketing"}
    for s in report.signals:
        assert isinstance(s, ValidationSignal)
        assert s.outcome in {"robust", "inconclusive", "fragile"}


def test_report_is_json_safe_no_inf_or_nan():
    # No-loss month would naively produce inf PF; assert serialization is clean.
    trades = [_trade(f"2024-0{m}-05", 100, pnl_pct=2.0) for m in (1, 2, 3)]
    report = run_validation_suite(_bt(trades))
    raw = report.model_dump_json()
    # invalid-JSON tokens that JSON.parse() in the browser would reject
    for bad in ("Infinity", "-Infinity", "NaN"):
        assert bad not in raw, f"serialized report contains {bad!r}"
    json.loads(raw)  # must parse without error


def test_validation_layer_does_not_import_verdict_engine():
    # Verdict-neutrality is structural: the validation package must not import
    # the verdict module/aggregator or call it. Use the AST so docstring prose
    # that *mentions* compute_verdict (explaining why we avoid it) doesn't
    # trigger a false positive.
    import ast

    import tradelab.validation.suite as suite_mod

    tree = ast.parse(open(suite_mod.__file__, encoding="utf-8").read())
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert "verdict" not in (node.module or ""), f"imports verdict: {node.module}"
            for alias in node.names:
                imported_names.add(alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert "verdict" not in alias.name, f"imports verdict: {alias.name}"
        elif isinstance(node, ast.Call):
            fn = node.func
            name = getattr(fn, "id", None) or getattr(fn, "attr", None)
            assert name != "compute_verdict", "calls compute_verdict()"
    assert "compute_verdict" not in imported_names
    assert "VerdictResult" not in imported_names


def test_signals_carry_value_and_embed_number_in_reason():
    trades = [_trade(f"2024-01-{i+1:02d}", 5 if i % 3 else -5,
                     pnl_pct=1.0 if i % 3 else -1.0) for i in range(25)]
    report = run_validation_suite(_bt(trades))
    for s in report.signals:
        if s.value is not None:
            # FE _sigShortValue() regex: P\d+ | \d+(\.\d+)?%?
            import re
            assert re.search(r"P\d+|\d+(?:\.\d+)?%?", s.reason), s.reason


# ── Tier 2: Drawdown Stress (equity_curve scan) ──────────────────────────────

def _linspace(a: float, b: float, n: int) -> list[float]:
    if n == 1:
        return [a]
    return [a + (b - a) * i / (n - 1) for i in range(n)]


def test_drawdown_stress_finds_worst_short_window():
    # Daily equity: rise 100->120 over 10 days, crash 120->90 over the next 7
    # days (a 25% peak-to-trough inside one week), then recover to 130.
    dates = pd.date_range("2024-01-01", periods=31, freq="D").strftime("%Y-%m-%d").tolist()
    eq = _linspace(100, 120, 11) + _linspace(120, 90, 8)[1:] + _linspace(90, 130, 14)[1:]
    curve = [{"date": d, "equity": e} for d, e in zip(dates, eq)]
    sig = drawdown_stress(_bt([], equity_curve=curve))
    assert sig.name == "drawdown_stress"
    # worst 14-day drawdown magnitude ~25%
    assert sig.detail["worst_14d_dd_pct"] == pytest.approx(25.0, abs=0.5)
    assert sig.detail["worst_21d_dd_pct"] == pytest.approx(25.0, abs=0.5)
    assert sig.value == pytest.approx(25.0, abs=0.5)
    assert "25" in sig.reason.replace(".0", "")  # number embedded for FE regex


def test_drawdown_stress_empty_curve_is_inconclusive():
    assert drawdown_stress(_bt([], equity_curve=[])).outcome == "inconclusive"


def test_drawdown_stress_handles_irregular_dates():
    # per-trade-style irregular curve (gaps of days/weeks) must not crash
    curve = [
        {"date": "2024-01-02", "equity": 100.0},
        {"date": "2024-01-15", "equity": 110.0},
        {"date": "2024-01-20", "equity": 95.0},
        {"date": "2024-03-01", "equity": 120.0},
    ]
    sig = drawdown_stress(_bt([], equity_curve=curve))
    assert sig.outcome in {"robust", "inconclusive", "fragile"}
    # 110 -> 95 within 5 days = ~13.6% inside both windows
    assert sig.detail["worst_14d_dd_pct"] == pytest.approx(13.6, abs=0.5)


# ── Tier 2: Volatility Bucketing (ATR% from parquet, injected loader) ─────────

def _ohlcv(dates: list[str], highs, lows, closes) -> pd.DataFrame:
    return pd.DataFrame({
        "Date": pd.to_datetime(dates),
        "Open": closes, "High": highs, "Low": lows,
        "Close": closes, "Volume": [1_000_000] * len(dates),
    })


def test_volatility_bucketing_cache_miss_is_inconclusive():
    # loader returns None for every symbol -> nothing bucketable -> inconclusive,
    # and crucially it must NOT attempt any download/fetch.
    trades = [_trade(f"2024-02-{i+1:02d}", 5, ticker="AAPL") for i in range(10)]
    sig = volatility_bucketing(_bt(trades), ohlcv_loader=lambda sym, tf: None)
    assert sig.name == "volatility_bucketing"
    assert sig.outcome == "inconclusive"
    assert "no cached" in sig.reason.lower() or "ohlcv" in sig.reason.lower()


def test_volatility_bucketing_buckets_trades_by_atr():
    # 250 daily bars: first half calm (tiny range), second half volatile (wide
    # range) so ATR% climbs. Trades span both regimes.
    n = 250
    dates = pd.date_range("2023-01-02", periods=n, freq="B").strftime("%Y-%m-%d").tolist()
    closes = [100.0] * n
    calm_h = [100.3] * (n // 2)
    calm_l = [99.7] * (n // 2)
    vol_h = [104.0] * (n - n // 2)
    vol_l = [96.0] * (n - n // 2)
    df = _ohlcv(dates, calm_h + vol_h, calm_l + vol_l, closes)

    # one trade per ~every 10th bar, after ATR warmup
    trades = [_trade(dates[i], pnl=5 if i < n // 2 else -5,
                     pnl_pct=1.0 if i < n // 2 else -1.0, ticker="AAPL")
              for i in range(30, n, 8)]

    sig = volatility_bucketing(_bt(trades, timeframe="1D"),
                               ohlcv_loader=lambda sym, tf: df)
    assert sig.outcome in {"robust", "inconclusive", "fragile"}
    buckets = sig.detail["buckets"]
    assert len(buckets) >= 2
    # every bucketable trade landed in some bucket
    assert sum(b["n_trades"] for b in buckets) == sig.detail["n_bucketable"]
    assert sig.detail["n_bucketable"] > 0
    # JSON-safe
    raw = sig.model_dump_json()
    for bad in ("Infinity", "-Infinity", "NaN"):
        assert bad not in raw


def test_volatility_bucketing_too_few_trades_is_inconclusive():
    df = _ohlcv(
        pd.date_range("2023-01-02", periods=60, freq="B").strftime("%Y-%m-%d").tolist(),
        [101] * 60, [99] * 60, [100] * 60,
    )
    trades = [_trade("2023-02-01", 5, ticker="AAPL")]
    sig = volatility_bucketing(_bt(trades), ohlcv_loader=lambda sym, tf: df)
    assert sig.outcome == "inconclusive"


def test_volatility_bucketing_never_calls_default_cache_when_loader_injected(monkeypatch):
    # Structural guard: an injected loader must fully replace the parquet cache.
    import tradelab.validation.suite as suite_mod

    called = {"n": 0}

    def _boom(*a, **k):
        called["n"] += 1
        raise AssertionError("cache.read must not be called when a loader is injected")

    monkeypatch.setattr(suite_mod.cache, "read", _boom, raising=True)
    trades = [_trade(f"2024-02-{i+1:02d}", 5, ticker="AAPL") for i in range(10)]
    volatility_bucketing(_bt(trades), ohlcv_loader=lambda sym, tf: None)
    assert called["n"] == 0
