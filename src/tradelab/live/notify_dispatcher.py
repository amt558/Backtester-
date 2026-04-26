"""NotifyDispatcher — watchdog tail of notify_events.jsonl + channel fan-out.

Runs in the dashboard launcher process (single consumer per host). Tracks a
byte offset; reads from EOF on start so previously-dispatched events do not
re-fire on dispatcher restart.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Optional

from watchdog.events import FileSystemEventHandler
from watchdog.observers.polling import PollingObserver

from tradelab.live import live_config, notify
from tradelab.live.notify_channels import CHANNELS


class _EventHandler(FileSystemEventHandler):
    def __init__(self, dispatcher: "NotifyDispatcher"):
        self._d = dispatcher

    def on_modified(self, event):
        if event.is_directory:
            return
        if Path(event.src_path).resolve() == self._d.events_path.resolve():
            self._d._drain()


class NotifyDispatcher:
    def __init__(self, events_path: Optional[Path] = None):
        self.events_path = events_path or notify.NOTIFY_EVENTS_PATH
        self._offset = 0
        self._lock = threading.Lock()
        self._observer: Optional[PollingObserver] = None

    def start(self) -> None:
        # Make sure file exists before observer attaches (avoids first-modify-after-create races)
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        self.events_path.touch(exist_ok=True)
        # Read-from-EOF: skip past any pre-existing events
        with self._lock:
            self._offset = self.events_path.stat().st_size

        self._observer = PollingObserver(timeout=0.2)
        self._observer.schedule(_EventHandler(self), str(self.events_path.parent), recursive=False)
        self._observer.start()

    def stop(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2.0)
            self._observer = None

    def _drain(self) -> None:
        """Read all bytes appended since last drain, dispatch one event per line."""
        with self._lock:
            try:
                with open(self.events_path, "rb") as f:
                    f.seek(self._offset)
                    new_bytes = f.read()
                    self._offset = f.tell()
            except OSError as e:
                print(f"[notify_dispatcher] read failed: {type(e).__name__}: {e}", file=sys.stderr)
                return

        if not new_bytes:
            return
        for raw_line in new_bytes.decode("utf-8", errors="replace").splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError as e:
                print(f"[notify_dispatcher] bad JSON: {e}: {raw_line!r}", file=sys.stderr)
                continue
            self._dispatch(event)

    def _dispatch(self, event: dict) -> None:
        cfg = live_config.get()
        severity = event.get("severity", "info")
        title = event.get("title", "")
        body = event.get("body", "")
        explicit = event.get("channels")

        enabled = set(cfg["notifications"]["enabled_channels"])
        if explicit is not None:
            requested = set(explicit)
        else:
            requested = set(cfg["notifications"]["severity_routing"].get(severity, []))

        for ch_name in sorted(requested & enabled):
            send_fn = CHANNELS.get(ch_name)
            if send_fn is None:
                print(f"[notify_dispatcher] no such channel: {ch_name}", file=sys.stderr)
                continue
            try:
                send_fn(severity, title, body, cfg)
            except Exception as e:
                print(f"[notify_dispatcher] {ch_name} raised: {type(e).__name__}: {e}", file=sys.stderr)
