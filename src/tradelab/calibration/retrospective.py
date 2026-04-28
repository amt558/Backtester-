"""Slice -1 retrospective: compares 12mo of live trades vs predicted verdicts.

CAVEAT: outputs carry code_divergence_caveat=True until §1 confound resolves.
Per recon §1, deployed bot loads strategies by bare module name — live PnL is
from possibly-different code than what tradelab scored. Future calibrations
post-Slice-0.5 will have native attribution via client_order_id.
"""
from __future__ import annotations
import json
import re as _re_norm
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .alpaca_trade_history import fetch_filled_orders, pair_buy_sell_into_trades
from .bot_log_attribution import parse_position_added_lines, attribute_trade


def normalize_strategy_name(name: str) -> str:
    """Convert bot's CamelCase strategy name to tradelab's snake_case form.

    Bot.log uses 'S2_PocketPivot', tradelab reports use 's2_pocket_pivot'.
    Without normalization, fragile_by_strategy lookup misses.

    Examples:
        'S2_PocketPivot' -> 's2_pocket_pivot'
        'S12_MomentumAcceleration' -> 's12_momentum_acceleration'
        'S7_RDZMomentum' -> 's7_rdz_momentum'    (multi-cap acronym kept together)
        'S10_RSNewHighs' -> 's10_rs_new_highs'
        's4_inside_day_breakout' -> 's4_inside_day_breakout'   (idempotent)
    """
    # Step 1: split runs-of-caps before a Cap+lower (RDZMomentum → RDZ_Momentum)
    s = _re_norm.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', name)
    # Step 2: split lowercase/digit before uppercase (PocketPivot → Pocket_Pivot)
    s = _re_norm.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s)
    return s.lower()


@dataclass
class RetrospectiveResult:
    code_divergence_caveat: bool = True
    per_strategy: list = field(default_factory=list)
    per_signal_seed: dict = field(default_factory=dict)


def load_predicted_verdict(report_path: Path) -> dict:
    """Read robustness_result.json; return the raw dict.

    Real shape (2026-04-28):
        {
          "strategy": "s2_pocket_pivot",
          "dsr_probability": 0.42,
          "monte_carlo": {...}, "param_landscape": {...},
          "entry_delay": {...}, "loso": {...}, "noise_injection": {...},
          "verdict": {
            "verdict": "ROBUST" | "INCONCLUSIVE" | "FRAGILE",
            "signals": [
              {"name": "baseline_pf", "outcome": "inconclusive", "reason": "..."},
              ...
            ]
          }
        }
    """
    with open(report_path) as f:
        return json.load(f)


def extract_fragile_signal_names(report: dict) -> list[str]:
    """From a robustness report, return the names of signals with outcome='fragile'.

    Handles the real on-disk shape (verdict is a dict containing signals list).
    Backwards-compatible with the legacy fixture shape (signals dict with 'verdict' key).
    """
    # Real shape: verdict.signals is a list of {name, outcome, reason}
    verdict_block = report.get("verdict")
    if isinstance(verdict_block, dict) and isinstance(verdict_block.get("signals"), list):
        return [
            s["name"] for s in verdict_block["signals"]
            if isinstance(s, dict) and s.get("outcome") == "fragile"
        ]
    # Legacy/fixture shape: signals is a dict {name: {verdict: "FRAGILE"}}
    legacy_signals = report.get("signals")
    if isinstance(legacy_signals, dict):
        return [
            name for name, sig in legacy_signals.items()
            if isinstance(sig, dict) and sig.get("verdict") == "FRAGILE"
        ]
    return []


def compute_per_strategy_outcomes(attributed_trades: list[dict]) -> list[dict]:
    """Group attributed trades by strategy; bucket unattributed separately.

    Each input row needs `strategy` (or None) and `pnl`.
    Output rows: {strategy, n_trades, total_pnl, live_pf, wins_total, losses_total}.
    """
    pnls_by_strat: dict[str, list[float]] = defaultdict(list)
    for t in attributed_trades:
        key = t.get("strategy") or "unattributed"
        pnls_by_strat[key].append(t["pnl"])

    out = []
    for strategy, pnls in pnls_by_strat.items():
        wins = sum(p for p in pnls if p > 0)
        losses = -sum(p for p in pnls if p < 0)
        live_pf = (wins / losses) if losses > 0 else float("inf")
        out.append({
            "strategy": strategy, "n_trades": len(pnls),
            "total_pnl": sum(pnls), "live_pf": live_pf,
            "wins_total": wins, "losses_total": losses,
        })
    return out


def _classify_hit_rate(hit_rate: Optional[float], n: int) -> str:
    if n < 3:
        return "insufficient sample"
    if hit_rate is None:
        return "insufficient sample"
    if hit_rate >= 0.5:
        return "predictive"
    if hit_rate >= 0.25:
        return "questionable"
    return "noisy"


def compute_per_signal_seed_hit_rates(
    strategies: list[dict],
    fail_threshold: float = 1.0,
) -> dict[str, dict]:
    """Per-signal: of the strategies where this signal said FRAGILE and were
    deployed anyway, how many lost money in production?

    `strategies` rows: {strategy, live_pf, signals_fragile (list of names)}.
    """
    per_signal: dict[str, dict] = {}
    for s in strategies:
        failed = s["live_pf"] < fail_threshold
        for sig_name in s.get("signals_fragile", []):
            row = per_signal.setdefault(sig_name, {
                "fragile_fires": 0, "accepted_despite": 0, "failed_in_prod": 0,
            })
            row["fragile_fires"] += 1
            row["accepted_despite"] += 1
            if failed:
                row["failed_in_prod"] += 1
    for sig_name, row in per_signal.items():
        n = row["accepted_despite"]
        row["hit_rate"] = (row["failed_in_prod"] / n) if n >= 3 else None
        row["read"] = _classify_hit_rate(row["hit_rate"], n)
    return per_signal


def run_retrospective_calibration(
    *, alpaca_api, bot_log_path: Path,
    reports_dir: Path, output_path: Path, window_months: int = 12,
) -> RetrospectiveResult:
    after_iso = (datetime.now(timezone.utc) - timedelta(days=window_months * 30)).isoformat()

    # 1. Pull Alpaca fills
    raw_orders = fetch_filled_orders(alpaca_api, after_iso=after_iso)

    # 2. Pair into round-trip trades
    trades = pair_buy_sell_into_trades(raw_orders)

    # 3. Attribute via bot.log (gracefully handle missing log)
    log_entries: list[dict] = []
    if bot_log_path.exists():
        log_entries = parse_position_added_lines(bot_log_path)

    attributed = []
    attributed_count = unattributed_count = 0
    for trade in trades:
        strategy = attribute_trade(trade, log_entries) if log_entries else None
        attributed.append({**trade, "strategy": strategy})
        if strategy:
            attributed_count += 1
        else:
            unattributed_count += 1

    # 4. Per-strategy live outcomes
    per_strategy = compute_per_strategy_outcomes(attributed)

    # 5. Predicted verdicts per strategy
    fragile_by_strategy: dict[str, list[str]] = {}
    candidates = list(reports_dir.glob("**/robustness_result.json"))
    single_fixture = reports_dir / "robustness_sample.json"
    if single_fixture.exists():
        candidates.append(single_fixture)
    for report_file in candidates:
        try:
            rv = load_predicted_verdict(report_file)
        except (OSError, json.JSONDecodeError):
            continue
        strategy = rv.get("strategy")
        if not strategy:
            continue
        fragile_by_strategy[strategy] = extract_fragile_signal_names(rv)

    enriched = []
    for row in per_strategy:
        raw_name = row["strategy"]
        sigs = (
            fragile_by_strategy.get(raw_name)
            or fragile_by_strategy.get(normalize_strategy_name(raw_name))
            or []
        )
        enriched.append({**row, "signals_fragile": sigs})
    per_signal = compute_per_signal_seed_hit_rates(enriched)

    total = attributed_count + unattributed_count
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_months": window_months,
        "code_divergence_caveat": True,
        "caveat_text": (
            "Outputs compare tradelab verdicts to live PnL of (possibly) "
            "different code per recon §1. Resolve before drawing strong conclusions."
        ),
        "attribution_quality": {
            "attributed_count": attributed_count,
            "unattributed_count": unattributed_count,
            "attribution_pct": (attributed_count / total) if total else 0.0,
            "note": (
                "Future fills will have native client_order_id attribution per "
                "Slice -0.5. Historical fills rely on bot.log Position added parsing."
            ),
        },
        "per_strategy": enriched,
        "per_signal_seed": per_signal,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2, default=str))
    return RetrospectiveResult(
        code_divergence_caveat=True,
        per_strategy=enriched,
        per_signal_seed=per_signal,
    )
