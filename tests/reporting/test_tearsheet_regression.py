"""Guard: the QuantStats tearsheet must render for a normal Python backtest,
and must raise a clear error (not crash) when there is no equity curve."""
from __future__ import annotations

import math

import pytest

from tradelab.results import BacktestResult, Trade
from tradelab.reporting.tearsheet import render_backtest_tearsheet


def _synthetic_bt(n: int = 260) -> BacktestResult:
    import datetime as dt
    start = dt.date(2023, 1, 2)
    curve = []
    eq = 100_000.0
    d = start
    for i in range(n):
        eq *= (1.0 + 0.0006 * math.sin(i / 9.0) + 0.0004)
        curve.append({"date": d.isoformat(), "equity": round(eq, 2)})
        d += dt.timedelta(days=1)
    return BacktestResult(
        strategy="qs_probe", start_date=curve[0]["date"], end_date=curve[-1]["date"],
        trades=[Trade(ticker="AAA", entry_date=curve[0]["date"], exit_date=curve[10]["date"],
                      entry_price=100, exit_price=110, shares=1, pnl=10, pnl_pct=10,
                      bars_held=10, exit_reason="test")],
        equity_curve=curve,
    )


def test_tearsheet_renders_nonempty_html(tmp_path):
    out = tmp_path / "ts.html"
    p = render_backtest_tearsheet(_synthetic_bt(), output_path=out, title="probe")
    assert p == out and out.exists()
    text = out.read_text(encoding="utf-8", errors="ignore")
    assert len(text) > 50_000
    assert "<html" in text.lower()


def test_tearsheet_empty_curve_raises_valueerror(tmp_path):
    bt = BacktestResult(strategy="empty", start_date="2024-01-01", end_date="2024-02-01")
    with pytest.raises(ValueError):
        render_backtest_tearsheet(bt, output_path=tmp_path / "x.html")
