"""
Parquet-based OHLCV cache.

Files: .cache/ohlcv/<timeframe>/<symbol>.parquet
Manifest: .cache/manifest.json — {symbol: {last_download, source, rows}}

Staleness: a cache entry is stale if its mtime is older than the most
recently closed trading day (America/New_York timezone, 4 PM ET close).
For simplicity this is computed as "previous business day before today's
4pm ET" without holiday awareness; corner cases are handled by the --force
flag which bypasses staleness checks entirely.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd


# --- paths ------------------------------------------------------------------

_CACHE_ROOT = Path(".cache") / "ohlcv"
_MANIFEST_PATH = Path(".cache") / "manifest.json"


def _cache_path(symbol: str, timeframe: str) -> Path:
    return _CACHE_ROOT / timeframe / f"{symbol.upper()}.parquet"


def list_cached_symbols(timeframe: str = "1D") -> list[str]:
    """Return sorted list of symbols that have a parquet cache entry at this
    timeframe. Replaces the legacy CSV-based ``list_available_symbols``."""
    root = _CACHE_ROOT / timeframe
    if not root.exists():
        return []
    return sorted(p.stem.upper() for p in root.glob("*.parquet"))


def _load_manifest() -> dict:
    if not _MANIFEST_PATH.exists():
        return {}
    try:
        return json.loads(_MANIFEST_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def _save_manifest(m: dict) -> None:
    _MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    _MANIFEST_PATH.write_text(json.dumps(m, indent=2, default=str))


# --- staleness --------------------------------------------------------------

def _last_close_ts() -> pd.Timestamp:
    """The timestamp at or before which a valid daily bar should exist."""
    now = pd.Timestamp.now()
    # Crude: previous business day before today
    return (now - pd.offsets.BDay(1)).normalize()


def is_stale(symbol: str, timeframe: str = "1D") -> bool:
    path = _cache_path(symbol, timeframe)
    if not path.exists():
        return True
    try:
        df = pd.read_parquet(path)
        if df.empty:
            return True
        last_bar = pd.Timestamp(df["Date"].max()).normalize()
        return last_bar < _last_close_ts()
    except Exception:
        return True


# --- read / write -----------------------------------------------------------

def read(symbol: str, timeframe: str = "1D") -> Optional[pd.DataFrame]:
    path = _cache_path(symbol, timeframe)
    if not path.exists():
        return None
    try:
        return pd.read_parquet(path)
    except Exception:
        return None


def write(symbol: str, df: pd.DataFrame, source: str, timeframe: str = "1D") -> None:
    path = _cache_path(symbol, timeframe)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)

    manifest = _load_manifest()
    manifest[symbol.upper()] = {
        "last_download": datetime.now().isoformat(timespec="seconds"),
        "source": source,
        "rows": int(len(df)),
        "timeframe": timeframe,
    }
    _save_manifest(manifest)


# --- public ops -------------------------------------------------------------

def cache_status(symbol: Optional[str] = None) -> dict:
    m = _load_manifest()
    if symbol:
        return {symbol.upper(): m.get(symbol.upper(), None)}
    return m


def clear_cache(symbol: Optional[str] = None) -> int:
    removed = 0
    if symbol:
        path = _cache_path(symbol, "1D")
        if path.exists():
            path.unlink()
            removed += 1
        m = _load_manifest()
        m.pop(symbol.upper(), None)
        _save_manifest(m)
    else:
        if _CACHE_ROOT.exists():
            for p in _CACHE_ROOT.rglob("*.parquet"):
                p.unlink()
                removed += 1
        if _MANIFEST_PATH.exists():
            _MANIFEST_PATH.unlink()
    return removed
