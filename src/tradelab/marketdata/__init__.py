"""
Market data access -- Twelve Data downloader + parquet cache.

This is the authoritative data path for tradelab. The old CSV-based
``tradelab.data`` module is DEPRECATED and not used by the active workflow.

Public API:
    download_symbols(symbols, start, end, timeframe="1D", force=False)
        -> dict[symbol, DataFrame]
    list_cached_symbols(timeframe="1D") -> list[str]
    cache_status() -> dict
    clear_cache(symbol=None) -> int  # number of files removed

See src/tradelab/marketdata/downloader.py for orchestration logic.
"""
from .downloader import download_symbols, MissingTwelveDataKey
from .cache import cache_status, clear_cache, list_cached_symbols
from .enrich import enrich_with_indicators, enrich_universe
from .pit import assert_pit_valid, check_pit, PITViolation

__all__ = [
    "download_symbols", "MissingTwelveDataKey",
    "cache_status", "clear_cache", "list_cached_symbols",
    "enrich_with_indicators", "enrich_universe",
    "assert_pit_valid", "check_pit", "PITViolation",
]
