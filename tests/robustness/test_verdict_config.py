"""Verdict thresholds read from tradelab.yaml (not hardcoded)."""
from __future__ import annotations

from tradelab.results import BacktestResult, BacktestMetrics
from tradelab.robustness.verdict import _resolve_thresholds, compute_verdict


def _bt(pf: float = 1.0):
    m = BacktestMetrics(total_trades=20, wins=10, losses=10, win_rate=50.0,
                        profit_factor=pf, sharpe_ratio=0.5, max_drawdown_pct=-5.0)
    return BacktestResult(strategy="t", start_date="2023-01-01", end_date="2024-01-01",
                           params={}, metrics=m, trades=[], equity_curve=[])


def test_resolve_thresholds_reads_config(monkeypatch):
    # config.get_config() returns a real Config if tradelab.yaml is found
    # from the test's cwd (which is the repo root in normal pytest invocations).
    t = _resolve_thresholds()
    assert "pf_robust" in t
    assert t["pf_robust"] == 1.5   # value from tradelab.yaml


def test_resolve_thresholds_falls_back_when_config_missing(tmp_path, monkeypatch):
    # chdir into a directory with no tradelab.yaml — config loader must fail,
    # and _resolve_thresholds must fall back to code defaults.
    monkeypatch.chdir(tmp_path)
    # Reset the cached config so it reloads
    from tradelab import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "_config", None)
    t = _resolve_thresholds()
    assert t["pf_robust"] == 1.5   # fallback equals yaml default, confirms shape


def test_verdict_respects_yaml_override(monkeypatch, tmp_path):
    """Write a tradelab.yaml with a custom pf_robust and verify verdict uses it."""
    # Build a minimal yaml with all required sections
    yaml_content = """
paths:
  data_dir: "./_d"
  reports_dir: "./_r"
  cache_dir: "./_c"
robustness:
  thresholds:
    pf_robust: 3.0
    pf_fragile: 2.0
"""
    (tmp_path / "tradelab.yaml").write_text(yaml_content)
    monkeypatch.chdir(tmp_path)
    from tradelab import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "_config", None)

    # PF = 2.5 → with default thresholds (1.5 / 1.1) this would be ROBUST;
    # with the custom thresholds (3.0 / 2.0) it is INCONCLUSIVE.
    v = compute_verdict(_bt(pf=2.5), dsr=0.7)
    baseline_signal = next(s for s in v.signals if s.name == "baseline_pf")
    assert baseline_signal.outcome == "inconclusive"
