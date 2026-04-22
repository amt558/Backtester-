"""SSE (Server-Sent Events) broadcaster for the Job Tracker.

Each subscriber is an HTTP response wfile that the server keeps open.
Broadcast iterates a snapshot of the subscriber list (not the live list)
to remain safe under concurrent subscribe()/unsubscribe().
"""
from __future__ import annotations

import json
import threading
import uuid
from typing import Any, Optional


SSE_RETRY_MS = 3000


class Broadcaster:
    def __init__(self):
        self._lock = threading.Lock()
        self._clients: dict[str, Any] = {}  # token -> wfile

    def subscribe(self, wfile: Any, initial_state: Optional[list[dict]] = None) -> str:
        """Add a client. Optionally replay an initial state to that client only.

        Returns a token to use with unsubscribe().
        """
        token = uuid.uuid4().hex
        with self._lock:
            self._clients[token] = wfile

        # Only send retry hint + replay when an initial_state was supplied.
        # Without initial_state, subscribe() is a pure registration so callers
        # can race subscribe with broadcast without triggering a write here.
        if initial_state:
            try:
                wfile.write(f"retry: {SSE_RETRY_MS}\n\n".encode("utf-8"))
                for ev in initial_state:
                    wfile.write(f"data: {json.dumps(ev)}\n\n".encode("utf-8"))
                try:
                    wfile.flush()
                except Exception:
                    pass
            except (BrokenPipeError, ConnectionResetError, OSError):
                with self._lock:
                    self._clients.pop(token, None)
                return token  # caller can still unsubscribe — it's idempotent

        return token

    def unsubscribe(self, token: str) -> None:
        with self._lock:
            self._clients.pop(token, None)

    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    def broadcast(self, event: dict) -> None:
        """Write one SSE-formatted event to every connected client.

        Iterates a snapshot of the client list so concurrent subscribe()
        does not raise. Broken-pipe clients are pruned during the write.
        """
        payload = f"data: {json.dumps(event)}\n\n".encode("utf-8")
        with self._lock:
            snapshot = list(self._clients.items())

        dead: list[str] = []
        for token, wfile in snapshot:
            try:
                wfile.write(payload)
                try:
                    wfile.flush()
                except Exception:
                    pass
            except (BrokenPipeError, ConnectionResetError, OSError):
                dead.append(token)

        if dead:
            with self._lock:
                for t in dead:
                    self._clients.pop(t, None)
