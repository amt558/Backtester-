"""Browser notification channel — pushes event onto the notify SSE Broadcaster."""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from tradelab.live.notify_channels import register
from tradelab.web import get_notify_broadcaster


def send(severity: str, title: str, body: str, config: dict) -> bool:
    try:
        get_notify_broadcaster().broadcast({
            "ts": datetime.now(timezone.utc).isoformat(),
            "severity": severity,
            "title": title,
            "body": body,
        })
        return True
    except Exception as e:
        print(f"[notify.browser] failed: {type(e).__name__}: {e}", file=sys.stderr)
        return False


register("browser", send)
