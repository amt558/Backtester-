"""cp3 full-suite confinement check for the merge gate.

Parses a pytest ``--junitxml`` report and enforces the cp3 contract:

    Any failure outside ``tests/web/test_command_center_html.py`` is real.
    Inside that file, any failure that is NOT one of the 3 tracked B2
    delete-safety reds is real.

In other words, the gate PASSES (exit 0) iff the set of failing tests is a
subset of ``TRACKED_B2_REDS``. The 3 reds are KNOWN-RED and *confined* by the
gate -- they are deliberately not fixed here (see the verdict.py fence and the
B2 copy-fix board item). Any other failure, in any file, fails the gate.

Usage:
    python scripts/gate_confine.py --junitxml .cache/full_suite_gate.xml
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------------------
# Single source of truth: the 3 tracked B2 delete-safety reds.
# Pinned here ONCE. tests/gate/test_gate_targets.py asserts this list still
# matches the live, collectable test IDs -- so a rename/typo trips a test
# rather than silently widening what the gate will wave through.
# ---------------------------------------------------------------------------
TRACKED_B2_REDS = (
    "tests/web/test_command_center_html.py::test_v3_task14_trash_button_tooltip_says_delete_not_archive",
    "tests/web/test_command_center_html.py::test_v3_task15_stale_archive_copy_removed",
    "tests/web/test_command_center_html.py::test_v3_task15_modal_copy_describes_hard_delete",
)


def _nodeid(classname: str, name: str) -> str:
    """Reconstruct a pytest nodeid from junitxml (classname, name) attributes.

    junitxml stores e.g. classname="tests.web.test_command_center_html",
    name="test_foo" -> "tests/web/test_command_center_html.py::test_foo".
    """
    module_path = classname.replace(".", "/")
    return f"{module_path}.py::{name}"


def failing_nodeids(junit_path: str) -> list[str]:
    """Return the nodeids of every testcase that failed or errored."""
    root = ET.parse(junit_path).getroot()
    failing: list[str] = []
    for testcase in root.iter("testcase"):
        if testcase.find("failure") is not None or testcase.find("error") is not None:
            failing.append(_nodeid(testcase.get("classname", ""), testcase.get("name", "")))
    return failing


def unconfined_failures(junit_path: str) -> list[str]:
    """Failures that are NOT one of the tracked B2 reds -- i.e. real failures."""
    tracked = set(TRACKED_B2_REDS)
    return [nodeid for nodeid in failing_nodeids(junit_path) if nodeid not in tracked]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="cp3 confinement check: fail unless all failures are the 3 tracked B2 reds.",
    )
    parser.add_argument("--junitxml", required=True, help="path to the pytest junitxml report")
    args = parser.parse_args(argv)

    unconfined = unconfined_failures(args.junitxml)
    if unconfined:
        print("cp3 FAIL: unconfined failure(s) outside the 3 tracked B2 reds:")
        for nodeid in unconfined:
            print(f"  - {nodeid}")
        return 1

    print("cp3 PASS: full suite clean except the 3 confined B2 delete-safety reds.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
