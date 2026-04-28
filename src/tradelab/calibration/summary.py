"""Calibration summary — aggregate card outcomes for the dashboard banner.

Answers three operational questions across accepted cards still within the
observation window:
  1. How many tripped tracking-error below 0.60 within their first 30 live days?
  2. How many were manually disabled within 60 days of acceptance?
  3. What is the median PF gap (1 - te) across live cards?

Designed so that the "insufficient sample" path returns honest sparse data
rather than misleading zeros.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from pydantic import BaseModel


# TE threshold below which a strategy is considered to have tripped.
_TE_TRIP_THRESHOLD = 0.60

# Default observation window: 90 days from acceptance.
_DEFAULT_WINDOW_DAYS = 90


class CalibrationSummaryResult(BaseModel):
    n_accepted: int
    n_te_tripped_30d: int
    n_disabled_60d: int
    median_pf_gap: Optional[float]


def is_te_tripped_within_30d(te_result: dict) -> bool:
    """Return True if any value in the first 30 entries of decay_series < 0.60.

    Returns False for insufficient/missing data.
    """
    if te_result.get("status") != "ok":
        return False
    series = te_result.get("decay_series")
    if not series:
        return False
    # Take first 30 values (proxy for first 30 live trading days)
    window = series[:30]
    return any(v < _TE_TRIP_THRESHOLD for v in window)


def _parse_utc(ts: str) -> datetime:
    """Parse ISO-8601 timestamp, handling both 'Z' and '+00:00' suffixes."""
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)


def summarize_calibration(
    cards: list[dict],
    te_loader: Callable[[str], dict],
    window_days: int = _DEFAULT_WINDOW_DAYS,
) -> CalibrationSummaryResult:
    """Aggregate calibration metrics across accepted cards within window.

    Parameters
    ----------
    cards:
        List of card dicts. Each should have ``card_id``, ``accepted_bool``
        (True/False; absent defaults to True since all registry cards are
        accepted), ``created_at`` (ISO-8601), and optionally ``status``.
    te_loader:
        Callable mapping card_id → TE result dict (shape from
        compute_tracking_error.model_dump()).
    window_days:
        Cards older than this many days from now are excluded.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=window_days)

    n_accepted = 0
    n_te_tripped_30d = 0
    n_disabled_60d = 0
    pf_gaps: list[float] = []

    for card in cards:
        # Default accepted_bool to True — all cards in the registry were
        # accepted; the field is only False in synthetic test data.
        accepted = card.get("accepted_bool", True)
        if not accepted:
            continue

        created_raw = card.get("created_at")
        if created_raw:
            try:
                created_at = _parse_utc(created_raw)
            except (ValueError, TypeError):
                created_at = None
        else:
            created_at = None

        # Skip cards outside the observation window.
        if created_at is not None and created_at < cutoff:
            continue

        n_accepted += 1

        # TE trip check (first 30 days of decay_series).
        card_id = card.get("card_id", "")
        te_result = te_loader(card_id)
        if is_te_tripped_within_30d(te_result):
            n_te_tripped_30d += 1

        # PF gap: 1 - te  (only when TE available and status is ok).
        if te_result.get("status") == "ok":
            te_val = te_result.get("te")
            if te_val is not None:
                pf_gaps.append(1.0 - float(te_val))

        # Disabled within 60d check.
        if card.get("status") == "disabled" and created_at is not None:
            disabled_cutoff = created_at + timedelta(days=60)
            if now <= disabled_cutoff:
                n_disabled_60d += 1

    median_pf_gap: Optional[float] = None
    if len(pf_gaps) >= 1:
        median_pf_gap = statistics.median(pf_gaps)

    return CalibrationSummaryResult(
        n_accepted=n_accepted,
        n_te_tripped_30d=n_te_tripped_30d,
        n_disabled_60d=n_disabled_60d,
        median_pf_gap=median_pf_gap,
    )
