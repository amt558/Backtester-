"""Synthetic dial-gauge regression test — records baseline on first run, asserts on subsequent."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tradelab.engines.backtest import run_backtest
from tradelab.synthetic import DialGauge, build_dial_gauge_universe


EXPECTED_PATH = Path(__file__).parent / "expected.yaml"
TOL_PF = 0.01
TOL_EQUITY = 1.00
TOL_DD = 0.10


def _load_expected():
    with EXPECTED_PATH.open("r") as f:
        return yaml.safe_load(f) or {}


def _save_expected(payload):
    with EXPECTED_PATH.open("w") as f:
        yaml.safe_dump(payload, f, sort_keys=False)


def _run_dial():
    universe = build_dial_gauge_universe()
    dates = universe["DIAL"]["Date"]
    start = str(dates.iloc[0].date())
    end = str(dates.iloc[-1].date())
    result = run_backtest(DialGauge(), universe, start=start, end=end)
    m = result.metrics
    return {
        "total_trades": int(m.total_trades),
        "profit_factor": float(m.profit_factor),
        "final_equity": float(m.final_equity),
        "max_drawdown_pct": float(m.max_drawdown_pct),
    }


def test_dial_gauge_matches_locked_baseline():
    expected = _load_expected()
    observed = _run_dial()
    metrics = expected.get("metrics") or {}
    needs_record = not metrics or any(v is None for v in metrics.values())

    if needs_record:
        payload = expected if expected else {
            "version": 1,
            "universe": {"symbol": "DIAL", "start": "2022-01-03", "n_bars": 500},
        }
        payload["metrics"] = observed
        _save_expected(payload)
        pytest.skip(f"Baseline recorded: {observed}. Rerun to lock.")

    assert observed["total_trades"] == metrics["total_trades"]
    assert abs(observed["profit_factor"] - metrics["profit_factor"]) <= TOL_PF
    assert abs(observed["final_equity"] - metrics["final_equity"]) <= TOL_EQUITY
    assert abs(observed["max_drawdown_pct"] - metrics["max_drawdown_pct"]) <= TOL_DD
