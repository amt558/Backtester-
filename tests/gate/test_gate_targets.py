"""Tests for the merge-gate artifacts: the cp3 confinement helper and the
gate-fast NOT-a-merge-gate label.

Per the gate brief §6: exercise the confinement script logic against *fabricated*
junitxml. Do NOT shell out to run the real full gate here -- that is a live-run
verification step (§7), not a unit test.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFINE_PATH = REPO_ROOT / "scripts" / "gate_confine.py"
GATE_FAST_PATH = REPO_ROOT / "scripts" / "gate-fast.ps1"


def _load_confine():
    """Load scripts/gate_confine.py by path (repo-root scripts/ is not on sys.path)."""
    spec = importlib.util.spec_from_file_location("gate_confine", CONFINE_PATH)
    assert spec is not None and spec.loader is not None, f"cannot load {CONFINE_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _split(nodeid: str) -> tuple[str, str]:
    """Convert a pytest nodeid into junitxml (classname, name) attributes."""
    file_part, name = nodeid.split("::", 1)
    classname = file_part[:-len(".py")].replace("/", ".")
    return classname, name


def _write_junit(path: Path, failing=(), passing=()) -> Path:
    """Fabricate a pytest junitxml report with the given failing/passing nodeids."""
    cases = []
    for nodeid in passing:
        cls, name = _split(nodeid)
        cases.append(f'<testcase classname="{cls}" name="{name}" time="0.001" />')
    for nodeid in failing:
        cls, name = _split(nodeid)
        cases.append(
            f'<testcase classname="{cls}" name="{name}" time="0.001">'
            f'<failure message="boom">AssertionError: boom</failure></testcase>'
        )
    body = "\n".join(cases)
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<testsuites><testsuite name="pytest" tests="{len(cases)}">\n'
        f"{body}\n</testsuite></testsuites>\n",
        encoding="utf-8",
    )
    return path


def test_only_tracked_reds_passes(tmp_path):
    """Exactly the 3 tracked B2 reds failing (plus green tests) -> confined, exit 0."""
    confine = _load_confine()
    junit = _write_junit(
        tmp_path / "j.xml",
        failing=confine.TRACKED_B2_REDS,
        passing=["tests/robustness/test_verdict.py::test_engine_ok"],
    )
    assert confine.main(["--junitxml", str(junit)]) == 0


def test_extra_failure_in_other_file_fails(tmp_path):
    """A failure outside the web file is always real -> exit non-zero."""
    confine = _load_confine()
    junit = _write_junit(
        tmp_path / "j.xml",
        failing=list(confine.TRACKED_B2_REDS)
        + ["tests/robustness/test_verdict.py::test_regression"],
    )
    assert confine.main(["--junitxml", str(junit)]) != 0


def test_untracked_failure_inside_web_file_fails(tmp_path):
    """A 4th failure inside the web file that is NOT a tracked red -> exit non-zero."""
    confine = _load_confine()
    junit = _write_junit(
        tmp_path / "j.xml",
        failing=list(confine.TRACKED_B2_REDS)
        + ["tests/web/test_command_center_html.py::test_some_new_assertion"],
    )
    assert confine.main(["--junitxml", str(junit)]) != 0


def test_all_green_passes(tmp_path):
    """No failures at all -> exit 0."""
    confine = _load_confine()
    junit = _write_junit(
        tmp_path / "j.xml",
        passing=[
            "tests/robustness/test_verdict.py::test_a",
            "tests/web/test_command_center_html.py::test_b",
        ],
    )
    assert confine.main(["--junitxml", str(junit)]) == 0


def test_tracked_reds_are_exactly_three_and_pinned_once():
    """The tracked-red list is the single source of truth: exactly 3 web-file IDs."""
    confine = _load_confine()
    assert len(confine.TRACKED_B2_REDS) == 3
    assert len(set(confine.TRACKED_B2_REDS)) == 3
    for nodeid in confine.TRACKED_B2_REDS:
        assert nodeid.startswith("tests/web/test_command_center_html.py::"), nodeid


def test_tracked_reds_match_live_test_ids():
    """Pinned IDs must be real, collectable tests -- guards against drift/typos."""
    confine = _load_confine()
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            "tests/web/test_command_center_html.py",
            "--collect-only", "-q", "-p", "no:cacheprovider",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    collected = result.stdout
    for nodeid in confine.TRACKED_B2_REDS:
        assert nodeid in collected, (
            f"pinned tracked red not found in live collection: {nodeid}"
        )


def test_gate_fast_carries_not_a_merge_gate_label():
    """gate-fast must visibly declare it is NOT a merge gate so cp3 is never dropped."""
    text = GATE_FAST_PATH.read_text(encoding="utf-8")
    assert "NOT a merge gate" in text
