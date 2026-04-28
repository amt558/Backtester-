"""Slice -1: tradelab retrospective-calibration subcommand.

Pulls 12mo of fills from Alpaca paper account, attributes via bot.log Position
added lines, joins to predicted verdicts from reports/, computes per-signal
seed hit rates. Output JSON carries §1 code-divergence caveat + attribution_quality.

Per memory `reference_alpaca_config_location.md`: api_key/secret_key live in
gitignored alpaca_config.json, NOT env vars. Per memory
`reference_alpaca_trade_history_source.md`: trades.csv does not exist; pull
from Alpaca + parse bot.log for historical attribution.
"""
from __future__ import annotations
import json
from pathlib import Path

import typer
from rich.console import Console

from .calibration.retrospective import run_retrospective_calibration

console = Console()


def _build_alpaca_client(config_path: Path, paper: bool):
    """Construct an Alpaca REST client from gitignored config.

    Config shape: {"alpaca": {"api_key": ..., "secret_key": ..., "base_url": ..., "paper_trading": bool}, ...}.
    Uses utf-8-sig because the file is PowerShell-written with BOM
    (per memory reference_powershell_utf8_bom.md).

    Lazy-imports alpaca_trade_api so the CLI doesn't fail to load when the SDK
    is unavailable (e.g. in test environments).
    """
    cfg = json.loads(config_path.read_text(encoding="utf-8-sig"))
    alpaca_cfg = cfg["alpaca"]
    import alpaca_trade_api as tradeapi
    base_url = (
        "https://paper-api.alpaca.markets" if paper
        else "https://api.alpaca.markets"
    )
    return tradeapi.REST(
        key_id=alpaca_cfg["api_key"],
        secret_key=alpaca_cfg["secret_key"],
        base_url=base_url,
    )


def retrospective_calibration(
    alpaca_config: Path = typer.Option(
        ..., "--alpaca-config",
        help="Path to gitignored alpaca_config.json with api_key + secret_key.",
        exists=True, file_okay=True, dir_okay=False, readable=True,
    ),
    bot_log: Path = typer.Option(
        ..., "--bot-log",
        help="Path to alpaca_trading_bot.log (parsed for Position added lines).",
    ),
    reports: Path = typer.Option(
        ..., "--reports",
        help="Path to tradelab reports/ directory (read robustness_result.json files).",
        exists=True, file_okay=False, dir_okay=True, readable=True,
    ),
    output: Path = typer.Option(
        ..., "--output",
        help="Output JSON file (will overwrite if exists).",
    ),
    window_months: int = typer.Option(
        12, "--window-months", help="Lookback window in months (default 12).",
    ),
    paper: bool = typer.Option(
        True, "--paper/--live",
        help="Use Alpaca paper account (default) or live.",
    ),
):
    """Run Slice -1 retrospective calibration. §1 caveat applies to outputs."""
    api = _build_alpaca_client(alpaca_config, paper=paper)
    run_retrospective_calibration(
        alpaca_api=api, bot_log_path=bot_log,
        reports_dir=reports, output_path=output, window_months=window_months,
    )
    console.print(f"[green]Retrospective written to[/green] {output}")
    console.print("[yellow]CAVEAT:[/yellow] outputs carry §1 code-divergence caveat + attribution_quality field")
