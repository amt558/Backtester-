"""
Generate an executive markdown report from backtest + optional Optuna + optional WF results.

Observations only. No prescriptive text. DSR and robustness fields are stubbed
with "Pending Phase 0/1" until those engines land.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from ..determinism import hash_config, hash_universe, render_footer
from ..engines.dsr import classify_dsr, deflated_sharpe_ratio
from ..results import BacktestResult, OptunaResult, WalkForwardResult
from . import templates as T

# Avoid a hard import cycle: robustness imports reporting types are minimal.
try:
    from ..robustness import RobustnessSuiteResult
except ImportError:
    RobustnessSuiteResult = None  # type: ignore


def _compute_dsr(bt: BacktestResult, opt: Optional[OptunaResult]) -> tuple[float, str]:
    """Compute DSR from backtest equity curve. Returns (probability, classification)."""
    import math
    returns = bt.daily_returns()
    if returns is None or len(returns) < 10:
        return float("nan"), "undefined"
    n_trials = opt.n_trials if opt else 1
    p = deflated_sharpe_ratio(returns.values, n_trials=n_trials)
    return p, classify_dsr(p)


def _fmt_dsr(p: float, verdict: str) -> str:
    import math
    if math.isnan(p):
        return "—"
    return f"{p:.3f} ({verdict})"


def _verdict_line(pf: float, sharpe: float, wfe: float) -> str:
    if pf >= 1.5 and sharpe >= 1.0 and wfe >= 0.7:
        return "Edge profile: **promising** — positive edge across metrics, acceptable out-of-sample preservation. Full robustness verification pending Phase 1."
    if pf >= 1.1 and sharpe >= 0.3:
        return "Edge profile: **marginal** — positive in-sample edge but fragile or underpowered. Verify with walk-forward and robustness before trusting."
    return "Edge profile: **weak** — insufficient or absent edge on current metrics. Reconsider strategy hypothesis or data window before proceeding."


def _collect_weak_windows(wf: WalkForwardResult, threshold: float = 0.9) -> list[str]:
    if not wf:
        return []
    out = []
    for w in wf.windows:
        if w.test_metrics is None:
            continue
        if w.test_metrics.profit_factor < threshold:
            out.append(f"Window {w.index}: OOS PF {w.test_metrics.profit_factor:.2f} ({w.test_start} → {w.test_end})")
    return out


def _observations(bt: BacktestResult, opt: Optional[OptunaResult], wf: Optional[WalkForwardResult]) -> list[str]:
    import math
    obs = []
    m = bt.metrics
    obs.append(f"Total trades: {m.total_trades}. Average bars held: {m.avg_bars_held}.")
    obs.append(f"Win rate {m.win_rate}%; average win {m.avg_win_pct}% vs average loss {m.avg_loss_pct}%.")
    obs.append(f"Peak-to-trough drawdown: {m.max_drawdown_pct}%.")

    dsr_p, dsr_verdict = _compute_dsr(bt, opt)
    if not math.isnan(dsr_p):
        n_trials = opt.n_trials if opt else 1
        obs.append(
            f"Deflated Sharpe: {dsr_p:.3f} ({dsr_verdict}) "
            f"after {n_trials} trial{'s' if n_trials != 1 else ''}."
        )

    if opt and opt.param_importance:
        top = sorted(opt.param_importance.items(), key=lambda kv: kv[1], reverse=True)[0]
        obs.append(f"Parameter importance dominated by `{top[0]}` at {top[1]*100:.1f}% of variance.")

    if wf:
        is_pfs = [w.train_metrics.profit_factor for w in wf.windows if w.train_metrics]
        oos_pfs = [w.test_metrics.profit_factor for w in wf.windows if w.test_metrics]
        if is_pfs and oos_pfs:
            is_mean = sum(is_pfs) / len(is_pfs)
            oos_mean = sum(oos_pfs) / len(oos_pfs)
            obs.append(f"Walk-forward: IS mean PF {is_mean:.2f} vs OOS mean PF {oos_mean:.2f} across {len(wf.windows)} windows.")
        obs.append(f"Aggregate OOS WFE ratio: {wf.wfe_ratio}.")

    return obs


def _render_robustness_section(robust) -> str:
    """Render the full robustness section from a RobustnessSuiteResult."""
    parts = [T.ROBUSTNESS_HEADER.format(verdict=robust.verdict.verdict)]
    for s in robust.verdict.signals:
        parts.append(T.ROBUSTNESS_ROW.format(
            name=s.name, outcome=s.outcome, reason=s.reason,
        ))

    # MC table
    mc = robust.monte_carlo
    if mc and mc.distributions:
        mc_lines = []
        for method in mc.methods:
            cells = []
            for metric in ["max_dd", "max_loss_streak", "time_underwater", "ulcer_index"]:
                try:
                    d = mc.get(method, metric)
                    cells.append(f"{d.observed:.2f} ({d.percentile_of_observed:.0f})")
                except KeyError:
                    cells.append("-")
            mc_lines.append(f"| {method} | " + " | ".join(cells) + " |")
        mc_rows = "\n".join(mc_lines)
    else:
        mc_rows = "| (no trades) | - | - | - | - |"

    # Landscape
    lp = robust.param_landscape
    if lp and len(lp.top_params) == 2:
        lp0, lp1 = lp.top_params[0], lp.top_params[1]
        best_f = lp.best_fitness
        mean_f = lp.mean_fitness
        smooth = lp.smoothness_ratio
        cliff = "yes" if lp.cliff_flag else "no"
        grid_size = len(lp.fitness_grid) if lp.fitness_grid else 0
    else:
        lp0 = lp1 = "-"
        best_f = mean_f = smooth = 0.0
        cliff = "-"
        grid_size = 0

    # Entry delay
    ed = robust.entry_delay
    ed_rows_list = []
    pf_drop = 0.0
    if ed and ed.points:
        for p in ed.points:
            m = p.metrics
            ed_rows_list.append(
                f"| +{p.delay} | {m.total_trades} | {m.profit_factor} | {m.sharpe_ratio} | {m.pct_return}% |"
            )
        pf_drop = ed.pf_drop_one_bar
    ed_rows = "\n".join(ed_rows_list) if ed_rows_list else "| - | - | - | - | - |"

    # LOSO
    lo = robust.loso
    loso_rows_list = []
    if lo and lo.folds:
        for f in lo.folds:
            m = f.metrics
            loso_rows_list.append(
                f"| {f.held_out_symbol} | {m.total_trades} | {m.profit_factor} | {m.sharpe_ratio} | {m.pct_return}% |"
            )
        pf_mean = lo.pf_mean
        pf_min = lo.pf_min
        pf_max = lo.pf_max
        pf_spread = lo.pf_spread
        n_folds = len(lo.folds)
    else:
        pf_mean = pf_min = pf_max = pf_spread = 0.0
        n_folds = 0
    loso_rows = "\n".join(loso_rows_list) if loso_rows_list else "| - | - | - | - | - |"

    parts.append(T.ROBUSTNESS_DETAILS.format(
        n_sims=mc.n_simulations if mc else 0,
        mc_rows=mc_rows,
        grid_size=grid_size,
        lp0=lp0, lp1=lp1,
        best_fitness=best_f, mean_fitness=mean_f, smoothness=smooth, cliff=cliff,
        ed_rows=ed_rows,
        pf_drop=pf_drop,
        n_folds=n_folds, pf_mean=pf_mean, pf_min=pf_min, pf_max=pf_max, pf_spread=pf_spread,
        loso_rows=loso_rows,
    ))
    return "".join(parts)


def generate_executive_report(
    backtest_result: BacktestResult,
    optuna_result: Optional[OptunaResult] = None,
    wf_result: Optional[WalkForwardResult] = None,
    universe: Optional[dict] = None,
    out_dir: Optional[Path] = None,
    robustness_result = None,
) -> Path:
    """
    Generate the executive report.

    Returns the path to the markdown file written.
    """
    ts = datetime.now()
    ts_str = ts.strftime("%Y-%m-%d_%H%M%S")
    if out_dir is None:
        out_dir = Path("reports") / f"{backtest_result.strategy}_{ts_str}"
    out_dir.mkdir(parents=True, exist_ok=True)

    m = backtest_result.metrics

    # Header
    universe_str = ", ".join(sorted(universe.keys())) if universe else "see config"
    parts = [T.HEADER.format(
        strategy_name=backtest_result.strategy,
        timestamp=ts.strftime("%Y-%m-%d %H:%M:%S"),
        start=backtest_result.start_date,
        end=backtest_result.end_date,
        universe=universe_str,
    )]

    # Verdict
    wfe_val = wf_result.wfe_ratio if wf_result else 0.0
    parts.append(T.VERDICT.format(
        verdict_line=_verdict_line(m.profit_factor, m.sharpe_ratio, wfe_val)
    ))

    # Edge metrics
    oos_is = wf_result.wfe_ratio if wf_result else "N/A"
    dsr_p, dsr_verdict = _compute_dsr(backtest_result, optuna_result)
    parts.append(T.EDGE_METRICS.format(
        pf=m.profit_factor,
        sharpe=m.sharpe_ratio,
        dsr=_fmt_dsr(dsr_p, dsr_verdict),
        total_return=m.pct_return,
        annual_return=m.annual_return,
        wfe=wf_result.wfe_ratio if wf_result else "N/A",
        oos_is_ratio=oos_is,
    ))

    # Performance snapshot
    expectancy = (m.win_rate / 100 * m.avg_win_pct) + ((1 - m.win_rate / 100) * m.avg_loss_pct)
    parts.append(T.PERFORMANCE_SNAPSHOT.format(
        total_trades=m.total_trades, win_rate=m.win_rate,
        wins=m.wins, losses=m.losses,
        avg_win_pct=m.avg_win_pct, avg_loss_pct=m.avg_loss_pct,
        expectancy=round(expectancy, 3),
        max_dd=m.max_drawdown_pct, avg_bars_held=m.avg_bars_held,
    ))

    # WF table
    if wf_result and wf_result.windows:
        parts.append(T.WF_TABLE_HEADER)
        for w in wf_result.windows:
            tr_m = w.train_metrics
            ts_m = w.test_metrics
            parts.append(T.WF_TABLE_ROW.format(
                i=w.index,
                train=f"{w.train_start} to {w.train_end}",
                test=f"{w.test_start} to {w.test_end}",
                is_pf=tr_m.profit_factor if tr_m else "-",
                oos_pf=ts_m.profit_factor if ts_m else "-",
                is_trades=tr_m.total_trades if tr_m else "-",
                oos_trades=ts_m.total_trades if ts_m else "-",
                oos_wr=ts_m.win_rate if ts_m else "-",
                oos_dd=ts_m.max_drawdown_pct if ts_m else "-",
            ))
        parts.append("\n---\n")
    else:
        parts.append(T.WF_TABLE_NONE)

    # Param importance
    if optuna_result and optuna_result.param_importance:
        parts.append(T.PARAM_IMPORTANCE_HEADER)
        ranked = sorted(optuna_result.param_importance.items(), key=lambda kv: kv[1], reverse=True)
        for rank, (name, imp) in enumerate(ranked[:5], 1):
            parts.append(T.PARAM_IMPORTANCE_ROW.format(rank=rank, name=name, importance=imp))
        parts.append("\n---\n")
    else:
        parts.append(T.PARAM_IMPORTANCE_NONE)

    # Robustness — either full section (if suite was run) or stub
    if robustness_result is not None:
        parts.append(_render_robustness_section(robustness_result))
    else:
        parts.append(T.ROBUSTNESS_STUB)

    # Where it breaks
    parts.append(T.WHERE_IT_BREAKS_HEADER)
    weak = _collect_weak_windows(wf_result) if wf_result else []
    if weak:
        for w in weak:
            parts.append(f"- {w}\n")
    else:
        parts.append("*No structural weaknesses detected at current threshold (OOS PF < 0.9). Per-symbol breakdown appears in section 5d when --robustness is passed.*\n")
    parts.append("\n---\n")

    # Observations
    parts.append(T.OBSERVATIONS_HEADER)
    for obs in _observations(backtest_result, optuna_result, wf_result):
        parts.append(f"- {obs}\n")
    parts.append("\n")

    # Footer
    parts.append(T.FOOTER_HEADER)
    data_hash = hash_universe(universe) if universe else None
    config_hash = hash_config(backtest_result.params)
    parts.append(render_footer(data_hash=data_hash, config_hash=config_hash))
    parts.append(f"\n\ngenerated: {ts.strftime('%Y-%m-%d %H:%M:%S')}\n")

    out_path = out_dir / "executive_report.md"
    out_path.write_text("".join(parts), encoding="utf-8")
    return out_path
