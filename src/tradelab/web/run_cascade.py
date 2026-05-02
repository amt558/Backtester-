"""Cascade detection for run deletion.

When the user asks to delete one or more runs, the FE needs to know which
live cards depend on those runs (via card.scoring_run_id) so it can
escalate to a card-aware confirm modal (Tier 2 / Tier 4) before the
destructive action fires.

Pure: caller passes an iterable of card dicts (typically
`CardRegistry.all_hydrated().values()`) and a set of candidate run_ids.
No I/O.
"""

from __future__ import annotations

from typing import Iterable


def cards_powered_by_runs(
    run_ids: Iterable[str],
    cards: Iterable[dict],
) -> list[dict]:
    """Return [{card_id, base_name, scoring_run_id, status}] for each card
    whose scoring_run_id is in `run_ids`. Cards without scoring_run_id
    (smoke / test cards) are skipped.

    The returned dicts carry only the four link fields — no card secrets,
    quantity, cadence, etc. — so the response is safe to surface to the
    FE confirm modal.
    """
    target = set(run_ids)
    if not target:
        return []
    out: list[dict] = []
    for card in cards:
        scoring_run_id = card.get("scoring_run_id")
        if scoring_run_id and scoring_run_id in target:
            out.append({
                "card_id": card.get("card_id"),
                "base_name": card.get("base_name"),
                "scoring_run_id": scoring_run_id,
                "status": card.get("status"),
            })
    return out
