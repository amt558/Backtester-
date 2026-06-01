"""Task H: the robustness suite must fail LOUDLY with a clear reason on an
empty trade set, instead of crashing deep inside a trade-dependent step
(Monte Carlo resampling / LOSO on zero trades).
"""
from __future__ import annotations

import pytest

from tradelab.results import BacktestResult
from tradelab.robustness.suite import RobustnessInputError, run_robustness_suite


def test_zero_trade_backtest_raises_clear_robustness_input_error():
    bt = BacktestResult(
        strategy="empty_strat",
        start_date="2024-01-01",
        end_date="2024-06-01",
    )
    assert bt.metrics.total_trades == 0

    with pytest.raises(RobustnessInputError) as ei:
        # strategy/ticker_data are irrelevant — the guard must fire before any
        # trade-dependent step touches them.
        run_robustness_suite(strategy=object(), ticker_data={}, backtest_result=bt)

    msg = str(ei.value).lower()
    assert "0 trades" in msg or "no trades" in msg, msg
