"""
`tradelab doctor` — environment + install sanity check.

Runs a sequence of self-tests and prints pass/fail per check. Non-zero
exit if any critical check fails. Useful right after install / on a new
machine / after a yfinance/TwelveData rotation.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Callable

import typer
from rich.console import Console

from .audit import list_runs
from .env import load_env


console = Console()


# Each check returns (ok, message). `critical` controls whether a fail
# triggers a non-zero exit.
def _ok(msg: str) -> tuple[bool, str]:
    return True, msg


def _fail(msg: str) -> tuple[bool, str]:
    return False, msg


def _check_python_version() -> tuple[bool, str]:
    v = sys.version_info
    if (v.major, v.minor) >= (3, 12):
        return _ok(f"Python {v.major}.{v.minor}.{v.micro}")
    return _fail(f"Python {v.major}.{v.minor}.{v.micro} (need 3.12+)")


REQUIRED = [
    "pandas", "numpy", "scipy", "pydantic", "optuna", "typer",
    "rich", "yaml", "plotly", "pyarrow", "requests",
]
OPTIONAL = ["yfinance", "quantstats"]


def _check_required_imports() -> tuple[bool, str]:
    missing = []
    for mod in REQUIRED:
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        return _fail(f"Missing required: {', '.join(missing)}")
    return _ok(f"All {len(REQUIRED)} required deps importable")


def _check_optional_imports() -> tuple[bool, str]:
    missing = []
    for mod in OPTIONAL:
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        return True, f"Optional missing (degraded): {', '.join(missing)}"
    return _ok(f"All {len(OPTIONAL)} optional deps importable")


def _check_twelvedata_key() -> tuple[bool, str]:
    load_env()
    if os.environ.get("TWELVEDATA_API_KEY"):
        return _ok("TWELVEDATA_API_KEY set")
    return _fail("TWELVEDATA_API_KEY not set — runs will refuse without --allow-yfinance-fallback")


def _check_config_loads() -> tuple[bool, str]:
    try:
        from .config import get_config
        cfg = get_config()
        return _ok(f"Config loaded from {cfg.config_path.name}")
    except Exception as e:
        return _fail(f"Config load failed: {e}")


def _check_strategies_resolvable() -> tuple[bool, str]:
    try:
        from .config import get_config
        from .registry import load_strategy_class
        cfg = get_config()
        names = list(cfg.strategies.keys())
        if not names:
            return _fail("No strategies registered in tradelab.yaml")
        broken = []
        for name in names:
            try:
                load_strategy_class(name)
            except Exception as e:
                broken.append(f"{name} ({type(e).__name__})")
        if broken:
            return _fail(f"Cannot import: {', '.join(broken)}")
        return _ok(f"All {len(names)} strategies importable")
    except Exception as e:
        return _fail(f"Registry probe failed: {e}")


def _check_cache_writable() -> tuple[bool, str]:
    cache_dir = Path(".cache") / "ohlcv" / "1D"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        probe = cache_dir / ".doctor_probe"
        probe.write_text("ok")
        probe.unlink()
        return _ok(f"Cache dir writable: {cache_dir}")
    except Exception as e:
        return _fail(f"Cache dir not writable: {e}")


def _check_audit_db() -> tuple[bool, str]:
    try:
        runs = list_runs(limit=1)
        if runs:
            r = runs[0]
            return _ok(f"Audit DB has {len(list_runs(limit=10000))} rows; "
                       f"latest: {r.strategy_name} @ {r.timestamp_utc[:19]} "
                       f"verdict={r.verdict}")
        return True, "Audit DB exists but empty (no runs recorded yet)"
    except Exception as e:
        return _fail(f"Audit DB probe failed: {e}")


def _check_canary_recently_passed() -> tuple[bool, str]:
    """Most recent canary verdict should never be ROBUST."""
    bad = []
    for canary in ("rand_canary", "overfit_canary", "leak_canary", "survivor_canary"):
        runs = list_runs(strategy=canary, limit=1)
        if runs and runs[0].verdict == "ROBUST":
            bad.append(canary)
    if bad:
        return _fail(f"CANARY ALERT — these returned ROBUST: {', '.join(bad)} "
                     f"(tool may be broken)")
    return _ok("No canary returned ROBUST in audit history")


CHECKS: list[tuple[str, Callable[[], tuple[bool, str]], bool]] = [
    ("python",     _check_python_version,        True),
    ("deps_req",   _check_required_imports,      True),
    ("deps_opt",   _check_optional_imports,      False),
    ("td_key",     _check_twelvedata_key,        False),
    ("config",     _check_config_loads,          True),
    ("strategies", _check_strategies_resolvable, True),
    ("cache",      _check_cache_writable,        True),
    ("audit_db",   _check_audit_db,              False),
    ("canaries",   _check_canary_recently_passed, True),
]


def doctor() -> None:
    """Run the full self-test sequence."""
    any_critical_failed = False
    console.print()
    console.print("[bold]tradelab doctor[/bold]\n")
    for name, check, critical in CHECKS:
        try:
            ok, msg = check()
        except Exception as e:
            ok, msg = False, f"check raised: {type(e).__name__}: {e}"
        crit_marker = "" if critical else " [dim](optional)[/dim]"
        if ok:
            console.print(f"  [green]OK [/green] {name:<12}{crit_marker}  {msg}")
        else:
            color = "red" if critical else "yellow"
            console.print(f"  [{color}]FAIL[/{color}] {name:<12}{crit_marker}  {msg}")
            if critical:
                any_critical_failed = True

    console.print()
    if any_critical_failed:
        console.print("[red]Doctor: 1+ critical checks failed.[/red]")
        raise typer.Exit(1)
    console.print("[green]Doctor: all critical checks passed.[/green]")
