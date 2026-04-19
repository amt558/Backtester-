"""Canary-health aggregator tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from tradelab import cli_canary
from tradelab.audit import record_run
from tradelab.audit.history import DEFAULT_DB_PATH


@pytest.fixture(autouse=True)
def _chdir_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    yield


def test_canary_health_writes_html_when_no_history(tmp_path):
    out = tmp_path / "canary.html"
    cli_canary.canary_health(out=out, open_browser=False)
    assert out.exists()
    html = out.read_text()
    assert "tradelab canary health" in html
    assert "never run" in html


def test_canary_health_picks_up_recorded_rows(tmp_path):
    # Record one row for rand_canary — it should appear in the aggregator
    record_run("rand_canary", verdict="FRAGILE", dsr_probability=0.2,
               db_path=tmp_path / "data" / "tradelab_history.db")
    # The canary-health CLI uses the default DB path; point it there by chdir
    # tmp_path is already cwd via fixture → DEFAULT_DB_PATH resolves inside tmp
    out = tmp_path / "canary.html"
    cli_canary.canary_health(out=out, open_browser=False)
    html = out.read_text()
    assert "rand_canary" in html
    assert "FRAGILE" in html


def test_canary_health_flags_robust_verdict_as_broken(tmp_path):
    # A canary showing ROBUST = tool broken; aggregator must flag it
    record_run("leak_canary", verdict="ROBUST", dsr_probability=0.99,
               db_path=tmp_path / "data" / "tradelab_history.db")
    out = tmp_path / "canary.html"
    cli_canary.canary_health(out=out, open_browser=False)
    html = out.read_text()
    assert "CANARY PRODUCED ROBUST" in html
    assert "BROKEN" in html


def test_canary_health_prints_all_four_canaries():
    # Smoke: the HTML should mention all 4 canary names even if empty
    html = cli_canary._build_html()
    for name in ("rand_canary", "overfit_canary", "leak_canary", "survivor_canary"):
        assert name in html
