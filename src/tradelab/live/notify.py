"""notify() — append-one-line entry point for cross-process notification delivery.

Producers (receiver, dashboard, future panic/silence checkers) call notify(...).
The dispatcher process (one per host, lives in the dashboard launcher) tails
notify_events.jsonl and fans out to channel modules.

Decoupling via JSONL keeps producer code path identical regardless of which
process it runs in — same as alerts.jsonl.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

NOTIFY_EVENTS_PATH = Path(__file__).resolve().parents[3] / "live" / "notify_events.jsonl"


class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


def notify(
    severity: Severity,
    title: str,
    body: str,
    *,
    channels: Optional[set[str]] = None,
) -> None:
    """Append a single JSONL event. Best-effort; failures swallowed.

    severity: routing key (resolved by dispatcher against live_config).
    title/body: human-readable strings.
    channels: optional explicit channel set, bypasses routing matrix.
    """
    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "severity": severity.value if isinstance(severity, Severity) else str(severity),
        "title": title,
        "body": body,
        "channels": sorted(channels) if channels is not None else None,
    }
    try:
        NOTIFY_EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(NOTIFY_EVENTS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except Exception as e:
        # Notification machinery must never crash the producer.
        import sys
        print(f"[notify] failed to append event: {type(e).__name__}: {e}", file=sys.stderr)
