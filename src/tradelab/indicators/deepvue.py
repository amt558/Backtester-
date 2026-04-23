"""DeepVue indicator library — replicated from deepvue_mcp/indicators.py
into tradelab as the canonical implementation.

All functions accept a DataFrame with OHLCV columns. The helper ``_lc`` lets
them work with either lowercase ('open','high','low','close','volume') or
tradelab's capitalized convention ('Open','High','Low','Close','Volume').
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


_OHLCV = {"open", "high", "low", "close", "volume"}


def _lc(df: pd.DataFrame) -> pd.DataFrame:
    """Return a DataFrame with OHLCV columns lowercased; leave others alone."""
    rename = {c: c.lower() for c in df.columns if c.lower() in _OHLCV and c not in _OHLCV}
    return df.rename(columns=rename) if rename else df


# ----- VOLATILITY --------------------------------------------------------

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range."""
    df = _lc(df)
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low, (high - prev_close).abs(), (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def atr_pct(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR as percentage of close."""
    df = _lc(df)
    return (atr(df, period) / df["close"]) * 100


def adr_pct(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Average Daily Range as percent of close."""
    df = _lc(df)
    daily_range = (df["high"] - df["low"]) / df["close"] * 100
    return daily_range.rolling(period).mean()


def sigma_spike(df: pd.DataFrame, lookback: int = 100) -> pd.Series:
    """Standardized daily price change. |v|>2 is abnormal."""
    df = _lc(df)
    change = df["close"] - df["close"].shift(1)
    rolling_std = change.rolling(lookback).std()
    return change / rolling_std


def relative_measured_volatility(
    df: pd.DataFrame, period: int = 5, baseline: int = 50
) -> pd.Series:
    """Realized vol over N days vs baseline window. <0.7 coiled, >1.3 extended."""
    df = _lc(df)
    log_returns = np.log(df["close"] / df["close"].shift(1))
    current_vol = log_returns.rolling(period).std()
    baseline_vol = log_returns.rolling(baseline).std()
    return current_vol / baseline_vol


# ----- MOMENTUM / TREND --------------------------------------------------

def relative_strength(
    df: pd.DataFrame, benchmark: pd.DataFrame, period: int = 21
) -> pd.Series:
    """Mansfield RS: stock %chg - benchmark %chg, in pct-points."""
    df = _lc(df); benchmark = _lc(benchmark)
    stock_chg = df["close"].pct_change(period)
    bench_chg = benchmark["close"].pct_change(period)
    bench_chg = bench_chg.reindex(stock_chg.index, method="ffill")
    return (stock_chg - bench_chg) * 100


def up_down_ratio(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Count up-days / down-days rolling."""
    df = _lc(df)
    daily_change = df["close"] - df["close"].shift(1)
    up_days = (daily_change > 0).rolling(period).sum()
    down_days = (daily_change < 0).rolling(period).sum()
    return up_days / down_days.replace(0, 1)


def weinstein_stage(df: pd.DataFrame, sma_period: int = 150) -> pd.Series:
    """Stan Weinstein stage 1/2/3/4 from price vs SMA slope."""
    df = _lc(df)
    sma = df["close"].rolling(sma_period).mean()
    sma_slope = sma - sma.shift(10)
    price_above = df["close"] > sma

    stage = pd.Series(0, index=df.index, dtype=int)
    stage[(price_above) & (sma_slope > 0)] = 2
    stage[(~price_above) & (sma_slope < 0)] = 4
    stage[(sma_slope.abs() < sma_slope.rolling(50).std() * 0.5) & (~price_above)] = 1
    stage[(sma_slope.abs() < sma_slope.rolling(50).std() * 0.5) & (price_above)] = 3
    return stage


def price_vs_ema(df: pd.DataFrame, period: int = 21) -> pd.Series:
    """(close - EMA) / EMA * 100."""
    df = _lc(df)
    ema = df["close"].ewm(span=period, adjust=False).mean()
    return ((df["close"] - ema) / ema) * 100


def sma_alignment(df: pd.DataFrame) -> pd.Series:
    """10 SMA > 21 SMA > 50 SMA."""
    df = _lc(df)
    sma10 = df["close"].rolling(10).mean()
    sma21 = df["close"].rolling(21).mean()
    sma50 = df["close"].rolling(50).mean()
    return (sma10 > sma21) & (sma21 > sma50)


def dcr(df: pd.DataFrame, period: int = 10) -> pd.Series:
    """Daily change rate, EMA-smoothed."""
    df = _lc(df)
    daily_pct = df["close"].pct_change() * 100
    return daily_pct.ewm(span=period, adjust=False).mean()


def wcr(df: pd.DataFrame, period: int = 4) -> pd.Series:
    """Weekly change rate, EMA-smoothed."""
    df = _lc(df)
    weekly_pct = df["close"].pct_change(5) * 100
    return weekly_pct.ewm(span=period, adjust=False).mean()


# ----- VOLUME ------------------------------------------------------------

def relative_volume(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Current volume / N-day average."""
    df = _lc(df)
    avg_vol = df["volume"].rolling(period).mean()
    return df["volume"] / avg_vol


def volume_dry_up(
    df: pd.DataFrame, period: int = 20, threshold: float = 0.5
) -> pd.Series:
    """True when relative volume < threshold."""
    return relative_volume(df, period) < threshold


# ----- PATTERNS ----------------------------------------------------------

def pocket_pivot(df: pd.DataFrame, lookback: int = 10) -> pd.Series:
    """Up-day vol > max down-day vol of prior N bars."""
    df = _lc(df)
    is_up = df["close"] > df["close"].shift(1)
    is_down = ~is_up
    down_vol = df["volume"].where(is_down, 0)
    max_down_vol = down_vol.rolling(lookback).max()
    return is_up & (df["volume"] > max_down_vol)


def open_equals_low(df: pd.DataFrame, tolerance: float = 0.001) -> pd.Series:
    df = _lc(df)
    return ((df["open"] - df["low"]).abs() / df["close"]) < tolerance


def open_equals_high(df: pd.DataFrame, tolerance: float = 0.001) -> pd.Series:
    df = _lc(df)
    return ((df["open"] - df["high"]).abs() / df["close"]) < tolerance


def buyable_gap_up(
    df: pd.DataFrame, gap_pct: float = 3.0, vol_multiple: float = 1.5
) -> pd.Series:
    df = _lc(df)
    prev_close = df["close"].shift(1)
    gap = ((df["open"] - prev_close) / prev_close) * 100
    rvol = relative_volume(df, 20)
    holds = df["close"] > df["open"]
    return (gap >= gap_pct) & (rvol >= vol_multiple) & holds


def vcp_score(df: pd.DataFrame, window: int = 60) -> pd.Series:
    """Volatility contraction pattern score 0-100. Higher = tighter."""
    atr_val = atr(df, 14)
    atr_start = atr_val.shift(window)
    contraction = ((atr_start - atr_val) / atr_start) * 100
    return contraction.clip(0, 100)


def rs_new_high_before_price(
    df: pd.DataFrame, benchmark: pd.DataFrame, lookback: int = 63
) -> pd.Series:
    """RS line at N-bar high while price is not."""
    df = _lc(df); benchmark = _lc(benchmark)
    rs_line = df["close"] / benchmark["close"].reindex(df.index, method="ffill")
    rs_at_high = rs_line >= rs_line.rolling(lookback).max()
    price_at_high = df["close"] >= df["close"].rolling(lookback).max()
    return rs_at_high & (~price_at_high)


def minervini_trend_template(df: pd.DataFrame) -> pd.Series:
    """Minervini's 7-condition template. Returns boolean Series.

    1) Close > SMA150
    2) Close > SMA200
    3) SMA150 > SMA200
    4) SMA200 trending up (21-day slope positive)
    5) Close > SMA50
    6) Close > 52w low * 1.25
    7) Close >= 52w high * 0.75
    (Condition 8 - RS rank > 70 - is not evaluated here; pair with an RS gate if needed)
    """
    df = _lc(df)
    sma50 = df["close"].rolling(50).mean()
    sma150 = df["close"].rolling(150).mean()
    sma200 = df["close"].rolling(200).mean()
    sma200_1mo_ago = sma200.shift(21)
    low_52w = df["low"].rolling(252).min()
    high_52w = df["high"].rolling(252).max()

    c1 = df["close"] > sma150
    c2 = df["close"] > sma200
    c3 = sma150 > sma200
    c4 = sma200 > sma200_1mo_ago
    c5 = df["close"] > sma50
    c6 = df["close"] > low_52w * 1.25
    c7 = df["close"] >= high_52w * 0.75
    return (c1 & c2 & c3 & c4 & c5 & c6 & c7).fillna(False)


# ----- COMPOSITE ---------------------------------------------------------

def compute_all_indicators(
    df: pd.DataFrame, benchmark: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """All indicators as a DataFrame, for bulk analysis (e.g. gate-check)."""
    result = pd.DataFrame(index=df.index)
    result["atr_pct_2d"] = atr_pct(df, 2)
    result["atr_pct_10d"] = atr_pct(df, 10)
    result["atr_pct_14d"] = atr_pct(df, 14)
    result["adr_pct_20d"] = adr_pct(df, 20)
    result["sigma_spike"] = sigma_spike(df)
    result["rmv_5d"] = relative_measured_volatility(df, 5)
    result["rmv_10d"] = relative_measured_volatility(df, 10)
    result["rmv_15d"] = relative_measured_volatility(df, 15)
    result["up_down_20d"] = up_down_ratio(df, 20)
    result["up_down_50d"] = up_down_ratio(df, 50)
    result["price_vs_10ema"] = price_vs_ema(df, 10)
    result["price_vs_21ema"] = price_vs_ema(df, 21)
    result["sma_aligned"] = sma_alignment(df)
    result["weinstein_stage"] = weinstein_stage(df)
    result["dcr"] = dcr(df)
    result["wcr"] = wcr(df)
    result["relative_volume_20d"] = relative_volume(df, 20)
    result["volume_dry_up"] = volume_dry_up(df)
    result["pocket_pivot"] = pocket_pivot(df)
    result["open_eq_low"] = open_equals_low(df)
    result["open_eq_high"] = open_equals_high(df)
    result["vcp_score"] = vcp_score(df)
    result["minervini_template"] = minervini_trend_template(df)

    if benchmark is not None:
        result["rs_1m"] = relative_strength(df, benchmark, 21)
        result["rs_3m"] = relative_strength(df, benchmark, 63)
        result["rs_12m"] = relative_strength(df, benchmark, 252)
        result["rs_new_high_before_price"] = rs_new_high_before_price(df, benchmark)

    return result
