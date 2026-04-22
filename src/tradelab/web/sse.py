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

        # Two distinct guards:
        #   - initial_state IS NOT None ─► caller signals "real client connection"
        #     so write the SSE retry hint per spec §6.3 (always, even when the
        #     replay is empty — empty active-job list is normal on cold start).
        #   - initial_state IS truthy   ─► also replay the per-job state events.
        # When initial_state is None (test default), subscribe() is a pure
        # registration with no IO — tests can race subscribe + broadcast safely.
        if initial_state is not None:
            try:
                wfile.write(f"retry: {SSE_RETRY_MS}\n\n".encode("utf-8"))
                if initial_state:
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

    def is_subscribed(self, token: str) -> bool:
        with self._lock:
            return token in self._clients

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
