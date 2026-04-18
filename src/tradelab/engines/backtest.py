"""
Portfolio backtest engine.

Ported from C:/TradingScripts/s2_backtest.py. Changes:

1. Strategy-agnostic: consumes the `buy_signal`, `entry_stop`, `entry_score`
   columns produced by any Strategy.generate_signals() rather than calling
   entry_check directly.
2. LEAKAGE FIX: the original code used df.index[-1] to close surviving
   positions at end-of-data. When called over a sub-window (walk-forward),
   that leaked future bars into the OOS test result. This engine uses the
   end-of-window close instead.
3. Returns a Pydantic BacktestResult instead of a dict.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from ..config import get_config
from ..results import BacktestResult, BacktestMetrics, Trade
from ..strategies.base import Strategy


def _exit_check(r, pos, params):
    """
    Return (should_exit, exit_price, reason).
    Updates pos['stop'] in place with trailing logic.
    """
    atr = r["ATR"]
    gain = pos["highest"] - pos["ep"]

    if gain > params["trail_tighten_atr"] * pos["entry_atr"]:
        trail = pos["highest"] - params["trail_tight_mult"] * atr
    else:
        trail = pos["highest"] - params["trail_wide_mult"] * atr

    pos["stop"] = max(pos.get("stop", 0.0), trail)

    if r["Low"] <= pos["stop"]:
        return True, pos["stop"], "Trail Stop"
    if r["Close"] < r["SMA50"]:
        return True, r["Close"], "Below SMA50"
    return False, 0.0, ""


def run_backtest(
    strategy,
    ticker_data,
    start=None,
    end=None,
    capital=None,
    pos_pct=None,
    max_pos=None,
    commission=None,
    spy_close=None,
):
    """Run portfolio backtest. Returns BacktestResult."""
    cfg = get_config()
    start = start or cfg.defaults.data_start
    end = end or cfg.defaults.data_end
    capital_val = capital if capital is not None else cfg.defaults.initial_capital
    pos_pct_val = (pos_pct if pos_pct is not None else cfg.defaults.position_size_pct) / 100.0
    max_pos_val = max_pos if max_pos is not None else cfg.defaults.max_concurrent_positions
    commission_val = commission if commission is not None else cfg.defaults.commission_per_trade

    params = strategy.params
    signaled = strategy.generate_signals(ticker_data, spy_close=spy_close)

    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    all_dates = sorted({d for df in signaled.values() for d in df["Date"].tolist()})
    all_dates = [d for d in all_dates if start_ts <= d <= end_ts]

    indexed = {sym: df.set_index("Date") for sym, df in signaled.items()}

    cap = capital_val
    peak = capital_val
    max_dd = 0.0
    positions = {}
    trades = []
    equity_curve = []

    for date in all_dates:
        # --- PASS 1: EXITS ---
        for sym in list(positions.keys()):
            df = indexed.get(sym)
            if df is None or date not in df.index:
                continue
            r = df.loc[date]
            if pd.isna(r.get("ATR", np.nan)) or r.get("ATR", 0) == 0:
                continue

            pos = positions[sym]
            if r["High"] > pos["highest"]:
                pos["highest"] = r["High"]

            should_exit, exit_price, reason = _exit_check(r, pos, params)
            if should_exit:
                shares = pos["shares"]
                pnl = (exit_price - pos["ep"]) * shares - commission_val * 2
                trades.append({
                    "ticker": sym,
                    "entry_date": pos["entry_date"],
                    "exit_date": str(date.date()),
                    "ep": round(pos["ep"], 2),
                    "xp": round(exit_price, 2),
                    "shares": shares,
                    "pnl": round(pnl, 2),
                    "pnl_pct": round((exit_price - pos["ep"]) / pos["ep"] * 100, 2),
                    "bars_held": pos["bars_held"] + 1,
                    "reason": reason,
                })
                cap += pnl
                del positions[sym]

        for pos in positions.values():
            pos["bars_held"] += 1

        # --- PASS 2: COLLECT SIGNALS ---
        signals = []
        for sym, df in indexed.items():
            if date not in df.index:
                continue
            if sym in positions:
                continue
            curr_idx = df.index.get_loc(date)
            if curr_idx < 1:
                continue
            r = df.iloc[curr_idx]
            if not bool(r.get("buy_signal", False)):
                continue
            if pd.isna(r.get("ATR", np.nan)) or r.get("ATR", 0) == 0:
                continue

            signals.append({
                "sym": sym,
                "date": date,
                "price": r["Close"],
                "stop": r["entry_stop"],
                "atr": r["ATR"],
                "score": r.get("entry_score", 0.0),
            })

        # --- PASS 3: RANK AND FILL ---
        signals.sort(key=lambda s: s["score"], reverse=True)
        for sig in signals:
            if len(positions) >= max_pos_val:
                break
            pv = cap * pos_pct_val
            shares = int(pv / sig["price"])
            if shares <= 0:
                continue
            positions[sig["sym"]] = {
                "ep": sig["price"],
                "shares": shares,
                "stop": sig["stop"],
                "highest": sig["price"],
                "entry_atr": sig["atr"],
                "entry_date": str(sig["date"].date()),
                "bars_held": 0,
            }

        # --- PASS 4: MARK-TO-MARKET ---
        unr = 0.0
        for sym, pos in positions.items():
            df = indexed.get(sym)
            if df is None or date not in df.index:
                continue
            px = df.loc[date, "Close"]
            unr += (px - pos["ep"]) * pos["shares"]

        total_equity = cap + unr
        equity_curve.append({"date": str(date.date()), "equity": round(total_equity, 2)})

        if total_equity > peak:
            peak = total_equity
        dd = (total_equity - peak) / peak * 100
        if dd < max_dd:
            max_dd = dd

    # --- END-OF-WINDOW LIQUIDATION (LEAKAGE FIX) ---
    if all_dates:
        window_end_date = all_dates[-1]
        for sym, pos in list(positions.items()):
            df = indexed.get(sym)
            if df is None:
                continue
            sym_dates = df.index[df.index <= window_end_date]
            if len(sym_dates) == 0:
                continue
            close_date = sym_dates[-1]
            px = df.loc[close_date, "Close"]
            shares = pos["shares"]
            pnl = (px - pos["ep"]) * shares - commission_val * 2
            trades.append({
                "ticker": sym,
                "entry_date": pos["entry_date"],
                "exit_date": str(close_date.date()),
                "ep": round(pos["ep"], 2),
                "xp": round(px, 2),
                "shares": shares,
                "pnl": round(pnl, 2),
                "pnl_pct": round((px - pos["ep"]) / pos["ep"] * 100, 2),
                "bars_held": pos["bars_held"],
                "reason": "End of Window",
            })
            cap += pnl

    # --- METRICS ---
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gp = sum(wins) if wins else 0.0
    gl = abs(sum(losses)) if losses else 0.001

    pnl_pcts = [t["pnl_pct"] for t in trades]
    sharpe = 0.0
    if len(pnl_pcts) > 1 and np.std(pnl_pcts) > 0:
        sharpe = float(np.mean(pnl_pcts) / np.std(pnl_pcts) * np.sqrt(252))

    years = len(all_dates) / 252 if all_dates else 1
    annual_return = ((cap / capital_val) ** (1 / years) - 1) * 100 if years > 0 else 0.0

    metrics = BacktestMetrics(
        total_trades=len(trades),
        wins=len(wins),
        losses=len(losses),
        win_rate=round(len(wins) / max(len(trades), 1) * 100, 2),
        profit_factor=round(gp / gl, 3),
        gross_profit=round(gp, 2),
        gross_loss=round(gl, 2),
        net_pnl=round(cap - capital_val, 2),
        pct_return=round((cap / capital_val - 1) * 100, 2),
        annual_return=round(annual_return, 2),
        final_equity=round(cap, 2),
        avg_win_pct=round(float(np.mean([t["pnl_pct"] for t in trades if t["pnl"] > 0])), 3) if wins else 0.0,
        avg_loss_pct=round(float(np.mean([t["pnl_pct"] for t in trades if t["pnl"] <= 0])), 3) if losses else 0.0,
        avg_bars_held=round(float(np.mean([t["bars_held"] for t in trades])), 2) if trades else 0.0,
        max_drawdown_pct=round(max_dd, 3),
        sharpe_ratio=round(sharpe, 3),
    )

    trade_objs = [
        Trade(
            ticker=t["ticker"],
            entry_date=t["entry_date"],
            exit_date=t["exit_date"],
            entry_price=t["ep"],
            exit_price=t["xp"],
            shares=t["shares"],
            pnl=t["pnl"],
            pnl_pct=t["pnl_pct"],
            bars_held=t["bars_held"],
            exit_reason=t["reason"],
        )
        for t in trades
    ]

    return BacktestResult(
        strategy=strategy.name,
        start_date=start,
        end_date=end,
        params=dict(params),
        metrics=metrics,
        trades=trade_objs,
        equity_curve=equity_curve,
    )