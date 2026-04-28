"""Test distributional TE / Decay / K-S engine."""
from __future__ import annotations
from pathlib import Path
import pytest
from tradelab.live.tracking_error import (
    compute_tracking_error,
    TrackingErrorResult,
    TE_GREEN_THRESHOLD,
    TE_AMBER_THRESHOLD,
)


def _write_tv_trades(card_dir: Path, profits_pct: list[float]) -> None:
    """Write a synthetic tv_trades.csv with given exit profit_pct per trade."""
    card_dir.mkdir(parents=True, exist_ok=True)
    rows = ["Trade #,Type,Signal,Date/Time,Price USD,Contracts,Profit USD,Profit %"]
    for i, p in enumerate(profits_pct, start=1):
        rows.append(f"{i},Entry long,enter,2026-01-{(i % 28) + 1:02d} 09:30:00,100.00,10,,")
        rows.append(f"{i},Exit long,exit,2026-01-{(i % 28) + 1:02d} 15:00:00,{100*(1+p/100):.2f},10,{p*10:.2f},{p:.2f}")
    (card_dir / "tv_trades.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_insufficient_sample_returns_status(tmp_path: Path) -> None:
    _write_tv_trades(tmp_path / "alpha-v1", [1.0, 2.0, -1.0, 0.5, 1.5] * 6)  # 30 backtest
    live_returns_pct = [1.2, 0.8, -0.5]  # only 3 live fills
    result = compute_tracking_error(
        backtest_csv=tmp_path / "alpha-v1" / "tv_trades.csv",
        live_returns_pct=live_returns_pct,
    )
    assert result.status == "insufficient"
    assert result.n_live_trades == 3
    assert result.te is None
    assert result.ks_p is None


def test_te_ratio_above_threshold_marks_green(tmp_path: Path) -> None:
    backtest = [1.0, -0.5, 1.5, -0.3, 2.0] * 6  # n=30, mean=0.74%, ~PF=2.0
    _write_tv_trades(tmp_path / "alpha-v1", backtest)
    live = [0.9, -0.4, 1.4, -0.3, 1.8] * 6  # n=30
    result = compute_tracking_error(
        backtest_csv=tmp_path / "alpha-v1" / "tv_trades.csv",
        live_returns_pct=live,
    )
    assert result.status == "ok"
    assert result.te is not None
    assert result.te > TE_GREEN_THRESHOLD  # >= 0.80
    assert result.ks_p is not None
    assert result.ks_p > 0.05  # similar distributions


def test_te_ratio_below_amber_threshold(tmp_path: Path) -> None:
    backtest = [2.0, -0.3, 2.0, -0.3, 2.0] * 6  # PF very high
    _write_tv_trades(tmp_path / "alpha-v1", backtest)
    live = [0.5, -1.0, 0.4, -1.0, 0.5] * 6  # PF ~0.5
    result = compute_tracking_error(
        backtest_csv=tmp_path / "alpha-v1" / "tv_trades.csv",
        live_returns_pct=live,
    )
    assert result.status == "ok"
    assert result.te is not None
    assert result.te < TE_AMBER_THRESHOLD  # < 0.60 → red bucket


def test_decay_series_has_11_points(tmp_path: Path) -> None:
    backtest = [1.0, -0.5, 1.5, -0.3, 2.0] * 8  # n=40
    _write_tv_trades(tmp_path / "alpha-v1", backtest)
    live = [0.9, -0.4, 1.4, -0.3, 1.8] * 8
    result = compute_tracking_error(
        backtest_csv=tmp_path / "alpha-v1" / "tv_trades.csv",
        live_returns_pct=live,
    )
    assert result.decay_series is not None
    assert len(result.decay_series) == 11


def test_decay_series_pads_to_11_for_small_input(tmp_path: Path) -> None:
    """_decay_series ALWAYS returns DECAY_POINTS items, even with n<11 input.
    Frontend assumes len(decay_series) == 11; padding preserves that contract."""
    from tradelab.live.tracking_error import _decay_series, DECAY_POINTS
    assert len(_decay_series([])) == DECAY_POINTS
    assert len(_decay_series([1.0, -0.5, 1.5])) == DECAY_POINTS
    assert len(_decay_series([1.0] * 10)) == DECAY_POINTS
    assert len(_decay_series([1.0] * 11)) == DECAY_POINTS
    assert len(_decay_series([1.0] * 30)) == DECAY_POINTS


def test_ks_low_p_for_divergent_distributions(tmp_path: Path) -> None:
    backtest = [1.0] * 30  # all wins of +1%
    _write_tv_trades(tmp_path / "alpha-v1", backtest)
    live = [-1.0] * 30  # all losses of -1%
    result = compute_tracking_error(
        backtest_csv=tmp_path / "alpha-v1" / "tv_trades.csv",
        live_returns_pct=live,
    )
    assert result.status == "ok"
    assert result.ks_p is not None
    assert result.ks_p < 0.01  # very different distributions
