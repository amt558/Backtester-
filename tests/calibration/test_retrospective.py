import json
from pathlib import Path
from unittest.mock import MagicMock
import pytest

FIXTURES = Path(__file__).parent.parent / "fixtures" / "retrospective"


def test_load_predicted_verdict():
    from tradelab.calibration.retrospective import load_predicted_verdict
    rv = load_predicted_verdict(FIXTURES / "robustness_sample.json")
    assert rv["verdict"] == "FRAGILE"
    assert rv["signals"]["baseline_pf"]["verdict"] == "FRAGILE"
    assert rv["signals"]["entry_delay"]["value"] == pytest.approx(0.66)


def test_per_strategy_outcomes_groups_by_strategy_and_buckets_unattributed():
    from tradelab.calibration.retrospective import compute_per_strategy_outcomes
    attributed = [
        {"symbol": "AAPL", "strategy": "S4_InsideDayBreakout", "pnl": 240.00},
        {"symbol": "AAPL", "strategy": "S4_InsideDayBreakout", "pnl": 400.00},
        {"symbol": "NVDA", "strategy": "S7_RDZMomentum", "pnl": -100.00},
        {"symbol": "GOOGL", "strategy": None, "pnl": 50.00},
    ]
    out = compute_per_strategy_outcomes(attributed)
    by_strat = {row["strategy"]: row for row in out}
    assert by_strat["S4_InsideDayBreakout"]["n_trades"] == 2
    assert by_strat["S4_InsideDayBreakout"]["total_pnl"] == 640.00
    assert by_strat["S7_RDZMomentum"]["n_trades"] == 1
    assert by_strat["unattributed"]["n_trades"] == 1
    assert by_strat["unattributed"]["total_pnl"] == 50.00


def test_per_strategy_outcomes_computes_live_pf():
    from tradelab.calibration.retrospective import compute_per_strategy_outcomes
    attributed = [
        {"strategy": "X", "pnl": 100.0},
        {"strategy": "X", "pnl": 200.0},
        {"strategy": "X", "pnl": -100.0},
    ]
    out = compute_per_strategy_outcomes(attributed)
    x = next(r for r in out if r["strategy"] == "X")
    # wins = 300, losses = 100, PF = 3.0
    assert x["live_pf"] == pytest.approx(3.0)


def test_per_strategy_outcomes_handles_zero_losses():
    from tradelab.calibration.retrospective import compute_per_strategy_outcomes
    attributed = [{"strategy": "X", "pnl": 100.0}, {"strategy": "X", "pnl": 50.0}]
    out = compute_per_strategy_outcomes(attributed)
    x = next(r for r in out if r["strategy"] == "X")
    # zero losses → PF is +inf
    assert x["live_pf"] == float("inf")


def test_seed_hit_rates_classifies_predictive_questionable_noisy():
    from tradelab.calibration.retrospective import compute_per_signal_seed_hit_rates
    # 3 strategies: 2 with entry_delay FRAGILE that lost, 1 that won
    strategies = [
        {"strategy": "S4", "live_pf": 0.85, "signals_fragile": ["entry_delay", "loso"]},
        {"strategy": "S8", "live_pf": 1.42, "signals_fragile": ["entry_delay", "loso"]},
        {"strategy": "S7", "live_pf": 0.61, "signals_fragile": ["baseline_pf"]},
    ]
    out = compute_per_signal_seed_hit_rates(strategies, fail_threshold=1.0)
    # entry_delay: 2 deployed, 1 failed → hit rate 0.5 → predictive
    assert out["entry_delay"]["fragile_fires"] == 2
    assert out["entry_delay"]["accepted_despite"] == 2
    assert out["entry_delay"]["failed_in_prod"] == 1
    # n=2 < 3 → insufficient sample
    assert out["entry_delay"]["read"] == "insufficient sample"
    # baseline_pf: 1 fired, 1 failed → n<3 → insufficient
    assert out["baseline_pf"]["read"] == "insufficient sample"


def test_seed_hit_rates_predictive_with_n_at_least_3():
    from tradelab.calibration.retrospective import compute_per_signal_seed_hit_rates
    strategies = [
        {"strategy": "A", "live_pf": 0.5, "signals_fragile": ["x"]},
        {"strategy": "B", "live_pf": 0.7, "signals_fragile": ["x"]},
        {"strategy": "C", "live_pf": 0.9, "signals_fragile": ["x"]},
    ]
    out = compute_per_signal_seed_hit_rates(strategies, fail_threshold=1.0)
    assert out["x"]["accepted_despite"] == 3
    assert out["x"]["failed_in_prod"] == 3
    assert out["x"]["hit_rate"] == 1.0
    assert out["x"]["read"] == "predictive"


def test_seed_hit_rates_noisy_when_zero_fail():
    from tradelab.calibration.retrospective import compute_per_signal_seed_hit_rates
    strategies = [
        {"strategy": "A", "live_pf": 1.5, "signals_fragile": ["x"]},
        {"strategy": "B", "live_pf": 1.7, "signals_fragile": ["x"]},
        {"strategy": "C", "live_pf": 2.0, "signals_fragile": ["x"]},
    ]
    out = compute_per_signal_seed_hit_rates(strategies, fail_threshold=1.0)
    assert out["x"]["accepted_despite"] == 3
    assert out["x"]["failed_in_prod"] == 0
    assert out["x"]["hit_rate"] == 0.0
    assert out["x"]["read"] == "noisy"


def test_run_retrospective_writes_output_with_attribution_quality(tmp_path):
    from tradelab.calibration.retrospective import run_retrospective_calibration
    fake_api = MagicMock()
    fake_api.list_orders.side_effect = [
        json.loads((FIXTURES / "alpaca_orders_sample.json").read_text()),
        [],
    ]
    out_path = tmp_path / "retrospective.json"
    result = run_retrospective_calibration(
        alpaca_api=fake_api,
        bot_log_path=FIXTURES / "bot_log_sample.log",
        reports_dir=FIXTURES,
        output_path=out_path,
        window_months=12,
    )
    assert out_path.exists()
    data = json.loads(out_path.read_text())
    assert data["code_divergence_caveat"] is True
    assert "attribution_quality" in data
    aq = data["attribution_quality"]
    assert "attributed_count" in aq
    assert "unattributed_count" in aq
    assert "attribution_pct" in aq
    assert "per_strategy" in data
    assert "per_signal_seed" in data
    assert data["window_months"] == 12


def test_run_retrospective_handles_missing_bot_log(tmp_path):
    from tradelab.calibration.retrospective import run_retrospective_calibration
    fake_api = MagicMock()
    fake_api.list_orders.side_effect = [
        json.loads((FIXTURES / "alpaca_orders_sample.json").read_text()),
        [],
    ]
    out_path = tmp_path / "retrospective.json"
    nonexistent_log = tmp_path / "no_log.log"
    result = run_retrospective_calibration(
        alpaca_api=fake_api,
        bot_log_path=nonexistent_log,
        reports_dir=FIXTURES,
        output_path=out_path,
        window_months=12,
    )
    data = json.loads(out_path.read_text())
    # All trades should be unattributed when log is missing
    assert data["attribution_quality"]["attributed_count"] == 0
    assert data["attribution_quality"]["attribution_pct"] == 0.0


def test_normalize_strategy_name_camel_to_snake():
    from tradelab.calibration.retrospective import normalize_strategy_name
    assert normalize_strategy_name("S2_PocketPivot") == "s2_pocket_pivot"
    assert normalize_strategy_name("S12_MomentumAcceleration") == "s12_momentum_acceleration"
    assert normalize_strategy_name("S4_InsideDayBreakout") == "s4_inside_day_breakout"


def test_normalize_strategy_name_keeps_multi_cap_acronyms():
    from tradelab.calibration.retrospective import normalize_strategy_name
    # RDZ and RS should stay together as 'rdz' and 'rs', not split as 'r_d_z' / 'r_s'
    assert normalize_strategy_name("S7_RDZMomentum") == "s7_rdz_momentum"
    assert normalize_strategy_name("S10_RSNewHighs") == "s10_rs_new_highs"


def test_normalize_strategy_name_idempotent_on_snake_case():
    from tradelab.calibration.retrospective import normalize_strategy_name
    assert normalize_strategy_name("s2_pocket_pivot") == "s2_pocket_pivot"


def test_run_retrospective_bridges_camel_log_to_snake_reports(tmp_path):
    """Retrospective must match bot's 'S2_PocketPivot' to tradelab's 's2_pocket_pivot'."""
    from tradelab.calibration.retrospective import run_retrospective_calibration
    from unittest.mock import MagicMock

    # Synthetic Alpaca data: one buy + sell pair on AAPL
    fake_api = MagicMock()
    fake_api.list_orders.side_effect = [[
        {"id": "1", "symbol": "AAPL", "side": "buy", "qty": "100",
         "filled_qty": "100", "filled_avg_price": "180.00",
         "filled_at": "2026-01-15T14:31:00Z", "client_order_id": "x1",
         "status": "filled"},
        {"id": "2", "symbol": "AAPL", "side": "sell", "qty": "100",
         "filled_qty": "100", "filled_avg_price": "175.00",  # loss
         "filled_at": "2026-01-15T19:00:00Z", "client_order_id": "x2",
         "status": "filled"},
    ], []]

    # Bot log uses CamelCase
    log = tmp_path / "bot.log"
    log.write_text(
        "2026-01-15 09:31:02 INFO Position added: AAPL (S4_InsideDayBreakout) - 100@$180.00 | Stop: $175.00\n"
    )

    # tradelab report uses snake_case
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "s4_inside_day_breakout_2026-04-19").mkdir()
    (reports / "s4_inside_day_breakout_2026-04-19" / "robustness_result.json").write_text(json.dumps({
        "strategy": "s4_inside_day_breakout",
        "verdict": "FRAGILE",
        "signals": {
            "baseline_pf": {"value": 1.05, "verdict": "FRAGILE"},
            "entry_delay": {"value": 0.66, "verdict": "FRAGILE"},
        },
    }))

    out = tmp_path / "retrospective.json"
    run_retrospective_calibration(
        alpaca_api=fake_api, bot_log_path=log,
        reports_dir=reports, output_path=out, window_months=12,
    )
    data = json.loads(out.read_text())
    # The trade was attributed to S4_InsideDayBreakout, signals from s4_inside_day_breakout
    s4 = next((r for r in data["per_strategy"] if r["strategy"] == "S4_InsideDayBreakout"), None)
    assert s4 is not None, f"no S4 row in {data['per_strategy']}"
    # Naming-bridge worked: signals_fragile pulled from snake_case report
    assert "baseline_pf" in s4["signals_fragile"]
    assert "entry_delay" in s4["signals_fragile"]
    # Hit rates should now show entry_delay + baseline_pf
    seed = data["per_signal_seed"]
    assert "entry_delay" in seed
    assert seed["entry_delay"]["fragile_fires"] == 1
