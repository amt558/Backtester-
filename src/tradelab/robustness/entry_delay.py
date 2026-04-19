"""
Entry delay test — shift buy_signal by 0, +1, +2 bars and see how much edge
disappears. Strategies that need exact-bar timing are leak-prone or fragile
to live-execution slippage; a one-bar shift should not devastate a real edge.

Implementation: re-run the strategy to produce signals, then shift the
buy_signal column by N bars inside each DataFrame before handing to the
backtest engine. All other columns unchanged.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from ..engines.backtest import run_backtest
from ..results import BacktestMetrics


class EntryDelayPoint(BaseModel):
    delay: int
    metrics: BacktestMetrics


class EntryDelayResult(BaseModel):
    """Collapse of edge as entry is delayed."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    delays: list[int]
    points: list[EntryDelayPoint]

    def pf_at(self, delay: int) -> float:
        for p in self.points:
            if p.delay == delay:
                return p.metrics.profit_factor
        return 0.0

    @property
    def pf_drop_one_bar(self) -> float:
        """Fraction PF drops from delay=0 to delay=+1. Positive = PF decreased."""
        base = self.pf_at(0)
        if base <= 0:
            return 0.0
        return (base - self.pf_at(1)) / base


def _shifted_universe(data: dict, delay: int, strategy) -> dict:
    """Run strategy on data, then shift buy_signal by `delay` bars in each frame."""
    signaled = strategy.generate_signals(
        data,
        spy_close=data.get("SPY", {}).set_index("Date")["Close"] if "SPY" in data else None,
    )
    out = {}
    for sym, df in signaled.items():
        df = df.copy()
        if delay > 0:
            df["buy_signal"] = df["buy_signal"].shift(delay, fill_value=False)
        # delay=0 is unchanged
        out[sym] = df
    return out


def run_entry_delay(
    strategy,
    ticker_data,
    delays: list[int] = None,
    spy_close=None,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> EntryDelayResult:
    """
    Run the backtest at each delay. Default [0, 1, 2] (no negative shifts —
    anti-drift rule from the master plan).
    """
    if delays is None:
        delays = [0, 1, 2]

    # We need a pre-signaled dict for shifting, then we hand-roll a backtest
    # by temporarily wrapping the strategy to return our shifted data.
    # Simpler: subclass the strategy on the fly, or just bypass the
    # generate_signals layer.
    #
    # Trick: call generate_signals once, shift externally, then feed the
    # already-signaled frames to run_backtest BUT via a stub strategy whose
    # generate_signals is a passthrough.
    class _Passthrough:
        name = strategy.name + "_shifted"
        timeframe = strategy.timeframe
        requires_benchmark = False

        def __init__(self, params):
            self.params = dict(params)

        def generate_signals(self, data, spy_close=None):
            return data  # already signaled and shifted

    points: list[EntryDelayPoint] = []
    for d in delays:
        shifted = _shifted_universe(ticker_data, d, strategy)
        stub = _Passthrough(strategy.params)
        bt = run_backtest(stub, shifted, start=start, end=end, spy_close=spy_close)
        points.append(EntryDelayPoint(delay=int(d), metrics=bt.metrics))

    return EntryDelayResult(delays=list(delays), points=points)
