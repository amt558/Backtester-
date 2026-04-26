"""ntfy.sh notification channel via stdlib urllib.request."""
from __future__ import annotations

import sys
from urllib.request import Request, urlopen

from tradelab.live.notify_channels import register


_PRIORITY_BY_SEVERITY = {"critical": "5", "warning": "4", "info": "3"}


def send(severity: str, title: str, body: str, config: dict) -> bool:
    ntfy_cfg = config.get("notifications", {}).get("ntfy", {})
    topic = ntfy_cfg.get("topic", "").strip()
    if not topic:
        return False
    server = ntfy_cfg.get("server", "https://ntfy.sh").rstrip("/")
    url = f"{server}/{topic}"
    req = Request(
        url,
        data=body.encode("utf-8"),
        method="POST",
        headers={
            "Title": title,
            "Priority": _PRIORITY_BY_SEVERITY.get(severity, "3"),
        },
    )
    try:
        with urlopen(req, timeout=3) as resp:
            return 200 <= resp.status < 300
    except Exception as e:
        print(f"[notify.ntfy] failed: {type(e).__name__}: {e}", file=sys.stderr)
        return False


register("ntfy", send)
