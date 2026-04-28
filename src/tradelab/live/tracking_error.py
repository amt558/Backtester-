"""Distributional tracking-error engine for LITE-on-Flow-A.

Compares live trade-return distribution to backtest trade-return distribution
(both as lists of profit_pct values). The backtest baseline is read from the
frozen pine_archive/<card_id>/tv_trades.csv at Accept time.

Returns:
- te: live PF / backtest PF over rolling last-N-trades window
- decay_series: 11-point smoothed rolling PF over live trades
- ks_p: two-sample K-S test p-value
- status: "ok" | "insufficient" (n_live < MIN_N_TRADES)
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel
from scipy import stats as scipy_stats

from ..io.returns import read_trade_profit_pcts

MIN_N_TRADES = 30
ROLLING_WINDOW = 30
DECAY_POINTS = 11
TE_GREEN_THRESHOLD = 0.80
TE_AMBER_THRESHOLD = 0.60
KS_AMBER = 0.05
KS_RED = 0.01


class TrackingErrorResult(BaseModel):
    te: Optional[float] = None
    decay_series: Optional[list[float]] = None
    ks_p: Optional[float] = None
    n_live_trades: int = 0
    n_backtest_trades: int = 0
    status: str = "insufficient"  # "ok" | "insufficient"


def _profit_factor(returns_pct: list[float]) -> Optional[float]:
    """PF = sum(wins) / abs(sum(losses)). Returns None if no losses."""
    wins = sum(r for r in returns_pct if r > 0)
    losses = sum(r for r in returns_pct if r < 0)
    if losses >= 0:
        return None
    return wins / abs(losses)


def _decay_series(returns_pct: list[float], n_points: int = DECAY_POINTS) -> list[float]:
    """11 evenly-spaced rolling-PF samples. Pads with 1.0 when fewer trades than n_points."""
    if not returns_pct:
        return [1.0] * n_points
    n = len(returns_pct)
    if n < n_points:
        # Compute what we can, pad the front with 1.0 (neutral PF)
        partial = [
            _profit_factor(returns_pct[: i + 1]) or 1.0
            for i in range(n)
        ]
        return [1.0] * (n_points - n) + partial
    anchors = [int(i * (n - 1) / (n_points - 1)) for i in range(n_points)]
    series: list[float] = []
    for a in anchors:
        start = max(0, a + 1 - ROLLING_WINDOW)
        pf = _profit_factor(returns_pct[start : a + 1])
        series.append(pf if pf is not None else 1.0)
    return series


def compute_tracking_error(
    backtest_csv: Path,
    live_returns_pct: list[float],
) -> TrackingErrorResult:
    backtest_returns = read_trade_profit_pcts(backtest_csv)
    n_backtest = len(backtest_returns)
    n_live = len(live_returns_pct)
    if n_live < MIN_N_TRADES:
        return TrackingErrorResult(
            status="insufficient",
            n_live_trades=n_live,
            n_backtest_trades=n_backtest,
        )
    live_window = live_returns_pct[-ROLLING_WINDOW:]
    live_pf = _profit_factor(live_window)
    backtest_pf = _profit_factor(backtest_returns)
    te: Optional[float] = None
    if live_pf is not None and backtest_pf is not None and backtest_pf > 0:
        te = round(live_pf / backtest_pf, 3)
    ks_p: Optional[float] = None
    if backtest_returns:
        try:
            ks_result = scipy_stats.ks_2samp(live_returns_pct, backtest_returns)
            ks_p = round(float(ks_result.pvalue), 4)
        except Exception:
            ks_p = None
    decay = _decay_series(live_returns_pct)
    return TrackingErrorResult(
        te=te,
        decay_series=decay,
        ks_p=ks_p,
        n_live_trades=n_live,
        n_backtest_trades=n_backtest,
        status="ok",
    )


def load_live_returns_for_card(card_id: str, *, alpaca_client=None) -> list[float]:
    """Pull all paired-fill returns_pct from Alpaca filtered to this card.

    Uses receiver.py client_order_id tagging: orders placed by this bot have
    client_order_id = f"{card_id}-{timestamp_ms}".  Returns list of percent
    returns, oldest first.

    Returns [] if no fills found or attribution unavailable.

    NOTE: The actual Alpaca client (alpaca_client.py) only exposes
    list_open_orders() — there is no closed/filled orders wrapper yet.
    Wiring real closed-fills retrieval requires adding a list_filled_orders()
    function to alpaca_client.py and pairing entry/exit orders by symbol+card.
    This is deferred until there are ≥30 live fills to validate against.

    TODO: wire real Alpaca fills (Slice -0.5 tagging → real implementation)
    """
    return []
