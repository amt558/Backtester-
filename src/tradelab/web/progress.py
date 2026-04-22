"""Polling tail reader for .cache/jobs/<id>/progress.jsonl.

Stdlib-only - no `watchdog` dependency. Polls the file every 500ms, reads
any new bytes since last position, splits on \n, parses each complete line,
and invokes a callback per valid event.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable, Optional

from .progress_events import parse_event


class ProgressTailer:
    """Tails a JSONL file in a background thread.

    Use:
        t = ProgressTailer(path, on_event=lambda ev: ...)
        t.start()
        ...
        t.stop()  # blocks until thread exits
    """

    def __init__(
        self,
        path: Path,
        on_event: Callable[[dict], None],
        poll_interval_s: float = 0.5,
    ):
        self.path = Path(path)
        self.on_event = on_event
        self.poll_interval_s = poll_interval_s
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _run(self) -> None:
        position = 0
        buffer = ""
        # We loop until stop is set, then do one final drain pass so any
        # bytes written between the last poll and the stop signal still
        # reach the callback (subprocesses often emit 'done' just before
        # exiting, racing with the watcher that triggers stop()).
        while True:
            stopping = self._stop.is_set()
            try:
                if self.path.exists():
                    size = self.path.stat().st_size
                    if size > position:
                        with self.path.open("r", encoding="utf-8") as f:
                            f.seek(position)
                            chunk = f.read(size - position)
                            position = size
                        buffer += chunk
                        # process complete lines
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            ev = parse_event(line)
                            if ev is not None:
                                try:
                                    self.on_event(ev)
                                except Exception:
                                    # callback errors must not kill the tailer
                                    pass
                    elif size < position:
                        # file shrank (truncated/rotated) - restart from 0
                        position = 0
                        buffer = ""
            except (OSError, IOError):
                pass  # transient disk error - retry next poll
            if stopping:
                return
            self._stop.wait(timeout=self.poll_interval_s)
