"""Slice 0: Backfill the runs table from existing reports/ on disk.

Walks reports/*/robustness_result.json files, extracts strategy + verdict +
signal vector + dsr_probability, and writes one runs row per report.

Handles BOTH the real on-disk shape (verdict is a nested dict with signals
list, lowercase outcomes) AND a legacy shape (signals as top-level dict).
Per memory `reference_robustness_result_shape.md`.

Usage:
    python -m tradelab.scripts.backfill_runs_table --reports reports/
"""
from __future__ import annotations
import json
from pathlib import Path

from tradelab.audit.history import record_run, DEFAULT_DB_PATH


def _signal_values_from_report(rv: dict) -> dict:
    """Return a per-signal map {name: {outcome/verdict, reason, value}}.

    Handles real shape (verdict.signals list) AND legacy shape (signals dict).
    """
    verdict_block = rv.get("verdict")
    if isinstance(verdict_block, dict) and isinstance(verdict_block.get("signals"), list):
        # Real shape: list of {name, outcome, reason}
        return {
            s["name"]: {k: v for k, v in s.items() if k != "name"}
            for s in verdict_block["signals"]
            if isinstance(s, dict) and "name" in s
        }
    # Legacy shape: signals as top-level dict
    legacy = rv.get("signals")
    if isinstance(legacy, dict):
        return legacy
    return {}


def _verdict_string_from_report(rv: dict) -> str | None:
    """Extract the bare ROBUST/INCONCLUSIVE/FRAGILE string from either shape."""
    verdict_block = rv.get("verdict")
    if isinstance(verdict_block, dict):
        return verdict_block.get("verdict")
    if isinstance(verdict_block, str):
        return verdict_block
    return None


def backfill_from_reports(
    reports_dir: Path, db_path: Path = DEFAULT_DB_PATH,
) -> int:
    """Walk reports_dir for robustness_result.json files; insert one runs row each.

    Returns the number of rows inserted.
    """
    n = 0
    for report_file in reports_dir.glob("**/robustness_result.json"):
        try:
            data = json.loads(report_file.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        record_run(
            strategy_name=data.get("strategy") or report_file.parent.name,
            verdict=_verdict_string_from_report(data),
            dsr_probability=data.get("dsr_probability"),
            signal_values=_signal_values_from_report(data),
            db_path=db_path,
        )
        n += 1
    return n


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--reports", type=Path, required=True)
    p.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    args = p.parse_args(argv)
    n = backfill_from_reports(args.reports, args.db)
    print(f"Backfilled {n} runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
