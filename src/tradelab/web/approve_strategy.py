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

import re
from pathlib import Path
from typing import Optional

from tradelab.audit.history import DEFAULT_DB_PATH as _DEFAULT_DB_PATH
from tradelab.csv_scoring import score_trades, write_report_folder
from tradelab.io.tv_csv import parse_tv_trades_csv


# ─── Pine source linter (UPGRADES #2-A) ──────────────────────────────
#
# Catches the common foot-gun: a Pine script with optimistic execution
# flags backtests with fills the broker can't replicate live, so the
# verdict / DSR look better than reality. Cheap regex sweep — no Pine
# parser. Each rule returns a {flag, level, message} dict for the UI.

_PINE_LINT_RULES: list[tuple[str, "re.Pattern[str]", str, str]] = [
    (
        "process_orders_on_close",
        re.compile(r"process_orders_on_close\s*=\s*true", re.IGNORECASE),
        "warning",
        "process_orders_on_close=true fills at the signal bar's close — "
        "the broker can't replicate this. Backtest PF/DSR will overstate.",
    ),
    (
        "calc_on_every_tick",
        re.compile(r"calc_on_every_tick\s*=\s*true", re.IGNORECASE),
        "warning",
        "calc_on_every_tick=true makes intrabar evaluation optimistic. "
        "Real-time signals will fire at different prices than the backtest.",
    ),
    (
        "lookahead_on",
        re.compile(r"lookahead\s*=\s*barmerge\.lookahead_on", re.IGNORECASE),
        "error",
        "lookahead=barmerge.lookahead_on peeks future bars. Backtest is "
        "look-ahead biased; live performance will diverge sharply.",
    ),
    (
        "calc_on_order_fills",
        re.compile(r"calc_on_order_fills\s*=\s*true", re.IGNORECASE),
        "warning",
        "calc_on_order_fills=true triggers extra evaluations on fills, "
        "potentially adding signals the broker won't see.",
    ),
]


def lint_pine_source(pine_source: Optional[str]) -> list[dict]:
    """Scan Pine v5/v6 source for optimistic execution flags.

    Returns a list of {flag, level, message} dicts; empty if clean or no
    source provided. Caller (score endpoint) surfaces them to the UI.
    """
    if not pine_source:
        return []
    findings: list[dict] = []
    for flag, pattern, level, message in _PINE_LINT_RULES:
        if pattern.search(pine_source):
            findings.append({"flag": flag, "level": level, "message": message})
    return findings


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

    Raises TVCSVParseError on bad CSV (including when the CSV has no
    closed trades — the parser guards this).
    Other exceptions propagate.
    """
    parsed = parse_tv_trades_csv(csv_text, symbol=symbol)

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
        "pine_lints": lint_pine_source(pine_source),
    }


import json as _json
import secrets as _secrets
import shutil as _shutil
from datetime import datetime as _datetime, timezone as _timezone

from tradelab.live.cards import CardRegistry as _CardRegistry


def accept_scored(
    *,
    base_name: str,
    symbol: str,
    timeframe: str,
    report_folder: str,
    verdict: str,
    dsr_probability: Optional[float],
    scoring_run_id: str,
    registry: _CardRegistry,
    pine_archive_root: Path = Path("pine_archive"),
    reports_root: Path = Path("reports"),
) -> dict:
    """Promote a scored report folder to an immutable card + pine_archive record.

    Raises:
      FileNotFoundError: report_folder doesn't exist or is outside reports_root.
      ValueError: report_folder has no strategy.pine.
      FileExistsError: target pine_archive dir already exists.
      CardExistsError: registry refuses duplicate (caller re-computes version).
    """
    # Paranoid path check — report_folder must live under reports_root.
    rf = Path(report_folder).resolve()
    rr = Path(reports_root).resolve()
    try:
        rf.relative_to(rr)
    except ValueError as exc:
        raise FileNotFoundError(
            f"report folder {rf} is not under reports_root {rr}"
        ) from exc
    if not rf.exists() or not rf.is_dir():
        raise FileNotFoundError(f"report folder not found: {rf}")

    pine_src = rf / "strategy.pine"
    csv_src = rf / "tv_trades.csv"
    if not pine_src.exists():
        raise ValueError(
            "report folder has no strategy.pine — re-score with Pine source"
        )

    version = registry.next_version_for(base_name)
    card_id = f"{base_name}-v{version}"
    secret = _secrets.token_urlsafe(24)  # 32-char url-safe

    archive_dir = Path(pine_archive_root) / card_id
    # exist_ok=False: caller sees FileExistsError on stale dir -> HTTP 409
    archive_dir.mkdir(parents=True, exist_ok=False)

    try:
        _shutil.copy2(pine_src, archive_dir / "strategy.pine")
        if csv_src.exists():
            _shutil.copy2(csv_src, archive_dir / "tv_trades.csv")

        created_at = _datetime.now(_timezone.utc).isoformat(timespec="seconds")
        verdict_snapshot = {
            "card_id":          card_id,
            "base_name":        base_name,
            "version":          version,
            "symbol":           symbol,
            "timeframe":        timeframe,
            "verdict":          verdict,
            "dsr_probability":  dsr_probability,
            "scoring_run_id":   scoring_run_id,
            "created_at":       created_at,
            "report_folder":    str(rf).replace("\\", "/"),
        }
        (archive_dir / "verdict.json").write_text(
            _json.dumps(verdict_snapshot, indent=2), encoding="utf-8",
        )

        card = {
            "card_id":           card_id,
            "secret":            secret,
            "symbol":            symbol,
            "status":            "disabled",
            "quantity":          None,
            "created_at":        created_at,
            "base_name":         base_name,
            "version":           version,
            "timeframe":         timeframe,
            "verdict":           verdict,
            "dsr_probability":   dsr_probability,
            "report_folder":     str(rf).replace("\\", "/"),
            "pine_archive_path": str(archive_dir).replace("\\", "/"),
            "scoring_run_id":    scoring_run_id,
        }
        registry.create(card_id, card)
    except Exception:
        # Rollback the pine archive dir so a retry can re-create it cleanly.
        _shutil.rmtree(archive_dir, ignore_errors=True)
        raise

    return {
        "card_id":           card_id,
        "secret":            secret,
        "pine_archive_path": str(archive_dir).replace("\\", "/"),
    }
