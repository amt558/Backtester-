"""2-second-cached read view over the Alpaca trading account.

Guardrails poll positions / open orders / buying-power frequently when many
cards fire at once. A short TTL makes 10 webhooks landing in the same second
do at most one fetch per resource, while still being fresh enough that a
just-submitted order's working notional is reflected on the next webhook
(callers invalidate after each successful submit).
"""
from __future__ import annotations

import time
from threading import Lock
from typing import Any, Optional

from alpaca.trading.enums import QueryOrderStatus
from alpaca.trading.requests import GetOrdersRequest


class AlpacaState:
    def __init__(self, client: Any, ttl_seconds: float = 2.0) -> None:
        self._client = client
        self._ttl = ttl_seconds
        self._lock = Lock()
        self._cache: dict[str, tuple[float, Any]] = {}

    def _get_cached(self, key: str, fetch):
        now = time.monotonic()
        with self._lock:
            entry = self._cache.get(key)
            if entry and (now - entry[0]) < self._ttl:
                return entry[1]
        value = fetch()
        with self._lock:
            self._cache[key] = (now, value)
        return value

    def positions(self) -> list:
        return self._get_cached("positions", self._client.get_all_positions)

    def open_orders(self) -> list:
        def fetch():
            req = GetOrdersRequest(status=QueryOrderStatus.OPEN)
            return self._client.get_orders(filter=req)
        return self._get_cached("orders", fetch)

    def account(self):
        return self._get_cached("account", self._client.get_account)

    def invalidate(self) -> None:
        """Clear all caches. Call after any change that would invalidate
        positions / orders / buying-power (e.g., a successful submit)."""
        with self._lock:
            self._cache.clear()
