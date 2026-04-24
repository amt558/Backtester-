"""Orchestrator: CSV-derived trades → verdict + report folder + audit row.

The single entry point that callers (CLI, dashboard backend) use:

    parsed = parse_tv_trades_csv(csv_text, symbol="AMZN")
    out = score_trades(parsed, strategy_name="viprasol-amzn-v1", symbol="AMZN")
    folder, run_id = write_report_folder(out, base_name="viprasol-amzn-v1",
                                         pine_source=None, csv_text=csv_text)

Degraded relative to `tradelab run`:
  - no Optuna / WF / param landscape / entry delay / noise / LOSO
  - DSR uses n_trials=1
  - dashboard.html still renders, but several tabs will be empty
  - regime breakdown empty (no SPY data)
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from .audit import record_run as _audit_record_run
from .audit.history import DEFAULT_DB_PATH as _DEFAULT_DB_PATH
from .dashboard import build_dashboard
from .determinism import hash_config
from .engines._diagnostics import compute_monthly_pnl, metrics_from_trades
from .engines.dsr import deflated_sharpe_ratio
from .io.tv_csv import ParsedTradesCSV
from .reporting import generate_executive_report
from .results import BacktestResult
from .robustness.monte_carlo import MonteCarloResult, run_monte_carlo
from .robustness.verdict import VerdictResult, compute_verdict


@dataclass
class CSVScoringOutput:
    backtest_result: BacktestResult
    dsr_probability: Optional[float]
    monte_carlo: Optional[MonteCarloResult]
    verdict: VerdictResult


def build_backtest_result_from_trades(
    parsed: ParsedTradesCSV,
    *,
    strategy_name: str,
    symbol: str,
    timeframe: str = "1D",
    starting_equity: float = 100_000.0,
) -> BacktestResult:
    metrics = metrics_from_trades(parsed.trades, starting_equity=starting_equity)

    # Equity curve, one point per trade exit (good enough for QuantStats /
    # DSR resampling — shorter than a daily-bar curve but sufficient).
    equity = starting_equity
    curve: list[dict] = []
    for t in parsed.trades:
        equity += t.pnl
        curve.append({"date": t.exit_date, "equity": round(equity, 2)})

    # Annualize using calendar days in the window.
    try:
        d0 = datetime.strptime(parsed.start_date, "%Y-%m-%d")
        d1 = datetime.strptime(parsed.end_date, "%Y-%m-%d")
        days = max((d1 - d0).days, 1)
        if metrics.final_equity > 0 and starting_equity > 0:
            growth = metrics.final_equity / starting_equity
            ann = (growth ** (365.0 / days) - 1.0) * 100.0
            metrics = metrics.model_copy(update={"annual_return": round(ann, 3)})
    except (ValueError, OverflowError):
        pass

    monthly = compute_monthly_pnl(parsed.trades)

    return BacktestResult(
        strategy=strategy_name,
        symbol=symbol,
        timeframe=timeframe,
        start_date=parsed.start_date,
        end_date=parsed.end_date,
        params={},
        metrics=metrics,
        trades=list(parsed.trades),
        equity_curve=curve,
        regime_breakdown={},
        monthly_pnl=monthly,
    )


def score_trades(
    parsed: ParsedTradesCSV,
    *,
    strategy_name: str,
    symbol: str,
    timeframe: str = "1D",
    starting_equity: float = 100_000.0,
    mc_simulations: int = 500,
) -> CSVScoringOutput:
    bt = build_backtest_result_from_trades(
        parsed, strategy_name=strategy_name, symbol=symbol,
        timeframe=timeframe, starting_equity=starting_equity,
    )

    # DSR on the trade-exit equity curve. Returns NaN for very short series.
    dsr_p: Optional[float] = None
    returns = bt.daily_returns()
    if returns is not None and len(returns) >= 2:
        p = deflated_sharpe_ratio(returns.values, n_trials=1)
        if not math.isnan(p):
            dsr_p = float(p)

    # MC: shuffles trade pnls; needs trades but no bar data.
    mc = None
    if bt.trades:
        try:
            mc = run_monte_carlo(bt, n_simulations=mc_simulations,
                                 starting_equity=starting_equity)
        except Exception:
            mc = None

    verdict = compute_verdict(bt, dsr=dsr_p, mc=mc)

    return CSVScoringOutput(
        backtest_result=bt,
        dsr_probability=dsr_p,
        monte_carlo=mc,
        verdict=verdict,
    )


def _safe_dashboard(out: CSVScoringOutput, out_dir: Path) -> Optional[Path]:
    """Build dashboard.html. Tolerate failures so the rest of the report survives."""
    try:
        return build_dashboard(
            out.backtest_result,
            optuna_result=None, wf_result=None,
            universe=None,
            out_dir=out_dir,
            robustness_result=None,
        )
    except Exception as exc:
        print(f"[csv_scoring] dashboard build skipped: {exc}", file=sys.stderr)
        return None


def write_report_folder(
    out: CSVScoringOutput,
    *,
    base_name: str,
    out_root: Path = Path("reports"),
    pine_source: Optional[str] = None,
    csv_text: Optional[str] = None,
    record_audit: bool = True,
    db_path: Path = _DEFAULT_DB_PATH,
) -> tuple[Path, Optional[str]]:
    """Persist a full report folder under <out_root>/<base_name>_<timestamp>/.

    Returns (folder_path, audit_run_id). audit_run_id is the audit DB row id
    when record_audit=True, else None.

    Files written:
      executive_report.md       — same renderer as `tradelab run`
      dashboard.html            — best-effort; missing tabs render as 'no data'
      backtest_result.json      — pydantic dump for `tradelab compare` parity
      tv_trades.csv             — verbatim copy of the imported CSV
      strategy.pine             — Pine source if caller provided one

    Audit row is written when record_audit=True (default).
    """
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    folder = Path(out_root) / f"{base_name}_{ts}"
    folder.mkdir(parents=True, exist_ok=True)

    # Override strategy name in the BacktestResult so the report header uses
    # the user-supplied base name rather than whatever was passed to score_trades.
    bt = out.backtest_result.model_copy(update={"strategy": base_name})

    report_path = generate_executive_report(
        bt, optuna_result=None, wf_result=None,
        universe=None, out_dir=folder, robustness_result=None,
    )

    dashboard_path = _safe_dashboard(
        CSVScoringOutput(
            backtest_result=bt,
            dsr_probability=out.dsr_probability,
            monte_carlo=out.monte_carlo,
            verdict=out.verdict,
        ),
        folder,
    )

    (folder / "backtest_result.json").write_text(
        bt.model_dump_json(indent=2), encoding="utf-8",
    )

    if csv_text is not None:
        (folder / "tv_trades.csv").write_text(csv_text, encoding="utf-8")
    if pine_source is not None:
        (folder / "strategy.pine").write_text(pine_source, encoding="utf-8")

    audit_run_id: Optional[str] = None
    if record_audit:
        audit_run_id = _audit_record_run(
            strategy_name=base_name,
            verdict=out.verdict.verdict,
            dsr_probability=out.dsr_probability,
            input_data_hash=None,            # no OHLCV; CSV is the source
            config_hash=hash_config({
                "csv_source": "tv_strategy_tester",
                "symbol": bt.symbol,
                "timeframe": bt.timeframe,
                "starting_equity": round(bt.metrics.final_equity - bt.metrics.net_pnl, 2),
                "n_trades": bt.metrics.total_trades,
            }),
            report_card_markdown=report_path.read_text(encoding="utf-8"),
            report_card_html_path=str(dashboard_path) if dashboard_path else None,
            db_path=db_path,
        )

    return folder, audit_run_id
