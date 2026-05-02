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


def test_verdict_result_has_diagnostics_field_default_empty():
    """VerdictResult must include a diagnostics dict, default to empty."""
    from tradelab.robustness.verdict import VerdictResult
    v = VerdictResult(verdict="ROBUST")
    assert v.diagnostics == {}


def test_verdict_result_diagnostics_round_trips_through_json():
    """diagnostics field must serialize and deserialize."""
    from tradelab.robustness.verdict import VerdictResult, VerdictSignal
    v = VerdictResult(
        verdict="ROBUST",
        signals=[VerdictSignal(name="x", outcome="robust", reason="test")],
        diagnostics={"trade_efficiency": 0.62, "future_metric": None},
    )
    payload = v.model_dump_json()
    parsed = VerdictResult.model_validate_json(payload)
    assert parsed.diagnostics == {"trade_efficiency": 0.62, "future_metric": None}


def test_verdict_result_old_json_without_diagnostics_still_parses():
    """Backwards compat: JSON written before diagnostics field must still parse."""
    from tradelab.robustness.verdict import VerdictResult
    old_payload = '{"verdict": "ROBUST", "signals": []}'
    v = VerdictResult.model_validate_json(old_payload)
    assert v.diagnostics == {}


def _wf_with_decay(decay_ratio: float) -> "WalkForwardResult":
    """Build a 6-window WF where late-half PF / early-half PF ≈ decay_ratio."""
    from tradelab.results import (
        BacktestMetrics, WalkForwardResult, WalkForwardWindow,
    )

    def w(idx: int, gp: float, gl: float) -> WalkForwardWindow:
        pf = (gp / gl) if gl > 0 else 0.0
        m = BacktestMetrics(
            total_trades=20, wins=12, losses=8, win_rate=60.0,
            profit_factor=pf, gross_profit=gp, gross_loss=gl,
        )
        return WalkForwardWindow(
            index=idx,
            train_start="2022-01-01", train_end="2022-06-30",
            test_start="2022-07-01", test_end="2022-12-31",
            train_metrics=None, test_metrics=m, best_params={},
        )

    # Early half: aggregate PF = 3.0 (300 / 100)
    early = [w(0, 100, 33), w(1, 100, 33), w(2, 100, 34)]
    # Late half: aggregate PF = decay_ratio * 3.0
    late_total_gp = decay_ratio * 3.0 * 100  # late_pf * gl_late
    late = [
        w(3, late_total_gp / 3, 33),
        w(4, late_total_gp / 3, 33),
        w(5, late_total_gp / 3, 34),
    ]
    return WalkForwardResult(
        strategy="x", n_windows=6, windows=early + late,
        wfe_ratio=0.8,
    )


def test_wf_decay_signal_emits_fragile_when_decaying():
    wf = _wf_with_decay(decay_ratio=0.5)  # 50% of early → < 0.70
    v = compute_verdict(_bt(pf=1.6), wf=wf)
    decay_signals = [s for s in v.signals if s.name == "wf_decay"]
    assert len(decay_signals) == 1
    assert decay_signals[0].outcome == "fragile"


def test_wf_decay_signal_emits_robust_when_stable():
    wf = _wf_with_decay(decay_ratio=1.0)  # equal halves → > 0.90
    v = compute_verdict(_bt(pf=1.6), wf=wf)
    decay_signals = [s for s in v.signals if s.name == "wf_decay"]
    assert len(decay_signals) == 1
    assert decay_signals[0].outcome == "robust"


def test_wf_decay_signal_emits_inconclusive_in_middle_band():
    wf = _wf_with_decay(decay_ratio=0.80)  # between 0.70 and 0.90
    v = compute_verdict(_bt(pf=1.6), wf=wf)
    decay_signals = [s for s in v.signals if s.name == "wf_decay"]
    assert len(decay_signals) == 1
    assert decay_signals[0].outcome == "inconclusive"


def test_wf_decay_signal_absent_when_wf_is_none():
    v = compute_verdict(_bt(pf=1.6), wf=None)
    assert not any(s.name == "wf_decay" for s in v.signals)


def test_wf_decay_signal_absent_when_fewer_than_4_windows():
    from tradelab.results import (
        BacktestMetrics, WalkForwardResult, WalkForwardWindow,
    )
    m = BacktestMetrics(
        total_trades=20, wins=12, losses=8, win_rate=60.0,
        profit_factor=1.5, gross_profit=100, gross_loss=66,
    )
    windows = [
        WalkForwardWindow(
            index=i,
            train_start="2022-01-01", train_end="2022-06-30",
            test_start="2022-07-01", test_end="2022-12-31",
            train_metrics=None, test_metrics=m, best_params={},
        )
        for i in range(3)
    ]
    wf = WalkForwardResult(strategy="x", n_windows=3, windows=windows, wfe_ratio=0.8)
    v = compute_verdict(_bt(pf=1.6), wf=wf)
    assert not any(s.name == "wf_decay" for s in v.signals)
