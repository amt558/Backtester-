"""
Structured result classes.

Every engine (backtest, optimizer, walk-forward, robustness) returns one of these.
The reporting layer consumes them — no print statements in engine code.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field


class Trade(BaseModel):
    """One completed trade."""
    ticker: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    shares: int
    pnl: float
    pnl_pct: float
    bars_held: int
    exit_reason: str
    mae_pct: float = 0.0
    mfe_pct: float = 0.0


class BacktestMetrics(BaseModel):
    """Summary metrics from a backtest run."""
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    net_pnl: float = 0.0
    pct_return: float = 0.0
    annual_return: float = 0.0
    final_equity: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    avg_bars_held: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0


class BacktestResult(BaseModel):
    """A single backtest's complete output."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    strategy: str
    symbol: str = "PORTFOLIO"
    timeframe: str = "1D"
    start_date: str
    end_date: str
    params: dict = Field(default_factory=dict)
    metrics: BacktestMetrics = Field(default_factory=BacktestMetrics)
    trades: list[Trade] = Field(default_factory=list)
    # equity_curve held as list of {"date": str, "equity": float}
    equity_curve: list[dict] = Field(default_factory=list)
    generated_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def daily_returns(self) -> Optional[pd.Series]:
        """
        Return the equity curve as a Series of daily percentage returns,
        suitable for feeding to QuantStats.
        """
        if not self.equity_curve:
            return None
        df = pd.DataFrame(self.equity_curve)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        returns = df["equity"].pct_change().dropna()
        returns.name = self.strategy
        return returns


class OptunaTrial(BaseModel):
    """One trial in an Optuna study."""
    number: int
    fitness: float
    params: dict
    metrics: dict = Field(default_factory=dict)  # user_attrs like pf, trades, win_rate


class OptunaResult(BaseModel):
    """Output of a parameter optimization run."""
    strategy: str
    n_trials: int
    best_trial: OptunaTrial
    all_trials: list[OptunaTrial] = Field(default_factory=list)
    param_importance: dict[str, float] = Field(default_factory=dict)
    best_backtest: Optional[BacktestResult] = None
    generated_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


class WalkForwardWindow(BaseModel):
    """One train/test split in a walk-forward run."""
    index: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    train_metrics: Optional[BacktestMetrics] = None
    test_metrics: Optional[BacktestMetrics] = None
    best_params: dict = Field(default_factory=dict)


class WalkForwardResult(BaseModel):
    """Aggregate walk-forward output."""
    strategy: str
    n_windows: int
    windows: list[WalkForwardWindow] = Field(default_factory=list)
    aggregate_oos: BacktestMetrics = Field(default_factory=BacktestMetrics)
    wfe_ratio: float = 0.0   # OOS_PF / IS_PF (robustness key metric)
    oos_trades: list[Trade] = Field(default_factory=list)
    oos_equity_curve: list[dict] = Field(default_factory=list)
    generated_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


class RobustnessResult(BaseModel):
    """Output of the 5-test robustness suite."""
    strategy: str
    baseline_metrics: BacktestMetrics
    monte_carlo_shuffle: dict = Field(default_factory=dict)     # mean/std of DD across shuffles
    noise_injection: dict = Field(default_factory=dict)          # PF before/after noise
    parameter_sensitivity: dict = Field(default_factory=dict)    # param -> fitness delta
    entry_exit_delay: dict = Field(default_factory=dict)         # delay -> metrics
    cross_symbol: dict = Field(default_factory=dict)             # in-sample vs out-of-sample universe
    verdict: str = "UNEVALUATED"
    generated_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
