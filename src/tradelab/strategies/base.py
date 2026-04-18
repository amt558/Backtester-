"""
Base class for trading strategies.

Strategies describe *logic*, not *execution*. They:
  1. Declare parameters and default values
  2. Generate entry and exit signals from OHLCV data
  3. Provide metadata (name, timeframe, requires benchmark, etc.)

The engines (backtest, optimizer, walk-forward) consume these.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

import pandas as pd


class Strategy(ABC):
    """Base class for all registered strategies."""

    #: Friendly name used in CLI and registry
    name: str = "unnamed_strategy"

    #: Target timeframe (e.g. '1D', '30min', '1H'). Resampling happens at data load.
    timeframe: str = "1D"

    #: If True, data layer will load SPY and pass spy_close through generate_signals
    requires_benchmark: bool = False

    #: Default parameters. Subclasses override with their actual defaults.
    default_params: dict[str, Any] = {}

    #: Parameter search ranges for Optuna. {name: (low, high)}. Subclasses override.
    tunable_params: dict[str, tuple[float, float]] = {}

    def __init__(self, name: Optional[str] = None, params: Optional[dict] = None):
        if name is not None:
            self.name = name
        self.params = {**self.default_params}
        if params:
            self.params.update(params)

    @abstractmethod
    def generate_signals(
        self,
        data: dict[str, pd.DataFrame],
        spy_close: Optional[pd.Series] = None,
    ) -> dict[str, pd.DataFrame]:
        """
        Compute signals per symbol.

        Args:
            data: dict mapping symbol -> OHLCV DataFrame (at self.timeframe).
                  Columns include: Date, Open, High, Low, Close, Volume.
                  Indicators (SMA, RSI, ATR, etc.) are NOT pre-computed —
                  each strategy is responsible for computing its own.
            spy_close: SPY close Series, indexed by date. Provided when
                       requires_benchmark is True.

        Returns:
            dict mapping symbol -> DataFrame with all original columns plus
            at minimum a 'buy_signal' column (bool) that the backtest engine
            will consume. Strategies may add other columns (e.g. 'score',
            'stop_price', 'trail_atr') that the engine can use for ranking
            and exit logic.
        """
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<Strategy name={self.name!r} timeframe={self.timeframe}>"
