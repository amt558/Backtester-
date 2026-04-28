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

    Strategy attribution: fills since Slice -0.5 carry client_order_id
    starting with f"{card_id}-". Pairs each entry fill with the next
    matching exit fill (same symbol) chronologically using a qty-aware
    FIFO deque per symbol — supports partial fills (e.g. entry qty 10
    paired against exit qty 4 splits the entry, leaving 6 still open).

    Long round-trip:  entry=buy,  exit=sell  → (exit - entry) / entry * 100
    Short round-trip: entry=sell, exit=buy   → (entry - exit) / entry * 100

    Returns list of percent returns, oldest first. Empty if no fills or no
    completed round-trips (e.g. open positions are correctly excluded).

    Falls back to [] on any Alpaca error so the endpoint reports
    "insufficient" rather than 500-ing.
    """
    from collections import deque

    from .alpaca_client import list_closed_orders

    try:
        all_closed = list_closed_orders(days=90)
    except Exception:
        return []

    # Filter to this card's orders that actually filled (price + qty present).
    # Prefer filled_qty when present (handles partial fills); fall back to qty
    # for backward compatibility with order dicts produced before that field
    # was added.
    prefix = f"{card_id}-"

    def _fill_qty(o: dict) -> float:
        fq = o.get("filled_qty")
        if fq is not None and float(fq) > 0:
            return float(fq)
        q = o.get("qty")
        return float(q) if q is not None else 0.0

    card_orders = [
        o for o in all_closed
        if (o.get("client_order_id") or "").startswith(prefix)
        and o.get("filled_avg_price") is not None
        and _fill_qty(o) > 0
    ]

    # Defensive sort by filled_at ascending (list_closed_orders requests ASC
    # already, but guards against any edge cases in the API response).
    card_orders.sort(key=lambda o: o.get("filled_at") or "")

    # Per-symbol qty-aware FIFO deque of open entry "lots":
    #     deque[(remaining_qty, entry_price, side)]
    # where side is the entry's side ("buy" for long, "sell" for short).
    # An incoming order on the *same* side appends a new lot; an opposite-
    # side order peels qty off the front lots until either its qty is
    # exhausted or the deque is empty (excess turns into a new opposite-
    # side lot, i.e. a flipped position).
    open_lots: dict[str, deque] = {}
    returns_pct: list[float] = []

    for o in card_orders:
        sym = o["symbol"]
        side = (o.get("side") or "").lower()
        price = float(o["filled_avg_price"])
        qty = _fill_qty(o)
        if price <= 0 or qty <= 0:
            continue

        lots = open_lots.setdefault(sym, deque())

        if not lots:
            lots.append([qty, price, side])
            continue

        front_side = lots[0][2]
        if side == front_side:
            # Same direction: stack as another open lot.
            lots.append([qty, price, side])
            continue

        # Opposite direction: close oldest lots FIFO until qty exhausted.
        remaining = qty
        while remaining > 0 and lots:
            lot = lots[0]
            lot_qty = lot[0]
            entry_price = lot[1]
            entry_side = lot[2]
            take = min(lot_qty, remaining)
            if entry_side == "buy":
                pct = (price - entry_price) / entry_price * 100.0
            else:
                pct = (entry_price - price) / entry_price * 100.0
            returns_pct.append(round(pct, 4))
            lot[0] -= take
            remaining -= take
            if lot[0] <= 0:
                lots.popleft()
        if remaining > 0:
            # Position fully closed and flipped; opposite-side excess opens
            # a new lot in the new direction.
            lots.append([remaining, price, side])

    return returns_pct
