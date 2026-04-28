"""Slice -1: tradelab retrospective-calibration subcommand.

Pulls 12mo of fills from Alpaca paper account, attributes via bot.log Position
added lines, joins to predicted verdicts from reports/, computes per-signal
seed hit rates. Output JSON carries §1 code-divergence caveat + attribution_quality.

Uses alpaca-py (the maintained SDK) via an adapter that exposes the small subset
of the old alpaca-trade-api surface that fetch_filled_orders expects. This keeps
the existing fetcher tests (which mock the old SDK shape) working without
introducing a deprecated dep.

Per memory `reference_alpaca_config_location.md`: api_key/secret_key live in
gitignored alpaca_config.json under the "alpaca" key, NOT env vars.
Per memory `reference_powershell_utf8_bom.md`: alpaca_config.json has UTF-8 BOM.
Per memory `reference_alpaca_trade_history_source.md`: trades.csv does not exist;
pull from Alpaca + parse bot.log for historical attribution.
"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console

from .calibration.retrospective import run_retrospective_calibration

console = Console()


class _AlpacaPyListOrdersAdapter:
    """Adapter exposing the small list_orders subset that fetch_filled_orders uses.

    fetch_filled_orders calls api.list_orders(status=..., after=..., until=...,
    limit=..., direction=...) and expects iterable of dicts with keys:
    id, symbol, qty, side, filled_qty, filled_avg_price, filled_at,
    client_order_id, status.

    This adapter implements that surface using alpaca-py's TradingClient.
    """

    def __init__(self, trading_client):
        self._client = trading_client

    def list_orders(self, *, status, after, until=None, limit=500, direction="desc"):
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus

        after_dt = datetime.fromisoformat(after.replace("Z", "+00:00"))
        until_dt = (
            datetime.fromisoformat(until.replace("Z", "+00:00"))
            if until else None
        )

        # alpaca-py's QueryOrderStatus.CLOSED includes filled + canceled + expired.
        # We post-filter to status="filled" below to match old SDK behaviour.
        req_kwargs = dict(
            status=QueryOrderStatus.CLOSED,
            after=after_dt,
            limit=limit,
            direction=direction,
            nested=False,
        )
        if until_dt is not None:
            req_kwargs["until"] = until_dt
        req = GetOrdersRequest(**req_kwargs)

        orders = self._client.get_orders(filter=req)

        out: list[dict] = []
        for o in orders:
            o_status_raw = o.status.value if hasattr(o.status, "value") else str(o.status)
            if o_status_raw != "filled":
                continue
            out.append({
                "id": str(o.id),
                "symbol": o.symbol,
                "qty": str(o.qty),
                "side": o.side.value if hasattr(o.side, "value") else str(o.side),
                "filled_qty": str(o.filled_qty) if o.filled_qty is not None else "0",
                "filled_avg_price": (
                    str(o.filled_avg_price) if o.filled_avg_price is not None else None
                ),
                "filled_at": o.filled_at.isoformat() if o.filled_at else None,
                "client_order_id": o.client_order_id,
                "status": "filled",
            })
        return out


def _build_alpaca_client(config_path: Path, paper: bool):
    """Construct an alpaca-py TradingClient + the list_orders adapter.

    Reads creds from gitignored alpaca_config.json (UTF-8 BOM tolerated, nested
    "alpaca" block).
    """
    cfg = json.loads(config_path.read_text(encoding="utf-8-sig"))
    alpaca_cfg = cfg["alpaca"]
    from alpaca.trading.client import TradingClient
    client = TradingClient(
        alpaca_cfg["api_key"],
        alpaca_cfg["secret_key"],
        paper=paper,
    )
    return _AlpacaPyListOrdersAdapter(client)


def retrospective_calibration(
    alpaca_config: Path = typer.Option(
        ..., "--alpaca-config",
        help="Path to gitignored alpaca_config.json (nested {alpaca: {api_key, secret_key}}).",
        exists=True, file_okay=True, dir_okay=False, readable=True,
    ),
    bot_log: Path = typer.Option(
        ..., "--bot-log",
        help="Path to alpaca bot log (parsed for Position added lines).",
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
    console.print(
        "[yellow]CAVEAT:[/yellow] outputs carry §1 code-divergence caveat + "
        "attribution_quality field"
    )
