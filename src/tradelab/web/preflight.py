"""Preflight checks for the Research tab run modal + chip cluster.

Four synchronous, disk-local checks (<100ms total, no network):
  - universe: launcher-state.json resolves + universe has >=1 symbol
  - cache:    parquet cache freshness for the resolved universe
  - strategy: all registered tradelab.yaml strategies import cleanly
  - tdapi:    TWELVEDATA_API_KEY env var is set

Each returns a dict with keys:
  status: "ok" | "warn" | "red"
  label:  short human string for the chip
  detail: longer string shown in tooltip / Run modal
"""
from __future__ import annotations

import importlib
import os
from datetime import datetime, timezone
from pathlib import Path

from tradelab.web.handlers import _resolve_active_universe


CACHE_WARN_HOURS = 24
CACHE_ROOT = Path(".cache") / "ohlcv" / "1D"


def check_universe() -> dict:
    name = _resolve_active_universe()
    if not name:
        return {"status": "red", "label": "no universe",
                "detail": "launcher-state.json missing or unreadable, and tradelab.yaml has no universes"}
    try:
        from tradelab.config import get_config
        cfg = get_config()
    except Exception as e:
        return {"status": "red", "label": "config load failed",
                "detail": f"tradelab.yaml load error: {type(e).__name__}: {e}"}
    symbols = cfg.universes.get(name, [])
    if not symbols:
        return {"status": "red", "label": f"{name} (0 symbols)",
                "detail": f"universe {name!r} resolved but contains no symbols"}
    return {"status": "ok", "label": f"{name} ({len(symbols)})",
            "detail": f"{len(symbols)} symbols in universe {name!r}"}


def check_cache() -> dict:
    name = _resolve_active_universe()
    if not name:
        return {"status": "red", "label": "universe unknown",
                "detail": "cannot assess cache without a resolved universe"}
    try:
        from tradelab.config import get_config
        symbols = get_config().universes.get(name, [])
    except Exception:
        symbols = []
    if not symbols:
        return {"status": "red", "label": "no symbols",
                "detail": "universe has no symbols to cache"}
    missing = []
    ages_hours = []
    now = datetime.now(tz=timezone.utc).timestamp()
    for sym in symbols:
        p = CACHE_ROOT / f"{sym}.parquet"
        if not p.exists():
            missing.append(sym)
            continue
        ages_hours.append((now - p.stat().st_mtime) / 3600)
    if missing and len(missing) > 5:
        return {"status": "red", "label": f"{len(missing)} missing",
                "detail": f"{len(missing)} parquet files missing for universe {name!r}: "
                          f"{', '.join(missing[:5])}..."}
    if missing:
        return {"status": "warn", "label": f"{len(missing)} missing",
                "detail": f"parquet missing: {', '.join(missing)}"}
    oldest = max(ages_hours) if ages_hours else 0
    if oldest > CACHE_WARN_HOURS:
        return {"status": "warn", "label": f"{oldest:.1f}h old",
                "detail": f"oldest parquet is {oldest:.1f}h - consider Refresh Data"}
    return {"status": "ok", "label": f"{oldest:.1f}h",
            "detail": f"all {len(symbols)} symbols cached, oldest {oldest:.1f}h"}


def check_strategies() -> dict:
    try:
        from tradelab.config import get_config
        cfg = get_config()
    except Exception as e:
        return {"status": "red", "label": "config load failed",
                "detail": f"tradelab.yaml load error: {type(e).__name__}: {e}"}
    names = list(cfg.strategies.keys()) if hasattr(cfg, "strategies") else []
    if not names:
        return {"status": "warn", "label": "0 registered",
                "detail": "no strategies registered in tradelab.yaml"}
    failed = []
    for name in names:
        last_err = None
        for module_root in ("tradelab.strategies", "tradelab.canaries"):
            try:
                importlib.import_module(f"{module_root}.{name}")
                last_err = None
                break
            except ModuleNotFoundError:
                continue
            except Exception as e:
                last_err = e
                break
        else:
            last_err = last_err or ModuleNotFoundError(name)
        if last_err is not None:
            failed.append(f"{name} ({type(last_err).__name__})")
    if failed:
        return {"status": "red", "label": f"{len(failed)} broken",
                "detail": "import failed: " + ", ".join(failed)}
    return {"status": "ok", "label": f"{len(names)} OK",
            "detail": f"all {len(names)} registered strategies importable"}


def check_tdapi() -> dict:
    if os.environ.get("TWELVEDATA_API_KEY"):
        return {"status": "ok", "label": "key present",
                "detail": "TWELVEDATA_API_KEY is set"}
    return {"status": "red", "label": "key missing",
            "detail": "TWELVEDATA_API_KEY env var not set - data downloads will fail"}


def compute_preflight() -> dict:
    return {
        "universe": check_universe(),
        "cache":    check_cache(),
        "strategy": check_strategies(),
        "tdapi":    check_tdapi(),
    }
