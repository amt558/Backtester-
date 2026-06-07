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


# TRACKED_B2_REDS is empty post-B2 (cp3 is a clean binary). The confinement
# LOGIC is still worth testing, so the behavioural tests below monkeypatch a
# synthetic tracked ID rather than relying on the (now-empty) production set --
# otherwise they would pass vacuously and silently stop guarding the gate.
_FAKE_TRACKED = ("tests/web/test_command_center_html.py::test_fake_confined_red",)


def test_only_tracked_reds_passes(tmp_path, monkeypatch):
    """Only the (synthetic) tracked reds failing, plus green tests -> confined, exit 0."""
    confine = _load_confine()
    monkeypatch.setattr(confine, "TRACKED_B2_REDS", _FAKE_TRACKED)
    junit = _write_junit(
        tmp_path / "j.xml",
        failing=_FAKE_TRACKED,
        passing=["tests/robustness/test_verdict.py::test_engine_ok"],
    )
    assert confine.main(["--junitxml", str(junit)]) == 0


def test_extra_failure_in_other_file_fails(tmp_path, monkeypatch):
    """A failure outside the confined set (other file) is always real -> exit non-zero."""
    confine = _load_confine()
    monkeypatch.setattr(confine, "TRACKED_B2_REDS", _FAKE_TRACKED)
    junit = _write_junit(
        tmp_path / "j.xml",
        failing=list(_FAKE_TRACKED)
        + ["tests/robustness/test_verdict.py::test_regression"],
    )
    assert confine.main(["--junitxml", str(junit)]) != 0


def test_untracked_failure_inside_web_file_fails(tmp_path, monkeypatch):
    """A failure inside the web file that is NOT confined -> exit non-zero."""
    confine = _load_confine()
    monkeypatch.setattr(confine, "TRACKED_B2_REDS", _FAKE_TRACKED)
    junit = _write_junit(
        tmp_path / "j.xml",
        failing=list(_FAKE_TRACKED)
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


def test_empty_tracked_reds_means_any_failure_fails(tmp_path):
    """Clean-binary property: with the REAL (now-empty) TRACKED_B2_REDS, ANY
    failure -- even a former B2 red -- is unconfined and fails cp3. This is what
    'cp3 is a clean binary' means post-B2."""
    confine = _load_confine()
    assert confine.TRACKED_B2_REDS == ()  # this test is only meaningful while empty
    junit = _write_junit(
        tmp_path / "j.xml",
        failing=[
            "tests/web/test_command_center_html.py"
            "::test_v3_task14_trash_button_tooltip_says_delete_not_archive"
        ],
        passing=["tests/robustness/test_verdict.py::test_engine_ok"],
    )
    assert confine.main(["--junitxml", str(junit)]) != 0


def test_tracked_reds_empty_clean_binary():
    """Post-B2 the confinement list is EMPTY: cp3 is a clean binary with no
    confined exceptions. (Was 'exactly three' while the B2 reds were pinned.)"""
    confine = _load_confine()
    assert confine.TRACKED_B2_REDS == ()
    assert isinstance(confine.TRACKED_B2_REDS, tuple)


def test_tracked_reds_match_live_test_ids():
    """Any pinned tracked red must be a real, collectable test -- guards against
    drift/typos. With the list empty (clean binary) this also asserts the live
    collection mechanism itself still works, so the guard re-activates correctly
    if IDs are ever re-pinned."""
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
    assert "test_command_center_html" in collected, (
        "live collection mechanism broken -- cannot validate pinned tracked reds"
    )
    for nodeid in confine.TRACKED_B2_REDS:
        assert nodeid in collected, (
            f"pinned tracked red not found in live collection: {nodeid}"
        )


def test_gate_fast_carries_not_a_merge_gate_label():
    """gate-fast must visibly declare it is NOT a merge gate so cp3 is never dropped."""
    text = GATE_FAST_PATH.read_text(encoding="utf-8")
    assert "NOT a merge gate" in text
