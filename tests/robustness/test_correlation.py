"""Test correlation engine: return rho, DD rho, entry-time overlap."""
from __future__ import annotations
from pathlib import Path
import csv
import pytest
from tradelab.robustness.correlation import (
    compute_pairwise_correlations,
    compute_candidate_vs_cohort,
    PortfolioHealthResult,
)


def _write_returns(tmp_path: Path, card_id: str, rows: list[tuple[str, float]]) -> Path:
    """Write pine_archive/<card_id>/returns.csv at tmp_path/pine_archive."""
    archive = tmp_path / "pine_archive" / card_id
    archive.mkdir(parents=True, exist_ok=True)
    p = archive / "returns.csv"
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "return_pct"])
        w.writeheader()
        for d, r in rows:
            w.writerow({"date": d, "return_pct": f"{r:.2f}"})
    return p


def test_two_uncorrelated_cards(tmp_path: Path) -> None:
    _write_returns(tmp_path, "alpha-v1", [(f"2026-01-{i:02d}", (-1.0) ** i * 1.5) for i in range(1, 32)])
    _write_returns(tmp_path, "beta-v1", [(f"2026-01-{i:02d}", 0.5) for i in range(1, 32)])
    result = compute_pairwise_correlations(
        archive_root=tmp_path / "pine_archive",
        card_ids=["alpha-v1", "beta-v1"],
    )
    assert result.max_return_rho < 0.5
    assert len(result.pairs) == 1
    assert result.pairs[0].a in ("alpha-v1", "beta-v1")
    assert result.pairs[0].b != result.pairs[0].a


def test_two_perfectly_correlated_cards(tmp_path: Path) -> None:
    same = [(f"2026-01-{i:02d}", float(i % 5 - 2)) for i in range(1, 32)]
    _write_returns(tmp_path, "alpha-v1", same)
    _write_returns(tmp_path, "beta-v1", same)
    result = compute_pairwise_correlations(
        archive_root=tmp_path / "pine_archive",
        card_ids=["alpha-v1", "beta-v1"],
    )
    assert result.max_return_rho == pytest.approx(1.0, abs=0.01)


def test_single_card_returns_empty_pairs(tmp_path: Path) -> None:
    _write_returns(tmp_path, "alpha-v1", [(f"2026-01-{i:02d}", 1.0) for i in range(1, 32)])
    result = compute_pairwise_correlations(
        archive_root=tmp_path / "pine_archive",
        card_ids=["alpha-v1"],
    )
    assert result.pairs == []
    assert result.max_return_rho == 0.0


def test_missing_card_skipped(tmp_path: Path) -> None:
    _write_returns(tmp_path, "alpha-v1", [(f"2026-01-{i:02d}", 1.0) for i in range(1, 32)])
    # 'missing-v1' has no returns.csv -- should be skipped without error.
    result = compute_pairwise_correlations(
        archive_root=tmp_path / "pine_archive",
        card_ids=["alpha-v1", "missing-v1"],
    )
    assert result.pairs == []


def test_candidate_vs_cohort_basic(tmp_path: Path) -> None:
    """compute_candidate_vs_cohort runs candidate (in-memory) against persisted cohort."""
    _write_returns(tmp_path, "live-1", [(f"2026-01-{i:02d}", 1.0) for i in range(1, 32)])
    candidate = [(f"2026-01-{i:02d}", 1.0) for i in range(1, 32)]
    result = compute_candidate_vs_cohort(
        archive_root=tmp_path / "pine_archive",
        candidate_returns=candidate,
        cohort_card_ids=["live-1"],
    )
    assert len(result.pairs) == 1
    assert result.pairs[0].a == "candidate"
    assert result.pairs[0].b == "live-1"
    # Both series are constant 1.0 -> std=0 -> return_rho should be 0.0 (not nan)
    # Implementation choice: when std=0, return_rho is treated as 0.0
    assert result.pairs[0].return_rho == 0.0


def test_candidate_vs_cohort_excludes_self(tmp_path: Path) -> None:
    """When candidate IS one of the cohort cards, filter it out via exclude_card_id."""
    same = [(f"2026-01-{i:02d}", float(i % 5 - 2)) for i in range(1, 32)]
    _write_returns(tmp_path, "self-card", same)
    _write_returns(tmp_path, "other-card", [(f"2026-01-{i:02d}", 0.5) for i in range(1, 32)])
    result = compute_candidate_vs_cohort(
        archive_root=tmp_path / "pine_archive",
        candidate_returns=same,
        cohort_card_ids=["self-card", "other-card"],
        exclude_card_id="self-card",
    )
    # Only one pair: candidate vs other-card (NOT vs self)
    assert len(result.pairs) == 1
    assert result.pairs[0].b == "other-card"
    # max should reflect the non-self pair
    assert result.max_return_rho < 1.0


def test_candidate_vs_cohort_no_exclude(tmp_path: Path) -> None:
    """When exclude_card_id is None, all cohort cards are paired (existing behavior)."""
    same = [(f"2026-01-{i:02d}", float(i % 5 - 2)) for i in range(1, 32)]
    _write_returns(tmp_path, "card-a", same)
    _write_returns(tmp_path, "card-b", same)
    result = compute_candidate_vs_cohort(
        archive_root=tmp_path / "pine_archive",
        candidate_returns=same,
        cohort_card_ids=["card-a", "card-b"],
    )
    assert len(result.pairs) == 2  # both included
