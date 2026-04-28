"""Test the backfill script's dry-run, apply, and skip-existing behavior."""
from __future__ import annotations
from pathlib import Path
import pytest
from tradelab.scripts import backfill_returns


def _make_card(archive_root: Path, card_id: str, with_existing_returns: bool = False) -> Path:
    """Set up a card_dir with tv_trades.csv and optionally returns.csv."""
    card = archive_root / card_id
    card.mkdir(parents=True, exist_ok=True)
    (card / "tv_trades.csv").write_text(
        "Trade #,Type,Signal,Date/Time,Price USD,Contracts,Profit USD,Profit %\n"
        "1,Entry long,enter,2026-01-05 09:30,100.00,10,,\n"
        "1,Exit long,exit,2026-01-05 11:00,103.00,10,30.00,3.00\n",
        encoding="utf-8",
    )
    if with_existing_returns:
        (card / "returns.csv").write_text("date,return_pct\n2026-01-05,99.99\n", encoding="utf-8")
    return card


def test_dry_run_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    _make_card(tmp_path, "alpha-v1")
    rc = backfill_returns.main(["--archive-root", str(tmp_path)])
    assert rc == 0
    assert not (tmp_path / "alpha-v1" / "returns.csv").exists()
    out = capsys.readouterr().out
    assert "would write" in out


def test_apply_writes_returns(tmp_path: Path) -> None:
    _make_card(tmp_path, "alpha-v1")
    rc = backfill_returns.main(["--archive-root", str(tmp_path), "--apply"])
    assert rc == 0
    assert (tmp_path / "alpha-v1" / "returns.csv").exists()


def test_apply_skips_existing_without_force(tmp_path: Path) -> None:
    _make_card(tmp_path, "alpha-v1", with_existing_returns=True)
    rc = backfill_returns.main(["--archive-root", str(tmp_path), "--apply"])
    assert rc == 0
    # File should still contain the sentinel value (99.99), unchanged.
    assert "99.99" in (tmp_path / "alpha-v1" / "returns.csv").read_text(encoding="utf-8")


def test_apply_force_overwrites(tmp_path: Path) -> None:
    _make_card(tmp_path, "alpha-v1", with_existing_returns=True)
    rc = backfill_returns.main(["--archive-root", str(tmp_path), "--apply", "--force"])
    assert rc == 0
    text = (tmp_path / "alpha-v1" / "returns.csv").read_text(encoding="utf-8")
    assert "99.99" not in text
    assert "3.00" in text
