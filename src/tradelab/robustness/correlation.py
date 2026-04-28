"""Pairwise correlation engine for portfolio health and score-modal fit gate.

Two public entry points:
- compute_pairwise_correlations(archive_root, card_ids) -- Portfolio Health
- compute_candidate_vs_cohort(archive_root, candidate_returns, cohort_card_ids) -- Score modal

Reads pine_archive/<card_id>/returns.csv (written by T1 returns persistence).
Returns PortfolioHealthResult with PairResult entries.

entry_overlap is hardcoded 0.0 for now; requires intra-day timestamps in
returns.csv schema which are not yet stored.
"""
from __future__ import annotations

import csv
import itertools
import math
from pathlib import Path
from typing import Sequence

from pydantic import BaseModel


class PairResult(BaseModel):
    """Correlation metrics for one card-pair."""

    a: str
    b: str
    return_rho: float
    dd_rho: float
    entry_overlap: float  # always 0.0 until intra-day timestamps exist
    n_aligned: int  # number of overlapping dates used


class PortfolioHealthResult(BaseModel):
    """Aggregate portfolio correlation result."""

    pairs: list[PairResult]
    max_return_rho: float
    max_dd_rho: float
    max_entry_overlap: float


# Minimum aligned-date count required to compute a meaningful pair.
_MIN_ALIGNED = 5


def _load_returns(returns_csv: Path) -> dict[str, float]:
    """Read returns.csv -> {date: return_pct}. Returns {} if file missing/empty."""
    if not returns_csv.exists():
        return {}
    out: dict[str, float] = {}
    with returns_csv.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                out[row["date"]] = float(row["return_pct"])
            except (KeyError, ValueError):
                continue
    return out


def _safe_pearson(xs: list[float], ys: list[float]) -> float:
    """Pearson r for paired lists. Returns 0.0 when std(x)=0 or std(y)=0."""
    n = len(xs)
    if n == 0:
        return 0.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / n
    std_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs) / n)
    std_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys) / n)
    if std_x == 0.0 or std_y == 0.0:
        return 0.0
    return cov / (std_x * std_y)


def _drawdown_series(returns: list[float]) -> list[float]:
    """Compute running drawdown (%) from a daily-returns list.

    Cumulative equity starts at 100; drawdown at each step is:
        (peak - current) / peak * 100
    """
    equity = 100.0
    peak = 100.0
    dds: list[float] = []
    for r in returns:
        equity *= 1.0 + r / 100.0
        if equity > peak:
            peak = equity
        dds.append((peak - equity) / peak * 100.0)
    return dds


def _compute_pair_result(
    a_label: str,
    b_label: str,
    a_series: dict[str, float],
    b_series: dict[str, float],
) -> PairResult | None:
    """Compute PairResult for two return series (as date->return_pct dicts).

    Returns None if the series have fewer than _MIN_ALIGNED overlapping dates.
    """
    common_dates = sorted(set(a_series) & set(b_series))
    if len(common_dates) < _MIN_ALIGNED:
        return None

    a_vals = [a_series[d] for d in common_dates]
    b_vals = [b_series[d] for d in common_dates]

    return_rho = _safe_pearson(a_vals, b_vals)

    a_dd = _drawdown_series(a_vals)
    b_dd = _drawdown_series(b_vals)
    dd_rho = _safe_pearson(a_dd, b_dd)

    return PairResult(
        a=a_label,
        b=b_label,
        return_rho=round(return_rho, 4),
        dd_rho=round(dd_rho, 4),
        entry_overlap=0.0,
        n_aligned=len(common_dates),
    )


def compute_pairwise_correlations(
    archive_root: Path,
    card_ids: Sequence[str],
) -> PortfolioHealthResult:
    """Compute all unordered pairwise correlations across card_ids.

    Args:
        archive_root: Path to pine_archive/ directory.
        card_ids:     Card IDs to include (typically all enabled cards).

    Returns:
        PortfolioHealthResult with one PairResult per sufficiently-overlapping pair.
        Pairs with fewer than _MIN_ALIGNED overlapping dates are silently skipped.
        Missing returns.csv files are silently skipped.
    """
    archive_root = Path(archive_root)

    # Load all series first to avoid repeated I/O.
    series: dict[str, dict[str, float]] = {}
    for cid in card_ids:
        csv_path = archive_root / cid / "returns.csv"
        loaded = _load_returns(csv_path)
        if loaded:
            series[cid] = loaded

    pairs: list[PairResult] = []
    for a_id, b_id in itertools.combinations(list(series.keys()), 2):
        pair = _compute_pair_result(a_id, b_id, series[a_id], series[b_id])
        if pair is not None:
            pairs.append(pair)

    if pairs:
        max_return_rho = max(p.return_rho for p in pairs)
        max_dd_rho = max(p.dd_rho for p in pairs)
        max_entry_overlap = max(p.entry_overlap for p in pairs)
    else:
        max_return_rho = 0.0
        max_dd_rho = 0.0
        max_entry_overlap = 0.0

    return PortfolioHealthResult(
        pairs=pairs,
        max_return_rho=max_return_rho,
        max_dd_rho=max_dd_rho,
        max_entry_overlap=max_entry_overlap,
    )


def compute_candidate_vs_cohort(
    archive_root: Path,
    candidate_returns: Sequence[tuple[str, float]],
    cohort_card_ids: Sequence[str],
    *,
    exclude_card_id: str | None = None,
) -> PortfolioHealthResult:
    """Compute correlation between a candidate (in-memory) and each cohort card.

    Used by the Score modal to show how a run under review correlates with
    the live portfolio before accept/reject.

    Args:
        archive_root:     Path to pine_archive/ directory.
        candidate_returns: List of (date, return_pct) tuples for the candidate run.
        cohort_card_ids:  Card IDs of the live portfolio to correlate against.
        exclude_card_id:  If provided, remove this card_id from the cohort before
                          pairing. Use when the candidate run belongs to an already-
                          enabled card — avoids self-correlation that would pollute
                          max_return_rho with a spurious 1.0.

    Returns:
        PortfolioHealthResult where pair.a == "candidate" for every PairResult.
    """
    archive_root = Path(archive_root)
    if exclude_card_id is not None:
        cohort_card_ids = [c for c in cohort_card_ids if c != exclude_card_id]
    candidate_series: dict[str, float] = {d: r for d, r in candidate_returns}

    pairs: list[PairResult] = []
    for cid in cohort_card_ids:
        csv_path = archive_root / cid / "returns.csv"
        cohort_series = _load_returns(csv_path)
        if not cohort_series:
            continue
        pair = _compute_pair_result("candidate", cid, candidate_series, cohort_series)
        if pair is not None:
            pairs.append(pair)

    if pairs:
        max_return_rho = max(p.return_rho for p in pairs)
        max_dd_rho = max(p.dd_rho for p in pairs)
        max_entry_overlap = max(p.entry_overlap for p in pairs)
    else:
        max_return_rho = 0.0
        max_dd_rho = 0.0
        max_entry_overlap = 0.0

    return PortfolioHealthResult(
        pairs=pairs,
        max_return_rho=max_return_rho,
        max_dd_rho=max_dd_rho,
        max_entry_overlap=max_entry_overlap,
    )
