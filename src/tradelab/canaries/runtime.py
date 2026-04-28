"""Runtime canary integrity check (Slice 0.5).

Queries the audit DB for the most recent verdict of each canary. If any
canary's latest verdict is ROBUST (or any other verdict outside its expected
set), the gauntlet is suspect — the dashboard should block new Accepts
globally until the engine is investigated.

Never-run canaries are reported as UNKNOWN — that does NOT block accepts
(infra/missing-data is not the same as engine drift).

This is a status query, NOT a re-run. Re-running canaries takes minutes;
this query is cheap and safe to call on every Research-tab load.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from tradelab.audit.history import DEFAULT_DB_PATH, list_runs
from tradelab.cli_canary import CANARY_NAMES, EXPECTED_VERDICT


@dataclass
class CanaryStatus:
    """Snapshot of canary integrity at a point in time.

    canaries: one dict per canary with fields name/expected/actual/status/last_run.
    all_match: False iff any canary is MISMATCH (engine drift). UNKNOWN canaries
               do NOT flip this to False — they're missing-data, not drift.
    last_run_at: ISO-8601 timestamp of when this snapshot was produced.
    """

    canaries: list[dict] = field(default_factory=list)
    all_match: bool = True
    last_run_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def run_canary_check(*, db_path: Optional[Path] = None) -> CanaryStatus:
    """Read the latest verdict per canary from the audit DB.

    For each canary in CANARY_NAMES, query the single most recent row and
    classify:

    - MATCH:    latest verdict is in EXPECTED_VERDICT[name]
                (typically FRAGILE or INCONCLUSIVE — the gauntlet correctly
                 flagged the deliberately-broken strategy)
    - MISMATCH: latest verdict is OUTSIDE the expected set
                (typically ROBUST — the gauntlet failed to catch the canary,
                 so the engine itself is suspect)
    - UNKNOWN:  no audit rows for this canary (never run on this machine)

    Only MISMATCH flips all_match=False. UNKNOWN is treated as missing data
    (engine integrity unproven, but not actively wrong); the dashboard
    surfaces UNKNOWN visually but does NOT block accepts on it.

    Args:
        db_path: optional override for the audit DB location. Defaults to
                 DEFAULT_DB_PATH (data/tradelab_history.db relative to cwd).

    Returns:
        CanaryStatus snapshot.
    """
    db = db_path if db_path is not None else DEFAULT_DB_PATH

    canaries: list[dict] = []
    all_match = True
    for name in CANARY_NAMES:
        expected = EXPECTED_VERDICT[name]
        rows = list_runs(strategy=name, limit=1, db_path=db)
        if not rows:
            actual = None
            last_run = None
            status = "UNKNOWN"
        else:
            actual = rows[0].verdict
            last_run = rows[0].timestamp_utc
            if actual in expected:
                status = "MATCH"
            else:
                status = "MISMATCH"
                all_match = False
        canaries.append(
            {
                "name": name,
                "expected": sorted(expected),
                "actual": actual,
                "status": status,
                "last_run": last_run,
            }
        )

    return CanaryStatus(
        canaries=canaries,
        all_match=all_match,
        last_run_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
