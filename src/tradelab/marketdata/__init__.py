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

__all__ = ["download_symbols", "cache_status", "clear_cache"]
