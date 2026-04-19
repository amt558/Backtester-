"""tradelab doctor self-test command tests."""
from __future__ import annotations

from unittest.mock import patch

import pytest
import typer

from tradelab import cli_doctor


def test_doctor_runs_all_checks(capsys, tmp_path, monkeypatch):
    """All checks should at least execute without raising."""
    monkeypatch.chdir(tmp_path)
    # Provide a minimal yaml so config check can succeed
    (tmp_path / "tradelab.yaml").write_text(
        "paths:\n  data_dir: ./_d\n  reports_dir: ./_r\n  cache_dir: ./_c\n"
        "strategies:\n  s2_pocket_pivot:\n"
        "    module: tradelab.strategies.s2_pocket_pivot\n"
        "    class_name: S2PocketPivot\n"
        "    status: ported\n"
    )
    from tradelab import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "_config", None)
    monkeypatch.setenv("TWELVEDATA_API_KEY", "fake_for_test")

    # Doctor may exit nonzero if some optional check fails; we don't care here.
    try:
        cli_doctor.doctor()
    except typer.Exit:
        pass

    out = capsys.readouterr().out
    # Every check name should appear
    for name in ("python", "deps_req", "td_key", "config", "strategies",
                  "cache", "audit_db", "canaries"):
        assert name in out


def test_doctor_python_version_check_passes():
    ok, msg = cli_doctor._check_python_version()
    assert ok
    assert "Python" in msg


def test_doctor_required_imports_present():
    ok, _ = cli_doctor._check_required_imports()
    assert ok


def test_doctor_td_key_missing_is_fail(monkeypatch):
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    from tradelab import env as env_mod
    monkeypatch.setattr(env_mod, "_LOADED", True)
    ok, msg = cli_doctor._check_twelvedata_key()
    assert not ok
    assert "TWELVEDATA_API_KEY" in msg


def test_doctor_td_key_present_is_ok(monkeypatch):
    monkeypatch.setenv("TWELVEDATA_API_KEY", "x")
    ok, msg = cli_doctor._check_twelvedata_key()
    assert ok


def test_doctor_canary_check_flags_robust(tmp_path, monkeypatch):
    """If a canary's most-recent verdict is ROBUST, the canary check fails."""
    monkeypatch.chdir(tmp_path)
    from tradelab.audit import record_run
    record_run("rand_canary", verdict="ROBUST", db_path=tmp_path/"data"/"tradelab_history.db")
    ok, msg = cli_doctor._check_canary_recently_passed()
    assert not ok
    assert "rand_canary" in msg


def test_doctor_critical_failure_exits_nonzero(tmp_path, monkeypatch):
    """If a critical check fails, doctor() raises typer.Exit."""
    monkeypatch.chdir(tmp_path)
    # No tradelab.yaml → config check fails → critical → exit
    from tradelab import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "_config", None)
    with pytest.raises(typer.Exit):
        cli_doctor.doctor()
