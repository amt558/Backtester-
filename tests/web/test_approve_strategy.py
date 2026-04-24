"""Unit tests for approve_strategy.score_csv and accept_scored."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tradelab.io.tv_csv import TVCSVParseError
from tradelab.web import approve_strategy


@pytest.fixture
def smoke_csv_text() -> str:
    return Path("tests/io/fixtures/tv_export_amzn_smoke.csv").read_text(encoding="utf-8-sig")


def test_score_csv_happy(tmp_path: Path, smoke_csv_text: str):
    """Happy-path: valid CSV scores, writes report folder + audit row."""
    db_path = tmp_path / "audit.db"
    result = approve_strategy.score_csv(
        csv_text=smoke_csv_text,
        pine_source="// pine stub",
        symbol="AMZN",
        base_name="smoke-amzn",
        timeframe="1H",
        reports_root=tmp_path / "reports",
        db_path=db_path,
    )
    # Contract: returns a dict with the keys the frontend needs.
    for key in (
        "verdict", "metrics", "report_folder", "scoring_run_id",
        "dsr_probability", "n_trades", "start_date", "end_date",
    ):
        assert key in result, f"missing key {key!r} in score_csv result"

    assert result["verdict"] in ("ROBUST", "INCONCLUSIVE", "FRAGILE")
    assert isinstance(result["scoring_run_id"], str) and result["scoring_run_id"]
    assert Path(result["report_folder"]).exists()
    assert (Path(result["report_folder"]) / "strategy.pine").read_text() == "// pine stub"
    assert (Path(result["report_folder"]) / "tv_trades.csv").read_text(encoding="utf-8") == smoke_csv_text
    assert result["n_trades"] > 0


def test_score_csv_bad_csv_raises_tv_parse_error(tmp_path: Path):
    with pytest.raises(TVCSVParseError):
        approve_strategy.score_csv(
            csv_text="not a csv at all",
            pine_source=None, symbol="AMZN", base_name="x", timeframe="1D",
            reports_root=tmp_path / "reports",
            db_path=tmp_path / "a.db",
        )


def test_score_csv_zero_closed_trades_surfaces_tv_parse_error(tmp_path: Path):
    """CSV with only entry rows (no exits) -> zero closed trades."""
    # One entry-only trade (no matching exit row)
    csv = (
        "Trade #,Type,Signal,Date/Time,Price USD,Contracts,Profit USD,Profit %,"
        "Cumulative profit USD,Cumulative profit %,Run-up USD,Run-up %,Drawdown USD,Drawdown %\n"
        "1,Entry long,Long,2024-01-08 09:30,150.00,10,,,,,,,,\n"
    )
    with pytest.raises(TVCSVParseError, match="no closed trades"):
        approve_strategy.score_csv(
            csv_text=csv,
            pine_source=None, symbol="AMZN", base_name="x", timeframe="1D",
            reports_root=tmp_path / "reports",
            db_path=tmp_path / "a.db",
        )


def _score_once(smoke_csv_text: str, tmp_path: Path, base_name: str) -> dict:
    """Helper: run score_csv and return its result dict."""
    return approve_strategy.score_csv(
        csv_text=smoke_csv_text,
        pine_source="// pine stub",
        symbol="AMZN", base_name=base_name, timeframe="1H",
        reports_root=tmp_path / "reports",
        db_path=tmp_path / "audit.db",
    )


def test_accept_scored_happy(tmp_path: Path, smoke_csv_text: str):
    from tradelab.live.cards import CardRegistry
    scored = _score_once(smoke_csv_text, tmp_path, "smoke-amzn")
    registry = CardRegistry(tmp_path / "cards.json")

    result = approve_strategy.accept_scored(
        base_name="smoke-amzn", symbol="AMZN", timeframe="1H",
        report_folder=scored["report_folder"],
        verdict=scored["verdict"],
        dsr_probability=scored["dsr_probability"],
        scoring_run_id=scored["scoring_run_id"],
        registry=registry,
        pine_archive_root=tmp_path / "pine_archive",
        reports_root=tmp_path / "reports",
    )
    assert result["card_id"] == "smoke-amzn-v1"
    assert isinstance(result["secret"], str) and len(result["secret"]) >= 30
    archive = Path(result["pine_archive_path"])
    assert (archive / "strategy.pine").exists()
    assert (archive / "tv_trades.csv").exists()
    verdict_json = json.loads((archive / "verdict.json").read_text(encoding="utf-8"))
    assert verdict_json["card_id"] == "smoke-amzn-v1"
    assert verdict_json["base_name"] == "smoke-amzn"
    assert verdict_json["version"] == 1

    card = registry.get("smoke-amzn-v1")
    assert card is not None
    assert card["status"] == "disabled"
    assert card["symbol"] == "AMZN"
    assert card["version"] == 1
    assert card["base_name"] == "smoke-amzn"
    assert card["secret"] == result["secret"]


def test_accept_scored_bumps_version_on_reuse(tmp_path: Path, smoke_csv_text: str):
    from tradelab.live.cards import CardRegistry
    registry = CardRegistry(tmp_path / "cards.json")

    scored1 = _score_once(smoke_csv_text, tmp_path, "smoke-amzn")
    r1 = approve_strategy.accept_scored(
        base_name="smoke-amzn", symbol="AMZN", timeframe="1H",
        report_folder=scored1["report_folder"],
        verdict=scored1["verdict"],
        dsr_probability=scored1["dsr_probability"],
        scoring_run_id=scored1["scoring_run_id"],
        registry=registry,
        pine_archive_root=tmp_path / "pine_archive",
        reports_root=tmp_path / "reports",
    )
    scored2 = _score_once(smoke_csv_text, tmp_path, "smoke-amzn")
    r2 = approve_strategy.accept_scored(
        base_name="smoke-amzn", symbol="AMZN", timeframe="1H",
        report_folder=scored2["report_folder"],
        verdict=scored2["verdict"],
        dsr_probability=scored2["dsr_probability"],
        scoring_run_id=scored2["scoring_run_id"],
        registry=registry,
        pine_archive_root=tmp_path / "pine_archive",
        reports_root=tmp_path / "reports",
    )
    assert r1["card_id"] == "smoke-amzn-v1"
    assert r2["card_id"] == "smoke-amzn-v2"
    # Two distinct Pine archive dirs
    assert r1["pine_archive_path"] != r2["pine_archive_path"]


def test_accept_scored_refuses_report_folder_outside_reports_root(tmp_path: Path, smoke_csv_text: str):
    """Paranoid path check — reject report_folder not under reports_root."""
    from tradelab.live.cards import CardRegistry
    scored = _score_once(smoke_csv_text, tmp_path, "smoke-amzn")
    registry = CardRegistry(tmp_path / "cards.json")

    # A different root that doesn't contain the report folder
    bogus_root = tmp_path / "bogus"
    bogus_root.mkdir()
    with pytest.raises(FileNotFoundError, match="report folder"):
        approve_strategy.accept_scored(
            base_name="smoke-amzn", symbol="AMZN", timeframe="1H",
            report_folder=scored["report_folder"],
            verdict=scored["verdict"],
            dsr_probability=scored["dsr_probability"],
            scoring_run_id=scored["scoring_run_id"],
            registry=registry,
            pine_archive_root=tmp_path / "pine_archive",
            reports_root=bogus_root,
        )


def test_accept_scored_refuses_missing_pine(tmp_path: Path, smoke_csv_text: str):
    """If the report folder has no strategy.pine, refuse."""
    from tradelab.live.cards import CardRegistry
    # Score WITHOUT pine_source
    scored = approve_strategy.score_csv(
        csv_text=smoke_csv_text,
        pine_source=None,
        symbol="AMZN", base_name="smoke-amzn", timeframe="1H",
        reports_root=tmp_path / "reports",
        db_path=tmp_path / "audit.db",
    )
    registry = CardRegistry(tmp_path / "cards.json")
    with pytest.raises(ValueError, match="no strategy.pine"):
        approve_strategy.accept_scored(
            base_name="smoke-amzn", symbol="AMZN", timeframe="1H",
            report_folder=scored["report_folder"],
            verdict=scored["verdict"],
            dsr_probability=scored["dsr_probability"],
            scoring_run_id=scored["scoring_run_id"],
            registry=registry,
            pine_archive_root=tmp_path / "pine_archive",
            reports_root=tmp_path / "reports",
        )


def test_accept_scored_rolls_back_pine_archive_on_registry_failure(
    tmp_path: Path, smoke_csv_text: str, monkeypatch,
):
    from tradelab.live.cards import CardRegistry, CardExistsError
    scored = _score_once(smoke_csv_text, tmp_path, "smoke-amzn")
    registry = CardRegistry(tmp_path / "cards.json")

    def boom(self, card_id, data):
        raise CardExistsError(card_id)
    monkeypatch.setattr(CardRegistry, "create", boom)

    with pytest.raises(CardExistsError):
        approve_strategy.accept_scored(
            base_name="smoke-amzn", symbol="AMZN", timeframe="1H",
            report_folder=scored["report_folder"],
            verdict=scored["verdict"],
            dsr_probability=scored["dsr_probability"],
            scoring_run_id=scored["scoring_run_id"],
            registry=registry,
            pine_archive_root=tmp_path / "pine_archive",
            reports_root=tmp_path / "reports",
        )
    # Pine archive dir must have been cleaned up
    archive_root = tmp_path / "pine_archive"
    assert not archive_root.exists() or not any(archive_root.iterdir())
