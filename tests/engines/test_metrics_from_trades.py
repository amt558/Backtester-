"""metrics_from_trades — derive BacktestMetrics from an arbitrary trade list."""
from __future__ import annotations

import pytest

from tradelab.engines._diagnostics import metrics_from_trades
from tradelab.results import Trade


def _t(pnl: float, pnl_pct: float, bars: int = 3,
       entry: str = "2024-01-01", exit_: str = "2024-01-04") -> Trade:
    # Round-trip-friendly synthetic trade.
    return Trade(
        ticker="X", entry_date=entry, exit_date=exit_,
        entry_price=100.0, exit_price=100.0 + pnl_pct, shares=1,
        pnl=pnl, pnl_pct=pnl_pct, bars_held=bars, exit_reason="t",
    )


def test_empty_trades_returns_zero_metrics():
    m = metrics_from_trades([], starting_equity=100_000.0)
    assert m.total_trades == 0
    assert m.profit_factor == 0.0
    assert m.win_rate == 0.0
    assert m.final_equity == 100_000.0


def test_basic_metrics_three_wins_two_losses():
    trades = [
        _t(100.0, 1.0), _t(-50.0, -0.5), _t(200.0, 2.0),
        _t(-100.0, -1.0), _t(150.0, 1.5),
    ]
    m = metrics_from_trades(trades, starting_equity=10_000.0)
    assert m.total_trades == 5
    assert m.wins == 3
    assert m.losses == 2
    assert m.win_rate == 60.0
    assert m.gross_profit == 450.0
    assert m.gross_loss == 150.0
    assert m.profit_factor == 3.0
    assert m.net_pnl == 300.0
    assert m.final_equity == 10_300.0
    assert round(m.pct_return, 4) == 3.0


def test_max_drawdown_is_negative_percent_of_peak():
    # Two wins lift equity to 10_300, then a loss takes it to 10_000 (~-2.91%).
    trades = [_t(200.0, 2.0), _t(100.0, 1.0), _t(-300.0, -3.0)]
    m = metrics_from_trades(trades, starting_equity=10_000.0)
    assert m.max_drawdown_pct < 0
    assert round(m.max_drawdown_pct, 2) == round(-300.0 / 10_300.0 * 100, 2)


def test_avg_bars_held_is_mean_of_bar_counts():
    trades = [_t(10, 0.1, bars=2), _t(10, 0.1, bars=4), _t(10, 0.1, bars=6)]
    m = metrics_from_trades(trades, starting_equity=100_000.0)
    assert m.avg_bars_held == 4.0


def test_zero_starting_equity_raises_value_error():
    with pytest.raises(ValueError) as exc:
        metrics_from_trades([_t(100.0, 1.0)], starting_equity=0.0)
    assert "starting_equity" in str(exc.value).lower()


def test_negative_starting_equity_raises_value_error():
    with pytest.raises(ValueError) as exc:
        metrics_from_trades([_t(100.0, 1.0)], starting_equity=-1000.0)
    assert "starting_equity" in str(exc.value).lower()
