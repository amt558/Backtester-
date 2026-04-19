"""Verdict-engine aggregation tests."""
from __future__ import annotations

from tradelab.results import BacktestResult, BacktestMetrics
from tradelab.robustness.verdict import VerdictResult, compute_verdict


def _bt(pf: float, trades: int = 100, sharpe: float = 1.0):
    m = BacktestMetrics(
        total_trades=trades, wins=int(trades * 0.6), losses=int(trades * 0.4),
        win_rate=60.0, profit_factor=pf, sharpe_ratio=sharpe,
        max_drawdown_pct=-10.0,
    )
    return BacktestResult(
        strategy="x", start_date="2023-01-01", end_date="2024-01-01",
        params={}, metrics=m, trades=[], equity_curve=[],
    )


def test_fragile_pf_alone_yields_fragile():
    v = compute_verdict(_bt(pf=0.9), dsr=0.3)
    assert v.verdict == "FRAGILE"
    # PF fragile + DSR fragile = 2 fragile signals
    assert len(v.fragile_signals) >= 2


def test_robust_pf_plus_robust_dsr_alone_is_inconclusive():
    # Strong PF + strong DSR, but no other tests run → not enough robust
    # signals to cross the >= max(3, n/2) threshold.
    v = compute_verdict(_bt(pf=1.6), dsr=0.97)
    assert v.verdict == "INCONCLUSIVE"


def test_all_signals_robust_yields_robust():
    from tradelab.robustness.param_landscape import ParamLandscapeResult
    from tradelab.robustness.entry_delay import EntryDelayResult, EntryDelayPoint
    from tradelab.robustness.loso import LOSOResult, LOSOFold

    bt = _bt(pf=1.6)
    landscape = ParamLandscapeResult(
        top_params=["a", "b"], grid_values=[[1, 2], [3, 4]],
        fitness_grid=[[1.0, 1.0], [1.0, 1.0]],
        best_fitness=1.0, mean_fitness=1.0, std_fitness=0.01,
        smoothness_ratio=0.01, cliff_flag=False,
    )
    ed = EntryDelayResult(delays=[0, 1], points=[
        EntryDelayPoint(delay=0, metrics=bt.metrics),
        EntryDelayPoint(delay=1, metrics=BacktestMetrics(
            total_trades=100, wins=60, losses=40, win_rate=60.0,
            profit_factor=1.55,  # drop < 10%
        )),
    ])
    m_fold = BacktestMetrics(total_trades=50, wins=30, losses=20,
                             win_rate=60.0, profit_factor=1.55)
    lo = LOSOResult(
        folds=[
            LOSOFold(held_out_symbol="A", metrics=m_fold),
            LOSOFold(held_out_symbol="B", metrics=m_fold),
        ],
        pf_mean=1.55, pf_min=1.5, pf_max=1.6, pf_spread=0.1,
    )
    v = compute_verdict(bt, dsr=0.97, mc=None, landscape=landscape,
                         entry_delay=ed, loso=lo)
    assert v.verdict == "ROBUST", f"expected ROBUST, got {v.verdict}: {[(s.name, s.outcome) for s in v.signals]}"


def test_one_fragile_with_no_robust_yields_fragile():
    v = compute_verdict(_bt(pf=0.8))
    assert v.verdict == "FRAGILE"


def test_mixed_yields_inconclusive():
    # PF robust (1.6), DSR in middle
    v = compute_verdict(_bt(pf=1.6), dsr=0.75)
    assert v.verdict == "INCONCLUSIVE"


def test_verdict_lists_signals_with_reasons():
    v = compute_verdict(_bt(pf=1.6), dsr=0.97)
    for s in v.signals:
        assert s.name and s.reason
        assert s.outcome in ("robust", "inconclusive", "fragile")
