"""Read Claude-recommended parameter ranges for What-If sliders.

Sidecar lives at src/tradelab/strategies/<name>/claude_ranges.json.
Schema per param: {min, max, default, step, claude_note}.

Presence of this file enables the What-If tab in the modal. Absence hides it.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

_DEFAULT_SRC = Path("src")


def get_ranges(strategy_name: str, src_root: Optional[Path] = None) -> Optional[dict]:
    """Return the parsed sidecar, or None if missing or malformed."""
    root = Path(src_root) if src_root else _DEFAULT_SRC
    path = root / "tradelab" / "strategies" / strategy_name / "claude_ranges.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
