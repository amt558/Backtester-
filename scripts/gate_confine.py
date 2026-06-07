"""cp3 full-suite confinement check for the merge gate.

Parses a pytest ``--junitxml`` report and enforces the cp3 contract:

    The full suite must be green. Any failing test whose nodeid is not in
    ``TRACKED_B2_REDS`` is a real failure and fails the gate.

``TRACKED_B2_REDS`` is the (small, normally empty) set of KNOWN-RED tests the
gate is permitted to wave through. As of B2 it is **empty** -- the 3
delete-safety reds went green when the live ``command_center.html`` copy was
fixed -- so cp3 is now a *clean binary*: it passes (exit 0) iff the suite has
zero failures. See the A1 coupling note on ``TRACKED_B2_REDS`` below.

Usage:
    python scripts/gate_confine.py --junitxml .cache/full_suite_gate.xml
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------------------
# Tracked B2 delete-safety reds: now EMPTY. The 3 reds went green when B2 fixed
# the delete-safety copy in the live command_center.html.
#
# A1 COUPLING -- read before you panic at a fresh-checkout cp3 failure:
# the copy fix that makes those 3 web tests green rides UNCOMMITTED in the
# PARENT repo's live C:\TradingScripts\command_center.html (the served file the
# web tests read), consistent with how that file has been treated across the
# whole arc (WP5 included). cp3 is now a clean binary: it expects ZERO confined
# reds. So a clean checkout / revert of the live command_center.html would
# re-red the 3 delete-safety tests and cp3 would FAIL here -- that is the
# expected, self-explaining symptom of a missing uncommitted parent-repo fix,
# NOT a regression in this script. Re-apply the live HTML delete-copy fix (see
# the B2 handoff) to restore green. When the parent-repo drift is resolved as
# its own session (the eventual A2 path), the fix becomes committed and this
# coupling goes away.
#
# tests/gate/test_gate_targets.py asserts this stays empty (clean binary) and
# exercises the confinement LOGIC against a synthetic tracked ID.
# ---------------------------------------------------------------------------
TRACKED_B2_REDS: tuple[str, ...] = ()


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
        print("cp3 FAIL: unconfined failure(s) -- full suite must be green (no confined reds):")
        for nodeid in unconfined:
            print(f"  - {nodeid}")
        return 1

    print("cp3 PASS: full suite clean -- no confined reds (clean binary).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
