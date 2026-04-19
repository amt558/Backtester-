"""
Deflated Sharpe Ratio (Bailey & López de Prado, 2014).

Given an observed Sharpe selected from N competing alternatives (e.g., the
best Optuna trial out of N trials), the DSR is the probability — in [0, 1] —
that the observed Sharpe reflects a genuine edge rather than luck from
multiple testing.

tradelab uses DSR as a calibrated gate on reported strategy Sharpe ratios.
Because we err toward flagging fragility (anti-drift rule: asymmetric error
costs), a DSR below 0.50 is treated as FRAGILE; 0.50–0.95 is INCONCLUSIVE;
above 0.95 is ROBUST.

Reference: Bailey, D.H., López de Prado, M. (2014).
    "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest
    Overfitting and Non-Normality." Journal of Portfolio Management 40(5).
"""
from __future__ import annotations

import math

import numpy as np
from scipy.stats import kurtosis, norm, skew


EULER_MASCHERONI = 0.5772156649015329


def _expected_max_null_sharpe(n_trials: int, T: int) -> float:
    """
    Expected maximum Sharpe under the null (SR=0) across n_trials independent
    draws from the SR sampling distribution with T observations each.

    Under H0 the SR has approximate variance 1/T (the non-normality correction
    vanishes at SR=0), so standard-deviation sd_null = sqrt(1/T). Using the
    extreme-value approximation from Bailey & López de Prado (2014):

        E[max_n SR] = sd_null * (
            (1 - γ_e) · Φ⁻¹(1 - 1/n)
          + γ_e        · Φ⁻¹(1 - 1/(n · e))
        )

    where γ_e is the Euler–Mascheroni constant.
    """
    if n_trials < 1:
        raise ValueError("n_trials must be ≥ 1")
    sd_null = math.sqrt(1.0 / T)
    if n_trials == 1:
        # A single trial has no selection bias — return 0.
        return 0.0
    a = (1.0 - EULER_MASCHERONI) * float(norm.ppf(1.0 - 1.0 / n_trials))
    b = EULER_MASCHERONI * float(norm.ppf(1.0 - 1.0 / (n_trials * math.e)))
    return sd_null * (a + b)


def deflated_sharpe_ratio(
    returns,
    n_trials: int = 1,
) -> float:
    """
    Compute the DSR for a return series.

    Args:
        returns: period-level returns (array-like). Do not pre-annualize.
            The DSR formula is invariant to affine scaling, so using raw
            period returns is correct.
        n_trials: number of competing trials from which this series was
            selected (e.g. 100 Optuna trials → n_trials=100). Pass 1 for
            the non-selected case (reduces to Probabilistic Sharpe Ratio).

    Returns:
        Probability in [0, 1] that the observed Sharpe > expected max null
        Sharpe. Returns NaN if the return series has zero volatility or
        fewer than 2 observations.
    """
    r = np.asarray(returns, dtype=float)
    T = r.size
    if T < 2:
        return float("nan")

    std = r.std(ddof=1)
    if std == 0.0 or not np.isfinite(std):
        return float("nan")

    sr_obs = r.mean() / std
    g3 = float(skew(r, bias=False))
    g4 = float(kurtosis(r, fisher=False, bias=False))  # non-excess kurtosis

    expected_max = _expected_max_null_sharpe(n_trials, T)

    # Denominator: sqrt(1 - γ3·SR + ((γ4-1)/4)·SR²), the SR standard error
    # adjustment for non-normality. Guard against the (rare) case of a
    # negative radicand from extreme kurtosis/skew combinations.
    radicand = 1.0 - g3 * sr_obs + ((g4 - 1.0) / 4.0) * sr_obs ** 2
    if radicand <= 0.0 or not math.isfinite(radicand):
        return float("nan")
    denom = math.sqrt(radicand)

    z = (sr_obs - expected_max) * math.sqrt(T - 1) / denom
    return float(norm.cdf(z))


def classify_dsr(dsr: float) -> str:
    """Map a DSR probability to tradelab's edge-classification bands."""
    if math.isnan(dsr):
        return "undefined"
    if dsr < 0.50:
        return "fragile"
    if dsr < 0.95:
        return "inconclusive"
    return "robust"
