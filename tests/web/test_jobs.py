"""Tests for tradelab.web.jobs — job manager."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tradelab.web import jobs


@pytest.fixture
def jm(tmp_path, monkeypatch):
    """Fresh JobManager with state under tmp_path/.cache."""
    cache = tmp_path / ".cache"
    cache.mkdir()
    return jobs.JobManager(cache_root=cache)


def test_job_dataclass_has_expected_fields():
    j = jobs.Job(
        id="abc",
        strategy="momo",
        command="run --robustness",
        argv=["run", "momo", "--robustness"],
        status=jobs.JobStatus.QUEUED,
    )
    assert j.id == "abc"
    assert j.status == jobs.JobStatus.QUEUED
    assert j.pid is None
    assert j.exit_code is None
    assert j.started_at is None
    assert j.ended_at is None


def test_atomic_write_creates_then_replaces(tmp_path):
    target = tmp_path / "jobs.json"
    jobs._atomic_write_json(target, {"hello": "world"})
    assert target.exists()
    assert json.loads(target.read_text())["hello"] == "world"
    # second write replaces
    jobs._atomic_write_json(target, {"hello": "again"})
    assert json.loads(target.read_text())["hello"] == "again"
    # tmp file should not be left behind
    assert not (tmp_path / "jobs.json.tmp").exists()
