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


NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]+$")


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

    Success:   {error: None, stage: "complete", metrics, equity_curves_by_symbol}
    Failure:   {error: "<msg>", stage: "name"|"import"|"discover"|"instantiate"|"backtest"}

    Side effect on success: staged file at staging_root/<name>.py.
    Side effect on failure: staged file is removed.
    """
    staging_root.mkdir(parents=True, exist_ok=True)
    staging_file = staging_root / f"{name}.py"

    # Stage 1: name
    if not NAME_PATTERN.match(name):
        return {"error": f"name must match {NAME_PATTERN.pattern}", "stage": "name"}
    if _is_registered(name):
        return {"error": f"name '{name}' is already registered", "stage": "name"}

    # Stage 2: import
    staging_file.write_text(code)
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
    strategy_classes = [
        v for v in vars(mod).values()
        if isinstance(v, type) and issubclass(v, Strategy) and v is not Strategy
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

    return {
        "error": None,
        "stage": "complete",
        "metrics": metrics,
        "equity_curves_by_symbol": equity_by_sym,
        "class_name": StrategyClass.__name__,
    }


def register_strategy(
    name: str,
    class_name: str,
    staging_root: Path,
    src_root: Path,
    yaml_path: Optional[Path] = None,
) -> dict:
    """Move staged file into src/tradelab/strategies/ and append to tradelab.yaml.

    Returns {error, final_path} on result.
    """
    from tradelab.registry import list_registered_strategies
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

    return {"error": None, "final_path": str(dest_file)}


def discard_staging(name: str, staging_root: Path) -> None:
    """Delete staged file if present. No error if missing."""
    path = staging_root / f"{name}.py"
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
    smoke_universe = cfg.universes.get("smoke_5", ["SPY", "NVDA", "MSFT", "AAPL", "META"])
    ticker_data = {}
    for sym in smoke_universe:
        df = cache.read(sym, strategy.timeframe)
        if df is not None and not df.empty:
            ticker_data[sym] = df
    if not ticker_data:
        raise RuntimeError(
            f"no smoke_5 data in cache for {smoke_universe} "
            f"at timeframe {strategy.timeframe} — refresh data first"
        )
    spy_close = None
    if strategy.requires_benchmark and "SPY" in ticker_data:
        spy_close = ticker_data["SPY"].set_index("Date")["Close"]

    result = run_backtest(strategy, ticker_data, spy_close=spy_close)
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
