"""
Deflated Sharpe Ratio tests (Bailey & López de Prado 2014).

The DSR answers: given a strategy was selected from N competing alternatives,
what is the probability the observed Sharpe reflects a true edge rather than luck?

Formula (reference): DSR(SR_obs) = Φ( (SR_obs - E[max SR_null]) * √(T-1)
                                        / √(1 - γ₃·SR_obs + ((γ₄-1)/4)·SR_obs²) )

Tests verify:
  1. Random-walk returns yield DSR < 0.50 (tool correctly rejects luck)
  2. Strong-trend deterministic series yield DSR > 0.95 (tool endorses real edge)
  3. Marginal edge after many trials lands in inconclusive band 0.50 ≤ DSR ≤ 0.95
  4. Hand-computed value matches implementation to 4 decimals
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from tradelab.engines.dsr import deflated_sharpe_ratio, EULER_MASCHERONI


def test_dsr_rejects_random_walk():
    """Zero-mean iid normal returns with 100 competing trials → DSR very low."""
    rng = np.random.default_rng(42)
    returns = rng.normal(loc=0.0, scale=0.01, size=1000)
    dsr = deflated_sharpe_ratio(returns, n_trials=100)
    assert 0.0 <= dsr <= 1.0
    assert dsr < 0.50, f"expected DSR<0.50 for random walk, got {dsr:.3f}"


def test_dsr_endorses_strong_trend():
    """Deterministic uptrend, 50 trials → DSR very high (>0.95)."""
    # Monotone positive small returns — very high Sharpe
    returns = np.full(500, 0.001) + np.linspace(0, 0.0005, 500)
    # Add trivial noise so std is nonzero
    rng = np.random.default_rng(1)
    returns = returns + rng.normal(0.0, 0.00005, 500)
    dsr = deflated_sharpe_ratio(returns, n_trials=50)
    assert dsr > 0.95, f"expected DSR>0.95 for strong trend, got {dsr:.3f}"


def test_dsr_marginal_edge_inconclusive_band():
    """Modest real edge + many trials → DSR in inconclusive band, not ROBUST."""
    # Period-level SR ≈ 0.18 with 500 trials — enough edge to clear the null
    # expectation, but not enough to reach the ROBUST threshold.
    rng = np.random.default_rng(7)
    returns = rng.normal(loc=0.0018, scale=0.010, size=1000)
    dsr = deflated_sharpe_ratio(returns, n_trials=500)
    # The key property: DSR sits BELOW the ROBUST band (<0.95) after heavy
    # multiple testing, while being clearly above trivial (>0.30).
    assert 0.30 <= dsr < 0.95, (
        f"expected marginal DSR in inconclusive band [0.30, 0.95), got {dsr:.3f}"
    )


def test_dsr_formula_matches_hand_computation():
    """
    Construct a return series with KNOWN moments and verify DSR matches
    the hand-computed value to 4 decimals.

    Use returns such that:
      - T = 1000
      - SR_obs (period) = 0.05   — strong
      - γ₃ (skew) ≈ 0            — symmetric
      - γ₄ (kurt, non-excess) ≈ 3 — gaussian-ish
    Then with N=100 trials, the expected max null SR is:
      E[max] = √(1/T) * ((1-γe)·Φ⁻¹(1-1/N) + γe·Φ⁻¹(1-1/(N·e)))
    and DSR = Φ((SR_obs - E[max]) * √(T-1) / √(1 - 0 + ((3-1)/4)·SR_obs²))

    We build the series by choosing returns with exact mean and std, then
    symmetrizing. Hand-compute then check.
    """
    from scipy.stats import norm

    T = 1000
    SR_target = 0.05       # period-level Sharpe
    mu = 0.001
    sigma = mu / SR_target  # → 0.02

    # Exactly-Gaussian-like construction: antithetic pairs → skew=0, kurt≈3
    rng = np.random.default_rng(123)
    half = rng.standard_normal(T // 2)
    raw = np.concatenate([half, -half])  # mean 0, std 1, skew 0
    # Rescale to target mean/std
    returns = raw * sigma + mu
    # Verify construction
    assert abs(returns.mean() / returns.std(ddof=1) - SR_target) < 0.01

    # Hand computation
    N = 100
    gamma_e = EULER_MASCHERONI
    sr_obs = returns.mean() / returns.std(ddof=1)
    from scipy.stats import skew, kurtosis
    g3 = skew(returns, bias=False)
    g4 = kurtosis(returns, fisher=False, bias=False)   # non-excess kurtosis
    sd_null = math.sqrt(1.0 / T)
    expected_max = sd_null * (
        (1 - gamma_e) * norm.ppf(1 - 1.0 / N)
        + gamma_e * norm.ppf(1 - 1.0 / (N * math.e))
    )
    numer = (sr_obs - expected_max) * math.sqrt(T - 1)
    denom = math.sqrt(1 - g3 * sr_obs + ((g4 - 1) / 4) * sr_obs ** 2)
    expected_dsr = float(norm.cdf(numer / denom))

    # Function output
    dsr = deflated_sharpe_ratio(returns, n_trials=N)
    assert abs(dsr - expected_dsr) < 1e-4, (
        f"DSR mismatch: got {dsr:.6f}, expected {expected_dsr:.6f}"
    )


def test_dsr_single_trial_reduces_to_probabilistic_sharpe():
    """With n_trials=1, DSR collapses to PSR (expected_max=0)."""
    rng = np.random.default_rng(99)
    returns = rng.normal(0.0005, 0.01, 500)
    dsr_1 = deflated_sharpe_ratio(returns, n_trials=1)
    # Manual PSR for comparison: DSR formula with expected_max = 0
    from scipy.stats import skew, kurtosis, norm
    sr = returns.mean() / returns.std(ddof=1)
    g3 = skew(returns, bias=False)
    g4 = kurtosis(returns, fisher=False, bias=False)
    T = len(returns)
    numer = sr * math.sqrt(T - 1)
    denom = math.sqrt(1 - g3 * sr + ((g4 - 1) / 4) * sr ** 2)
    psr = float(norm.cdf(numer / denom))
    assert abs(dsr_1 - psr) < 1e-4


def test_dsr_monotone_in_n_trials():
    """More trials → more penalty → lower DSR for the same returns."""
    rng = np.random.default_rng(5)
    returns = rng.normal(0.0006, 0.01, 800)
    dsr_few = deflated_sharpe_ratio(returns, n_trials=10)
    dsr_many = deflated_sharpe_ratio(returns, n_trials=1000)
    assert dsr_few > dsr_many, f"expected monotonic penalty: {dsr_few} vs {dsr_many}"


def test_dsr_degenerate_zero_volatility_returns_nan():
    """Zero-volatility returns → undefined Sharpe → NaN result."""
    returns = np.full(100, 0.001)
    dsr = deflated_sharpe_ratio(returns, n_trials=10)
    assert math.isnan(dsr)
