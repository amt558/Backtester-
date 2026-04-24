"""Dashboard-side CSV-scoring + card-approval flow (Option H Session 3a).

score_csv:   parse + score + write report folder + record audit row.
             Returns a JSON-serializable dict.
accept_scored (Task 4):
             copy Pine/CSV from report folder to pine_archive/{card_id}/,
             write verdict.json, create card in registry (disabled).

Both are pure functions. No HTTP, no global singletons. Handlers in
web/handlers.py validate request shape and map exceptions to HTTP codes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from tradelab.audit.history import DEFAULT_DB_PATH as _DEFAULT_DB_PATH
from tradelab.csv_scoring import score_trades, write_report_folder
from tradelab.io.tv_csv import parse_tv_trades_csv


def score_csv(
    *,
    csv_text: str,
    pine_source: Optional[str],
    symbol: str,
    base_name: str,
    timeframe: str,
    reports_root: Path = Path("reports"),
    db_path: Path = _DEFAULT_DB_PATH,
) -> dict:
    """Parse TV CSV, score it, write report folder, record audit row.

    Raises TVCSVParseError on bad CSV, ValueError on 0 closed trades.
    Other exceptions propagate.
    """
    parsed = parse_tv_trades_csv(csv_text, symbol=symbol)
    if not parsed.trades:
        raise ValueError("csv contained no closed trades")

    out = score_trades(parsed, strategy_name=base_name, symbol=symbol,
                       timeframe=timeframe)

    folder, run_id = write_report_folder(
        out, base_name=base_name,
        out_root=reports_root,
        pine_source=pine_source,
        csv_text=csv_text,
        record_audit=True,
        db_path=db_path,
    )

    bt = out.backtest_result
    m = bt.metrics
    return {
        "verdict":          out.verdict.verdict,
        "dsr_probability":  out.dsr_probability,
        "scoring_run_id":   run_id,
        "report_folder":    str(folder).replace("\\", "/"),
        "n_trades":         m.total_trades,
        "start_date":       bt.start_date,
        "end_date":         bt.end_date,
        "metrics": {
            "net_pnl":          m.net_pnl,
            "profit_factor":    m.profit_factor,
            "total_trades":     m.total_trades,
            "win_rate":         m.win_rate,
            "max_drawdown_pct": m.max_drawdown_pct,
            "annual_return":    m.annual_return,
            "sharpe_ratio":     m.sharpe_ratio,
        },
    }
