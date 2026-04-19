"""Tests for the .env loader."""
from __future__ import annotations

from pathlib import Path

import pytest

from tradelab import env as env_mod


@pytest.fixture(autouse=True)
def _reset_loaded():
    env_mod._LOADED = False
    yield
    env_mod._LOADED = False


def test_load_env_from_repo_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Anchor: tradelab.yaml marks repo root
    (tmp_path / "tradelab.yaml").write_text("paths: {}")
    (tmp_path / ".env").write_text(
        "TWELVEDATA_API_KEY=test_key_abc\n"
        "OTHER_VAR=hello\n"
    )
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    monkeypatch.delenv("OTHER_VAR", raising=False)
    loaded = env_mod.load_env(reload=True)
    assert loaded.get("TWELVEDATA_API_KEY") == "test_key_abc"
    assert loaded.get("OTHER_VAR") == "hello"


def test_load_env_preserves_existing_environ(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tradelab.yaml").write_text("paths: {}")
    (tmp_path / ".env").write_text("TWELVEDATA_API_KEY=from_file\n")
    monkeypatch.setenv("TWELVEDATA_API_KEY", "from_shell")
    loaded = env_mod.load_env(reload=True)
    # Existing env wins
    assert "TWELVEDATA_API_KEY" not in loaded
    import os
    assert os.environ["TWELVEDATA_API_KEY"] == "from_shell"


def test_load_env_handles_quotes_and_comments(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tradelab.yaml").write_text("paths: {}")
    (tmp_path / ".env").write_text(
        "# this is a comment\n"
        "\n"
        'QUOTED="value with spaces"\n'
        "SINGLE='single-quoted'\n"
        "UNQUOTED=plainvalue\n"
        "EXPORT_PREFIX=export KEY=value\n"   # "export " prefix is optional
        "export REAL_EXPORT=yes\n"
    )
    for k in ("QUOTED", "SINGLE", "UNQUOTED", "REAL_EXPORT"):
        monkeypatch.delenv(k, raising=False)
    loaded = env_mod.load_env(reload=True)
    assert loaded.get("QUOTED") == "value with spaces"
    assert loaded.get("SINGLE") == "single-quoted"
    assert loaded.get("UNQUOTED") == "plainvalue"
    assert loaded.get("REAL_EXPORT") == "yes"


def test_load_env_no_file_is_silent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tradelab.yaml").write_text("paths: {}")
    # No .env file present
    loaded = env_mod.load_env(reload=True)
    assert loaded == {}


def test_load_env_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tradelab.yaml").write_text("paths: {}")
    (tmp_path / ".env").write_text("TRADELAB_TEST_KEY=x\n")
    monkeypatch.delenv("TRADELAB_TEST_KEY", raising=False)
    env_mod.load_env(reload=True)
    # Second call with reload=False should be a no-op
    second = env_mod.load_env()
    assert second == {}
