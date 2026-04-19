"""Canary health check harness. See reports/canary_suite_readme.md for usage."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from tradelab.canaries import LeakCanary, OverfitCanary, RandCanary, SurvivorCanary
from tradelab.canaries.survivor_canary import CURATED_UNIVERSE as SURVIVOR_UNIVERSE
from tradelab.engines.backtest import run_backtest


EXPECTED_BANDS = {
    "rand_canary":     {"pf_min": 0.70, "pf_max": 1.30,
                         "comment": "Random entries should cluster PF near 1.0."},
    "overfit_canary":  {"comment": "Default params are noisy; run Optuna + WF for the real test."},
    "leak_canary":     {"pf_min": 3.0,
                         "comment": "With shift=0 the leak produces absurd PF. Entry-delay test is the real check."},
    "survivor_canary": {"pf_min": 1.2,
                         "comment": "Golden cross on curated winners aggregates well. LOSO is the real check."},
}


@dataclass
class CanaryResult:
    name: str
    trades: int
    profit_factor: float
    sharpe: float
    win_rate: float
    max_dd: float
    notes: list[str] = field(default_factory=list)
    ok: bool = True


@dataclass
class CanaryHealthReport:
    results: list[CanaryResult] = field(default_factory=list)

    @property
    def all_ok(self) -> bool:
        return all(r.ok for r in self.results)

    def summary(self) -> str:
        lines = ["=" * 72, "CANARY HEALTH CHECK", "=" * 72]
        for r in self.results:
            status = "OK " if r.ok else "!! "
            lines.append(
                f"{status} {r.name:<18}  Tr={r.trades:>4}  PF={r.profit_factor:>5.2f}  "
                f"Sh={r.sharpe:>5.2f}  WR={r.win_rate:>5.1f}%  DD={r.max_dd:>5.1f}%"
            )
            for note in r.notes:
                lines.append(f"      - {note}")
        lines.append("=" * 72)
        lines.append("STATUS: ALL OK" if self.all_ok
                     else "STATUS: REVIEW REQUIRED — one or more canaries outside expected bands")
        lines.append("=" * 72)
        return "\n".join(lines)


def _run_one(canary, data, spy_close, subset=None):
    notes = []
    if subset is not None:
        available = [s for s in subset if s in data]
        missing = [s for s in subset if s not in data]
        if missing:
            notes.append(f"Symbols missing: {missing}")
        if not available:
            return CanaryResult(name=canary.name, trades=0, profit_factor=0.0, sharpe=0.0,
                                 win_rate=0.0, max_dd=0.0, notes=notes + ["No symbols; not run."], ok=False)
        canary_data = {s: data[s] for s in available}
    else:
        canary_data = data

    result = run_backtest(canary, canary_data, spy_close=spy_close)
    m = result.metrics
    band = EXPECTED_BANDS.get(canary.name, {})
    ok = True
    if "pf_min" in band and m.profit_factor < band["pf_min"]:
        notes.append(f"PF {m.profit_factor:.2f} below min {band['pf_min']}.")
        ok = False
    if "pf_max" in band and m.profit_factor > band["pf_max"]:
        notes.append(f"PF {m.profit_factor:.2f} above max {band['pf_max']}.")
        ok = False
    if "comment" in band:
        notes.append(band["comment"])

    return CanaryResult(
        name=canary.name, trades=m.total_trades, profit_factor=m.profit_factor,
        sharpe=m.sharpe_ratio, win_rate=m.win_rate, max_dd=m.max_drawdown_pct,
        notes=notes, ok=ok,
    )


def run_canary_health_check(data, spy_close=None) -> CanaryHealthReport:
    report = CanaryHealthReport()
    report.results.append(_run_one(RandCanary(), data, spy_close))
    report.results.append(_run_one(OverfitCanary(), data, spy_close))
    report.results.append(_run_one(LeakCanary(), data, spy_close))
    report.results.append(_run_one(SurvivorCanary(), data, spy_close, subset=SURVIVOR_UNIVERSE))
    return report


if __name__ == "__main__":
    print("Canary health check harness — import and call run_canary_health_check(data, spy_close=spy).")
