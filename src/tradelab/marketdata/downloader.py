"""
Downloader orchestrator.

For each requested symbol:
  1. Check cache; if present and not stale and not --force, use cached data
  2. Otherwise try Twelve Data (if available)
  3. On Twelve Data failure, fall back to yfinance
  4. Write successful download to cache
  5. Return dict[symbol, DataFrame]

Never raises on per-symbol failure — returns the symbols it could get and
a _failed dict the caller can inspect via the return's metadata.
"""
from __future__ import annotations

import warnings
from typing import Optional

import pandas as pd

from ..env import load_env
from . import cache
from .sources import twelvedata as td
from .sources import yfinance as yf_src


class MissingTwelveDataKey(RuntimeError):
    """Raised when TWELVEDATA_API_KEY is absent and fallback is not allowed."""


def download_symbols(
    symbols: list[str],
    start: str = "2020-01-01",
    end: Optional[str] = None,
    timeframe: str = "1D",
    force: bool = False,
    allow_yfinance_fallback: bool = False,
) -> dict[str, pd.DataFrame]:
    # Pull keys from .env files if present (no-op if already loaded)
    load_env()

    if end is None:
        end = pd.Timestamp.now().strftime("%Y-%m-%d")

    out: dict[str, pd.DataFrame] = {}
    td_key_present = td.is_available()
    yf_available = yf_src.is_available()

    if not td_key_present:
        if not allow_yfinance_fallback:
            raise MissingTwelveDataKey(
                "TWELVEDATA_API_KEY is not set in the environment or .env file. "
                "tradelab requires Twelve Data as the authoritative data source. "
                "Either:\n"
                "  - Set the env var: export TWELVEDATA_API_KEY=your_key\n"
                "  - Add to .env at repo root: TWELVEDATA_API_KEY=your_key\n"
                "  - Pass --allow-yfinance-fallback explicitly (not recommended)"
            )
        warnings.warn(
            "TWELVEDATA_API_KEY not set — yfinance fallback explicitly allowed.",
            RuntimeWarning, stacklevel=2,
        )

    for sym in symbols:
        sym_u = sym.upper()

        # Cache hit?
        if not force and not cache.is_stale(sym_u, timeframe):
            cached = cache.read(sym_u, timeframe)
            if cached is not None and not cached.empty:
                # Slice to requested window
                mask = (cached["Date"] >= pd.Timestamp(start)) & (cached["Date"] <= pd.Timestamp(end))
                out[sym_u] = cached.loc[mask].reset_index(drop=True)
                continue

        # Cache miss or stale — download
        df = None
        source_used = None

        if td_key_present:
            df = td.download(sym_u, start, end, timeframe)
            if df is not None and not df.empty:
                source_used = "twelvedata"

        # yfinance only runs when explicitly allowed — either because TD was
        # skipped (allow_yfinance_fallback=True and no key), or because TD
        # returned empty for this symbol and allow_yfinance_fallback=True.
        if df is None and yf_available and allow_yfinance_fallback:
            df = yf_src.download(sym_u, start, end, timeframe)
            if df is not None and not df.empty:
                source_used = "yfinance"

        if df is None or df.empty:
            warnings.warn(f"Failed to download {sym_u} from any source.", RuntimeWarning, stacklevel=2)
            continue

        # Cache and emit
        cache.write(sym_u, df, source=source_used, timeframe=timeframe)
        out[sym_u] = df

    return out
