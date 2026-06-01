"""Tests for robustness diagnostic helpers (wf_decay, trade_efficiency)."""
from __future__ import annotations

from tradelab.results import (
    BacktestMetrics, BacktestResult, Trade,
    WalkForwardResult, WalkForwardWindow,
)
from tradelab.robustness.diagnostics import (
    compute_trade_efficiency, compute_wf_decay,
)


def _window(idx: int, gp: float, gl: float) -> WalkForwardWindow:
    """Build a minimal WF window with the given gross profit/loss in test_metrics."""
    pf = (gp / gl) if gl > 0 else 0.0
    metrics = BacktestMetrics(
        total_trades=20, wins=12, losses=8, win_rate=60.0,
        profit_factor=pf, gross_profit=gp, gross_loss=gl,
    )
    return WalkForwardWindow(
        index=idx,
        train_start="2022-01-01", train_end="2022-06-30",
        test_start="2022-07-01", test_end="2022-12-31",
        train_metrics=None, test_metrics=metrics, best_params={},
    )


def _wf(windows: list[WalkForwardWindow]) -> WalkForwardResult:
    return WalkForwardResult(
        strategy="x", n_windows=len(windows), windows=windows,
        wfe_ratio=0.8,
    )


def test_wf_decay_decay_pattern():
    """Late-half PF lower than early-half should give ratio < 1.0."""
    # 6 windows; first 3 strong, last 3 weak.
    # Early aggregate PF = 300/100 = 3.0; Late aggregate PF = 90/100 = 0.9
    # Ratio = 0.9 / 3.0 = 0.30
    windows = [
        _window(0, 100, 33), _window(1, 100, 33), _window(2, 100, 34),
        _window(3, 30, 33),  _window(4, 30, 33),  _window(5, 30, 34),
    ]
    result = compute_wf_decay(_wf(windows))
    assert result is not None
    assert abs(result - 0.30) < 0.01


def test_wf_decay_stable_pattern():
    """Equal PFs across windows should give ratio ~ 1.0."""
    windows = [_window(i, 100, 50) for i in range(6)]
    result = compute_wf_decay(_wf(windows))
    assert result is not None
    assert abs(result - 1.0) < 0.01


def test_wf_decay_improving_pattern():
    """Late-half PF higher than early-half should give ratio > 1.0."""
    # Early: 60/100 = 0.6 PF aggregate; Late: 200/100 = 2.0 PF aggregate.
    # Ratio = 2.0 / 0.6 = 3.33
    windows = [
        _window(0, 20, 33), _window(1, 20, 33), _window(2, 20, 34),
        _window(3, 65, 33), _window(4, 65, 33), _window(5, 70, 34),
    ]
    result = compute_wf_decay(_wf(windows))
    assert result is not None
    assert result > 2.0


def test_wf_decay_insufficient_windows_returns_none():
    """N < 4 valid windows should return None."""
    windows = [_window(i, 100, 50) for i in range(3)]
    assert compute_wf_decay(_wf(windows)) is None


def test_wf_decay_skips_windows_with_no_test_metrics():
    """Windows where test_metrics is None should be filtered out, not crash."""
    valid = [_window(i, 100, 50) for i in range(4)]
    # Add a window with no test_metrics
    no_metrics = WalkForwardWindow(
        index=4,
        train_start="2024-01-01", train_end="2024-06-30",
        test_start="2024-07-01", test_end="2024-12-31",
        train_metrics=None, test_metrics=None, best_params={},
    )
    result = compute_wf_decay(_wf(valid + [no_metrics]))
    assert result is not None  # 4 valid windows is enough
    assert abs(result - 1.0) < 0.01


def test_wf_decay_zero_gross_loss_returns_none():
    """If either half has zero gross_loss, PF undefined → return None."""
    # Late half has zero gross_loss in every window
    windows = [
        _window(0, 100, 50), _window(1, 100, 50),
        _window(2, 100, 0),  _window(3, 100, 0),
    ]
    assert compute_wf_decay(_wf(windows)) is None


def test_wf_decay_all_zero_metrics_returns_none():
    """Windows with all-zero metrics should produce None (no PF computable)."""
    windows = [_window(i, 0, 0) for i in range(6)]
    assert compute_wf_decay(_wf(windows)) is None


def _trade(pnl: float, mfe_pct: float, shares: int = 100,
           entry_price: float = 50.0) -> Trade:
    """Build a minimal Trade with the given pnl and mfe_pct."""
    return Trade(
        ticker="TEST",
        entry_date="2024-01-01", exit_date="2024-01-05",
        entry_price=entry_price, exit_price=entry_price + pnl / shares,
        shares=shares, pnl=pnl, pnl_pct=(pnl / (shares * entry_price)) * 100,
        bars_held=4, exit_reason="signal", mae_pct=0.0, mfe_pct=mfe_pct,
    )


def _bt_with_trades(trades: list[Trade]) -> BacktestResult:
    return BacktestResult(
        strategy="x", start_date="2024-01-01", end_date="2024-12-31",
        params={}, metrics=BacktestMetrics(), trades=trades, equity_curve=[],
    )


def test_trade_efficiency_winner_exact_capture():
    """Winner that captured exactly its MFE → ratio 1.0."""
    # entry=50, shares=100, mfe_pct=2.0 → ideal $ = 0.02 * 100 * 50 = 100.0
    # pnl = 100.0 → captured / ideal = 1.0
    trade = _trade(pnl=100.0, mfe_pct=2.0, shares=100, entry_price=50.0)
    result = compute_trade_efficiency(_bt_with_trades([trade]))
    assert result is not None
    assert abs(result - 1.0) < 0.001


def test_trade_efficiency_winner_half_capture():
    """Winner that captured half its MFE → ratio 0.5."""
    # ideal $ = 0.02 * 100 * 50 = 100.0; pnl = 50.0 → ratio 0.5
    trade = _trade(pnl=50.0, mfe_pct=2.0, shares=100, entry_price=50.0)
    result = compute_trade_efficiency(_bt_with_trades([trade]))
    assert result is not None
    assert abs(result - 0.5) < 0.001


def test_trade_efficiency_mixed_winners_and_losers():
    """Mix of winners and losers: portfolio aggregate."""
    # Winner: pnl=80, ideal=100  (efficiency 0.8 alone)
    # Loser:  pnl=-30, mfe_pct=1.0 → ideal = 0.01*100*50 = 50; pnl=-30 contributes -30
    # Aggregate: captured = 80 + (-30) = 50; ideal = 100 + 50 = 150
    # Ratio = 50/150 = 0.333
    winner = _trade(pnl=80.0, mfe_pct=2.0)
    loser = _trade(pnl=-30.0, mfe_pct=1.0)
    result = compute_trade_efficiency(_bt_with_trades([winner, loser]))
    assert result is not None
    assert abs(result - (50.0 / 150.0)) < 0.001


def test_trade_efficiency_empty_trades_returns_none():
    """No trades → None."""
    assert compute_trade_efficiency(_bt_with_trades([])) is None


def test_trade_efficiency_all_zero_mfe_returns_none():
    """All trades with mfe_pct=0 (old fixture) → ideal sum is 0 → None."""
    trades = [
        _trade(pnl=10.0, mfe_pct=0.0),
        _trade(pnl=-5.0, mfe_pct=0.0),
    ]
    assert compute_trade_efficiency(_bt_with_trades(trades)) is None


def test_trade_efficiency_loser_with_zero_mfe_drags_numerator():
    """Loser that never went favorable: contributes pnl to numerator,
    0 to denominator. Should NOT be filtered — that would hide real losses."""
    # Winner with mfe>0: ideal=100, pnl=80
    # Loser with mfe=0: ideal=0, pnl=-20
    # Aggregate: captured=60, ideal=100 → ratio 0.6
    winner = _trade(pnl=80.0, mfe_pct=2.0)
    loser = _trade(pnl=-20.0, mfe_pct=0.0)
    result = compute_trade_efficiency(_bt_with_trades([winner, loser]))
    assert result is not None
    assert abs(result - 0.60) < 0.001
