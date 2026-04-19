"""
`tradelab canary-health` — one-page aggregator of the 4 canary strategies.

Pulls the most recent audit-trail row for each registered canary and renders
a single HTML card per canary with its verdict + key metrics. If any canary
is missing (never run) or shows a ROBUST verdict (which would indicate the
tool itself is broken), the aggregator highlights it.

Usage:
    tradelab canary-health
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from .audit import list_runs


CANARY_NAMES = ["rand_canary", "overfit_canary", "leak_canary", "survivor_canary"]

EXPECTED_VERDICT = {
    # Any of these verdicts is acceptable for this canary. Anything NOT in the
    # set is a red flag; specifically a ROBUST verdict on any canary means
    # the tool is broken.
    "rand_canary":     {"FRAGILE", "INCONCLUSIVE"},
    "overfit_canary":  {"FRAGILE", "INCONCLUSIVE"},
    "leak_canary":     {"FRAGILE", "INCONCLUSIVE"},
    "survivor_canary": {"FRAGILE", "INCONCLUSIVE"},
}

console = Console()


_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>tradelab canary health</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 0; background: #fafafa; color: #222; }}
.header {{ padding: 20px 30px; background: #1a1a1a; color: #fafafa; }}
.header h1 {{ margin: 0; font-size: 22px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; padding: 24px; }}
.card {{ background: white; border: 1px solid #e0e0e0; border-radius: 6px; padding: 16px 18px; }}
.card h2 {{ margin: 0 0 6px; font-size: 15px; color: #444; }}
.card .verdict {{ font-size: 20px; font-weight: 600; margin: 8px 0; }}
.card .meta {{ font-size: 12px; color: #888; }}
.card .flag {{ background: #ffe0e0; color: #933; border: 1px solid #f0a0a0;
               padding: 4px 8px; border-radius: 3px; font-size: 12px; display: inline-block; margin-top: 4px; }}
.ok {{ color: #2d9c3a; }}
.warn {{ color: #d6a02a; }}
.bad {{ color: #d0443e; }}
.footer {{ padding: 16px 30px; color: #888; font-size: 11px; border-top: 1px solid #e0e0e0; }}
</style>
</head>
<body>
<div class="header">
<h1>tradelab canary health</h1>
<div style="font-size:13px;opacity:0.8;margin-top:4px;">Generated {ts} — status: <b>{overall}</b></div>
</div>
<div class="grid">
{cards}
</div>
<div class="footer">
Canaries are deliberately-broken strategies. If ANY canary shows a ROBUST verdict,
the tool itself is broken — all recent strategy verdicts are suspect.
</div>
</body>
</html>
"""


_CARD = """<div class="card">
<h2>{name}</h2>
<div class="verdict {vclass}">{verdict}</div>
<div class="meta">{meta}</div>
{flag_html}
</div>
"""


def _verdict_class(verdict: str, name: str) -> str:
    """Color class for the canary verdict."""
    expected = EXPECTED_VERDICT.get(name, set())
    if verdict == "ROBUST":
        return "bad"       # tool-broken signal
    if verdict in expected:
        return "ok"
    if verdict == "INCONCLUSIVE":
        return "warn"
    return "warn"


def _render_canary_cards() -> tuple[str, str]:
    """Return (inner HTML, overall status)."""
    any_bad = False
    any_missing = False
    parts: list[str] = []
    for canary in CANARY_NAMES:
        runs = list_runs(strategy=canary, limit=1)
        if not runs:
            any_missing = True
            parts.append(_CARD.format(
                name=canary, verdict="never run", vclass="warn",
                meta="no history rows",
                flag_html='<div class="flag">Run once to populate</div>',
            ))
            continue
        r = runs[0]
        verdict = r.verdict or "UNDEFINED"
        vclass = _verdict_class(verdict, canary)
        flag = ""
        if verdict == "ROBUST":
            any_bad = True
            flag = '<div class="flag">CANARY PRODUCED ROBUST — tool is broken, halt evaluations</div>'
        dsr = f"{r.dsr_probability:.3f}" if r.dsr_probability is not None else "—"
        parts.append(_CARD.format(
            name=canary, verdict=verdict, vclass=vclass,
            meta=f"last run {r.timestamp_utc[:19]} · DSR {dsr} · run_id {r.run_id[:8]}",
            flag_html=flag,
        ))
    overall = ("BROKEN — see red flag" if any_bad
               else ("OK (some canaries never run)" if any_missing else "OK"))
    return "\n".join(parts), overall


def _build_html() -> str:
    cards, overall = _render_canary_cards()
    return _HTML.format(
        ts=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        overall=overall, cards=cards,
    )


def canary_health(
    out: Path = typer.Option(
        Path("reports") / "canary_health.html",
        help="Output HTML path",
    ),
    open_browser: bool = typer.Option(
        True, "--open/--no-open", help="Auto-open in browser",
    ),
) -> None:
    """Aggregate the latest verdict for each registered canary into one HTML."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_build_html(), encoding="utf-8")
    console.print(f"[green]Wrote[/green] {out}")

    # Also print a tight status line to the terminal
    cards_html, overall = _render_canary_cards()
    console.print(f"Overall: [bold]{overall}[/bold]")
    for canary in CANARY_NAMES:
        runs = list_runs(strategy=canary, limit=1)
        if not runs:
            console.print(f"  {canary:<18} [yellow]never run[/yellow]")
            continue
        r = runs[0]
        verdict = r.verdict or "UNDEFINED"
        colour = {"ROBUST": "red", "INCONCLUSIVE": "yellow",
                  "FRAGILE": "green"}.get(verdict, "white")
        console.print(f"  {canary:<18} [{colour}]{verdict}[/{colour}]  "
                      f"DSR={r.dsr_probability if r.dsr_probability is not None else '—'}  "
                      f"run={r.run_id[:8]}")

    if open_browser:
        try:
            typer.launch(str(out))
        except Exception:
            pass
