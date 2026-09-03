"""Paste → stage → validate → register flow for the New Strategy modal.

Stages:
    1. name    — regex + collision check
    2. import  — write staged .py, run importlib, catch SyntaxError
    3. discover — require exactly one Strategy subclass
    4. instantiate — construct with defaults
    5. backtest — smoke_5 universe through run_backtest

Register does an atomic move to src/tradelab/strategies/ and appends to
tradelab.yaml's strategies: block.
"""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import sys
import time
import traceback
from pathlib import Path
from typing import Optional

from tradelab.registry import list_registered_strategies
from tradelab.strategies.base import Strategy


# Input pattern — accepts hyphens and uppercase (normalized to snake_case before use).
# User can type TEST-A5, Test_A5, test-a5, or test_a5; all become test_a5 internally.
NAME_INPUT_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]+$")


def _normalize_name(name: str) -> str:
    """Normalize user input to snake_case Python identifier form.

    Python modules must be valid identifiers, so hyphens/uppercase have to collapse.
    UI accepts the friendly form; filesystem + registry use the canonical form.
    """
    return name.strip().lower().replace("-", "_")


def _is_registered(name: str) -> bool:
    """Separate function so tests can monkeypatch config access."""
    try:
        return name in list_registered_strategies()
    except Exception:
        return False


def validate_and_stage(
    name: str,
    code: str,
    staging_root: Path,
    src_root: Path,
) -> dict:
    """Run the full validation pipeline. Returns result dict.

    Success:   {error: None, stage: "complete", metrics, equity_curves_by_symbol, canonical_name}
    Failure:   {error: "<msg>", stage: "name"|"import"|"discover"|"instantiate"|"backtest"}

    Side effect on success: staged file at staging_root/<canonical>.py.
    Side effect on failure: staged file is removed.
    """
    staging_root.mkdir(parents=True, exist_ok=True)

    # Stage 1: name
    if not NAME_INPUT_PATTERN.match(name):
        return {
            "error": f"name must match {NAME_INPUT_PATTERN.pattern} "
                     f"(letters, digits, underscores, hyphens; starts with letter)",
            "stage": "name",
        }
    canonical = _normalize_name(name)
    if _is_registered(canonical):
        return {"error": f"name '{canonical}' is already registered", "stage": "name"}

    # All further filesystem/registry operations use the canonical (snake_case) form.
    name = canonical
    staging_file = staging_root / f"{name}.py"

    # Stage 2: import
    # encoding="utf-8" is required: without it Path.write_text uses the host's
    # locale (cp1252 on Windows), corrupting em-dashes / smart quotes into bytes
    # the UTF-8 source importer rejects ("invalid start byte 0x97").
    staging_file.write_text(code, encoding="utf-8")
    try:
        mod = _import_file(name, staging_file)
    except Exception as e:
        staging_file.unlink(missing_ok=True)
        return {
            "error": f"import failed: {e}",
            "stage": "import",
            "traceback": traceback.format_exc(),
        }

    # Stage 3: discover
    # v.__module__ == mod.__name__ scopes discovery to classes DEFINED in the
    # staged module, so `from ...simple import SimpleStrategy` (an imported base)
    # isn't miscounted as a second strategy. Mirrors discover_unregistered_strategies().
    strategy_classes = [
        v for v in vars(mod).values()
        if isinstance(v, type) and issubclass(v, Strategy) and v is not Strategy
        and v.__module__ == mod.__name__
    ]
    if len(strategy_classes) != 1:
        staging_file.unlink(missing_ok=True)
        names = [c.__name__ for c in strategy_classes] or "(none)"
        return {
            "error": f"expected exactly one Strategy subclass, found: {names}",
            "stage": "discover",
        }
    StrategyClass = strategy_classes[0]

    # Stage 4: instantiate
    try:
        instance = StrategyClass(name=name)
    except Exception as e:
        staging_file.unlink(missing_ok=True)
        return {
            "error": f"constructor failed: {e}",
            "stage": "instantiate",
            "traceback": traceback.format_exc(),
        }

    # Stage 5: smoke_5 backtest
    try:
        metrics, equity_by_sym = _run_smoke_backtest(instance)
    except Exception as e:
        staging_file.unlink(missing_ok=True)
        return {
            "error": f"smoke_5 backtest failed: {e}",
            "stage": "backtest",
            "traceback": traceback.format_exc(),
        }

    # S2: a smoke that never trades is not a pass. Err toward FRAGILE — the
    # author fixes entry_signal() or the symbols before anything is registered.
    n_trades = metrics.get("total_trades", metrics.get("trades", None))
    try:
        n_trades = int(n_trades) if n_trades is not None else None
    except (TypeError, ValueError):
        n_trades = None
    if not n_trades:   # 0, None or unreadable — fail closed (Specialist review)
        staging_file.unlink(missing_ok=True)
        own = declared_symbols(StrategyClass)
        where = f"declared symbols {own}" if own else "the smoke_5 universe"
        detail = ("the entry rule never fired" if n_trades == 0
                  else "the engine reported no trade count")
        return {
            "error": f"smoke produced 0 trades on {where} — {detail}. "
                     f"Fix entry_signal() or the symbols, then Test again.",
            "stage": "smoke",
            "metrics": metrics,
        }

    return {
        "error": None,
        "stage": "complete",
        "metrics": metrics,
        "equity_curves_by_symbol": equity_by_sym,
        "class_name": StrategyClass.__name__,
        "canonical_name": name,
    }


def register_strategy(
    name: str,
    class_name: str,
    staging_root: Path,
    src_root: Path,
    yaml_path: Optional[Path] = None,
) -> dict:
    """Move staged file into src/tradelab/strategies/ and append to tradelab.yaml.

    Accepts either the raw user-typed name or the canonical snake_case form;
    normalizes internally so callers don't have to remember.

    Returns {error, final_path} on result.
    """
    from tradelab.registry import list_registered_strategies
    name = _normalize_name(name)
    # Re-check collision — could have been created while user viewed results
    if _is_registered(name):
        return {"error": f"name '{name}' is now taken (register blocked)", "final_path": None}

    staging_file = staging_root / f"{name}.py"
    if not staging_file.exists():
        return {"error": "staging file missing", "final_path": None}

    dest_dir = src_root / "tradelab" / "strategies"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / f"{name}.py"
    if dest_file.exists():
        return {"error": f"destination {dest_file} already exists", "final_path": None}

    # Atomic move
    shutil.move(str(staging_file), str(dest_file))

    # Append to tradelab.yaml strategies block
    if yaml_path is None:
        yaml_path = Path("tradelab.yaml")
    _append_strategy_to_yaml(yaml_path, name, class_name)
    _reload_registry()

    return {"error": None, "final_path": str(dest_file)}


def discard_staging(name: str, staging_root: Path) -> None:
    """Delete staged file if present. No error if missing.

    Accepts raw user input or canonical name — normalizes internally.
    """
    path = staging_root / f"{_normalize_name(name)}.py"
    path.unlink(missing_ok=True)


def cleanup_old_staging(staging_root: Path, max_age_hours: float = 24.0) -> int:
    """Remove staged files older than max_age_hours. Returns count removed."""
    if not staging_root.exists():
        return 0
    cutoff = time.time() - (max_age_hours * 3600)
    removed = 0
    for p in staging_root.glob("*.py"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                removed += 1
        except OSError:
            continue
    return removed


# ─── Internal helpers ─────────────────────────────────────────────────


def _import_file(name: str, path: Path):
    """Import a .py file as a module, isolated from normal import path."""
    mod_name = f"_tradelab_staged_{name}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not spec file {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(mod_name, None)
        raise
    return module


def _run_smoke_backtest(strategy) -> tuple[dict, dict]:
    """Run strategy against smoke_5 universe. Returns (metrics, equity_by_symbol)."""
    from tradelab.engines.backtest import run_backtest
    from tradelab.marketdata import cache
    from tradelab.config import get_config

    cfg = get_config()
    # S2: a strategy that declares its own tickers is smoked on exactly those;
    # otherwise the smoke_5 universe as before.
    own = declared_symbols(type(strategy))
    if own:
        smoke_universe = own
        universe_label = "declared symbols"
    else:
        smoke_universe = cfg.universes.get("smoke_5", ["SPY", "NVDA", "MSFT", "AAPL", "META"])
        universe_label = "smoke_5"
    ticker_data = {}
    missing: list[str] = []
    for sym in smoke_universe:
        df = cache.read(sym, strategy.timeframe)
        if df is not None and not df.empty:
            ticker_data[sym] = df
        else:
            missing.append(sym)
    if not ticker_data:
        raise RuntimeError(
            f"no {universe_label} data in cache for {smoke_universe} "
            f"at timeframe {strategy.timeframe} — refresh data first"
        )
    if own and missing:
        # A declared universe is smoked whole or not at all — a strategy that
        # names 10 tickers must not quietly pass on the 1 that happens to be
        # cached (Specialist review).
        raise RuntimeError(
            f"declared symbols not in cache: {missing} — refresh data or remove "
            f"them from `symbols` before testing"
        )
    # Enrich exactly like the full run (cli_run) does. Raw parquet has no ATR,
    # and the engine skips every entry/exit on a NaN-ATR bar, so an un-enriched
    # smoke backtest produces zero trades for ANY strategy. enrich_universe adds
    # ATR/RSI/SMA50/... and handles the SPY benchmark for RS_21d internally.
    from tradelab.marketdata.enrich import enrich_universe

    enriched = enrich_universe(ticker_data, benchmark="SPY")

    spy_close = None
    if strategy.requires_benchmark and "SPY" in enriched:
        spy_close = enriched["SPY"].set_index("Date")["Close"]

    result = run_backtest(strategy, enriched, spy_close=spy_close)
    metrics = getattr(result, "metrics", {}) or {}
    # Build per-symbol equity curves from the strategy's signals for visual overlay
    equity_by_sym: dict[str, list] = {}
    curve = getattr(result, "equity_curve", None)
    if curve is not None and not isinstance(curve, list):
        # Fallback: flatten into a single curve keyed as "portfolio"
        try:
            import pandas as pd
            if isinstance(curve, pd.DataFrame):
                equity_by_sym["portfolio"] = [
                    {"date": str(r["date"]), "equity": float(r["equity"])}
                    for _, r in curve.iterrows()
                ]
        except Exception:
            pass
    elif isinstance(curve, list):
        equity_by_sym["portfolio"] = curve
    return dict(metrics), equity_by_sym


def discover_unregistered_strategies(src_root: Optional[Path] = None) -> list[dict]:
    """Scan src/tradelab/strategies/ for Strategy subclasses whose module is not
    yet registered in tradelab.yaml. Returns one record per importable subclass.

    Records: {module, class_name, suggested_name, timeframe, requires_benchmark}.
    Files that fail to import or define no Strategy subclass are silently skipped
    (a half-written strategy must never break the scan)."""
    import importlib

    if src_root is None:
        src_root = Path("src")
    try:
        registered = list_registered_strategies()
        registered_modules = {getattr(e, "module", None) for e in registered.values()}
    except Exception:
        registered_modules = set()

    strat_dir = src_root / "tradelab" / "strategies"
    out: list[dict] = []
    if not strat_dir.is_dir():
        return out
    for py in sorted(strat_dir.glob("*.py")):
        if py.name in ("__init__.py", "base.py"):
            continue
        module_path = f"tradelab.strategies.{py.stem}"
        if module_path in registered_modules:
            continue
        try:
            mod = importlib.import_module(module_path)
        except Exception:
            continue
        for v in vars(mod).values():
            if (isinstance(v, type) and issubclass(v, Strategy)
                    and v is not Strategy and v.__module__ == module_path
                    and not _is_abstract_base(v)):
                out.append({
                    "module": module_path,
                    "class_name": v.__name__,
                    "suggested_name": py.stem,
                    "timeframe": getattr(v, "timeframe", "1D"),
                    "requires_benchmark": bool(getattr(v, "requires_benchmark", False)),
                    "symbols": declared_symbols(v),
                })
    return out


def _is_abstract_base(cls: type) -> bool:
    """A class that carries `_tradelab_abstract = True` in its OWN __dict__ is a
    base meant for subclassing (SimpleStrategy) and must never be offered as an
    importable strategy (S0 finding F7). Subclasses don't inherit the marker."""
    return bool(vars(cls).get("_tradelab_abstract", False))


def declared_symbols(cls: type) -> list[str]:
    """Tickers a strategy declares on itself (S2). Normalised to upper-case,
    de-duplicated, order preserved; anything that isn't a plausible ticker is
    dropped rather than allowed to reach the data layer."""
    raw = getattr(cls, "symbols", None) or []
    if isinstance(raw, str):
        # `symbols = "TSLA"` is a common slip; iterating the string would
        # fabricate a universe of single letters (T, S, L, A are real tickers).
        raw = [raw]
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        sym = item.strip().upper()
        if sym and _TICKER_RE.match(sym) and sym not in out:
            out.append(sym)
    return out


_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def import_discovered(
    name: str,
    class_name: str,
    yaml_path: Optional[Path] = None,
) -> dict:
    """Register an already-on-disk discovered strategy by appending its
    tradelab.yaml entry. `name` MUST equal the file stem (module is
    tradelab.strategies.<name>). Idempotent; refuses an already-registered name."""
    name = _normalize_name(name)
    if _is_registered(name):
        return {"error": f"'{name}' is already registered", "registered": False}
    if yaml_path is None:
        yaml_path = Path("tradelab.yaml")
    _append_strategy_to_yaml(yaml_path, name, class_name)
    _reload_registry()
    return {"error": None, "registered": True, "name": name}


def _reload_registry() -> None:
    """Drop the process-level config cache after tradelab.yaml changes, so the
    running dashboard sees a just-imported strategy without a restart (S0
    finding F8). Best-effort: a reload failure must never undo the write."""
    try:
        from tradelab.config import get_config
        get_config(reload=True)
    except Exception as e:  # noqa: BLE001
        import sys
        print(f"[registry] reload after tradelab.yaml write failed: {type(e).__name__}: {e} "
              f"— the previous registry stays in effect until restart", file=sys.stderr)


def _append_strategy_to_yaml(yaml_path: Path, name: str, class_name: str) -> None:
    """Append a strategy entry to tradelab.yaml under strategies:.

    Naive line-append — avoids introducing a YAML round-trip library dep.
    tradelab.yaml is small and user-maintained; this is low risk.
    """
    if not yaml_path.exists():
        raise FileNotFoundError(f"tradelab.yaml not found at {yaml_path}")

    entry = (
        f"\n  {name}:\n"
        f"    module: tradelab.strategies.{name}\n"
        f"    class_name: {class_name}\n"
        f"    params: {{}}\n"
    )
    text = yaml_path.read_text()
    if f"  {name}:" in text:
        return  # already present — idempotent
    # Find "strategies:" block and append at the end of it
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    in_strategies = False
    inserted = False
    for i, line in enumerate(lines):
        out.append(line)
        if line.rstrip() == "strategies:":
            in_strategies = True
            continue
        if in_strategies and not inserted:
            # Check if next line is at top level (no indent) — end of block
            is_last = i == len(lines) - 1
            next_line = lines[i + 1] if not is_last else ""
            next_is_top_level = bool(next_line) and not next_line.startswith((" ", "\t"))
            if is_last or next_is_top_level:
                out.append(entry)
                inserted = True
    if not inserted:
        # Defensive: no strategies block found; append to end
        out.append("\nstrategies:" + entry)
    yaml_path.write_text("".join(out))
