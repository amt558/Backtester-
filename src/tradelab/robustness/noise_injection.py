"""
Noise injection test — ATR-scaled Gaussian perturbation of OHLCV bars.

Why: if a 5-basis-point noise on every bar kills the edge, the edge was
an artifact of specific price paths and won't survive real-world slippage
or data-vendor rounding differences. A robust edge survives small,
realistic perturbations.

Bar-structure preservation:
  The noise is applied to a single "core price" per bar (the midpoint of
  High and Low); then High/Low/Close/Open are re-derived by adding the
  noise to each while preserving the OHLC inequalities:
     Low ≤ min(Open, Close)  ≤  max(Open, Close) ≤ High

Indicators are re-computed on the noisy universe (via enrich_universe)
so the strategy sees consistent data.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from ..engines.backtest import run_backtest
from ..marketdata.enrich import enrich_universe
from ..results import BacktestMetrics


class NoiseInjectionPoint(BaseModel):
    seed: int
    metrics: BacktestMetrics


class NoiseInjectionResult(BaseModel):
    """Distribution of backtest metrics over N noisy realisations."""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    n_seeds: int
    noise_sigma_bp: float
    baseline_pf: float
    baseline_sharpe: float
    baseline_return_pct: float
    points: list[NoiseInjectionPoint] = Field(default_factory=list)

    @property
    def pf_mean(self) -> float:
        vals = [p.metrics.profit_factor for p in self.points]
        return float(np.mean(vals)) if vals else 0.0

    @property
    def pf_std(self) -> float:
        vals = [p.metrics.profit_factor for p in self.points]
        return float(np.std(vals)) if vals else 0.0

    @property
    def pf_p5(self) -> float:
        vals = [p.metrics.profit_factor for p in self.points]
        return float(np.percentile(vals, 5)) if vals else 0.0

    @property
    def pf_p95(self) -> float:
        vals = [p.metrics.profit_factor for p in self.points]
        return float(np.percentile(vals, 95)) if vals else 0.0

    @property
    def pf_drop_p5_from_baseline(self) -> float:
        """Fraction baseline PF drops to the worst 5th-percentile realisation."""
        if self.baseline_pf <= 0:
            return 0.0
        return (self.baseline_pf - self.pf_p5) / self.baseline_pf


def _add_noise_to_bar(df: pd.DataFrame, sigma_bp: float, rng: np.random.Generator) -> pd.DataFrame:
    """
    Add Gaussian noise scaled by sigma_bp (basis points of close price) to each
    O/H/L/C independently, then repair OHLC inequalities.
    """
    out = df.copy()
    n = len(out)
    if n == 0 or "Close" not in out.columns:
        return out
    close = out["Close"].values
    # Per-bar scale: sigma in dollars = sigma_bp * 1e-4 * close
    scale = sigma_bp * 1e-4 * close
    # Draw 4 independent noise values per bar (Open/High/Low/Close)
    noise = rng.normal(0.0, 1.0, size=(n, 4))
    o = out["Open"].values + noise[:, 0] * scale
    h = out["High"].values + noise[:, 1] * scale
    l = out["Low"].values + noise[:, 2] * scale
    c = out["Close"].values + noise[:, 3] * scale
    # Repair: H = max(O, H, C), L = min(O, L, C)
    hi = np.maximum.reduce([o, h, c])
    lo = np.minimum.reduce([o, l, c])
    out["Open"] = o
    out["High"] = hi
    out["Low"] = lo
    out["Close"] = c
    return out


def _noisy_universe(data: dict[str, pd.DataFrame], sigma_bp: float, seed: int) -> dict[str, pd.DataFrame]:
    """Produce a noisy copy of the raw OHLCV universe, keeping 'Date' and 'Volume' unchanged."""
    rng = np.random.default_rng(seed)
    out: dict[str, pd.DataFrame] = {}
    for sym, df in data.items():
        # Retain original Date and Volume; perturb only OHLC
        noisy = _add_noise_to_bar(df[["Date", "Open", "High", "Low", "Close", "Volume"]],
                                   sigma_bp, rng)
        out[sym] = noisy
    return out


def run_noise_injection(
    strategy,
    ticker_data,
    baseline_metrics: BacktestMetrics,
    n_seeds: int = 50,
    noise_sigma_bp: float = 5.0,
    seed_base: int = 200,
    spy_close=None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    benchmark: str = "SPY",
) -> NoiseInjectionResult:
    """
    Rebuild the universe with ATR-scaled OHLC noise N times, re-enrich
    indicators, re-run backtest. Return metric distribution.

    Args:
        ticker_data: the ENRICHED universe (will be stripped to raw OHLCV
            before perturbing, then re-enriched per seed)
        baseline_metrics: the un-noised backtest metrics for comparison
        n_seeds: default 50 per master plan
        noise_sigma_bp: noise scale in basis points of close (default 5 bp)
    """
    # Strip down to raw OHLCV columns (indicators will be recomputed)
    raw = {s: df[["Date", "Open", "High", "Low", "Close", "Volume"]].copy()
           for s, df in ticker_data.items()}

    points: list[NoiseInjectionPoint] = []
    for i in range(n_seeds):
        seed = seed_base + i
        noisy_raw = _noisy_universe(raw, noise_sigma_bp, seed)
        enriched = enrich_universe(noisy_raw, benchmark=benchmark)
        spy_close_local = enriched[benchmark].set_index("Date")["Close"] if benchmark in enriched else None
        bt = run_backtest(
            strategy, enriched,
            start=start, end=end,
            spy_close=spy_close_local if spy_close is None else spy_close,
        )
        points.append(NoiseInjectionPoint(seed=seed, metrics=bt.metrics))

    return NoiseInjectionResult(
        n_seeds=n_seeds,
        noise_sigma_bp=noise_sigma_bp,
        baseline_pf=baseline_metrics.profit_factor,
        baseline_sharpe=baseline_metrics.sharpe_ratio,
        baseline_return_pct=baseline_metrics.pct_return,
        points=points,
    )
