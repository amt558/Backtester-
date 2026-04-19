"""
Market data access — downloader with Twelve Data + yfinance fallback, parquet cache.

This package is distinct from `tradelab.data`, which loads 1-min CSVs from disk.
Live downloading and parquet caching live here.

Public API:
    download_symbols(symbols, start, end, timeframe="1D", force=False)
        -> dict[symbol, DataFrame]
    cache_status() -> dict
    clear_cache(symbol=None) -> int  # number of files removed

See src/tradelab/marketdata/downloader.py for orchestration logic.
"""
from .downloader import download_symbols
from .cache import cache_status, clear_cache
from .enrich import enrich_with_indicators, enrich_universe
from .pit import assert_pit_valid, check_pit, PITViolation

__all__ = [
    "download_symbols", "cache_status", "clear_cache",
    "enrich_with_indicators", "enrich_universe",
    "assert_pit_valid", "check_pit", "PITViolation",
]
