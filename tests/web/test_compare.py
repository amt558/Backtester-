"""Tests for tradelab.web.compare."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from tradelab.web import compare


def test_rejects_fewer_than_two_run_ids():
    body, status = compare.run_compare(["only_one"])
    assert status == 400
    assert "at least 2" in body["error"]


def test_rejects_invalid_run_id_format():
    body, status = compare.run_compare(["../etc/passwd", "ok_id"])
    assert status == 400
    assert "invalid run_id" in body["error"]


def test_rejects_unknown_run_id(tmp_path):
    with patch("tradelab.web.audit_reader.get_run_folder", return_value=None):
        body, status = compare.run_compare(["valid_a", "valid_b"])
    assert status == 400
    assert "unknown run_id" in body["error"]


def test_rejects_runs_missing_backtest_result_json(tmp_path):
    f1 = tmp_path / "run1"; f1.mkdir()
    f2 = tmp_path / "run2"; f2.mkdir()
    with patch("tradelab.web.audit_reader.get_run_folder",
               side_effect=lambda rid: {"a": f1, "b": f2}.get(rid)):
        body, status = compare.run_compare(["a", "b"])
    assert status == 400
    assert "predate JSON persistence" in body["error"]


def test_happy_path_builds_report(tmp_path):
    f1 = tmp_path / "run1"; f1.mkdir()
    (f1 / "backtest_result.json").write_text("{}")
    f2 = tmp_path / "run2"; f2.mkdir()
    (f2 / "backtest_result.json").write_text("{}")
    reports = tmp_path / "reports"; reports.mkdir()

    fake_proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    with patch("tradelab.web.audit_reader.get_run_folder",
               side_effect=lambda rid: {"a": f1, "b": f2}.get(rid)), \
         patch("subprocess.run", return_value=fake_proc):
        body, status = compare.run_compare(["a", "b"], reports_root=reports)
    assert status == 200
    assert body["error"] is None
    assert re.match(r"^.*compare_\d{8}_\d{6}\.html$", body["data"]["report_path"])


def test_subprocess_non_zero_exit_returns_500():
    fake_proc = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="bad things happened")
    with patch("tradelab.web.audit_reader.get_run_folder", return_value=Path("/fake")), \
         patch.object(Path, "exists", return_value=True), \
         patch("subprocess.run", return_value=fake_proc):
        body, status = compare.run_compare(["a", "b"])
    assert status == 500
    assert "compare exited 1" in body["error"]


def test_subprocess_timeout_returns_500():
    with patch("tradelab.web.audit_reader.get_run_folder", return_value=Path("/fake")), \
         patch.object(Path, "exists", return_value=True), \
         patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=[], timeout=60)):
        body, status = compare.run_compare(["a", "b"])
    assert status == 500
    assert "timeout" in body["error"]
