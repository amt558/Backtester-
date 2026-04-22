"""Mock CLI used in lieu of real tradelab.cli for fast tests.

Invoked as: python tests/web/_fake_cli.py --progress-log <path> --script <script_name>

Each script_name maps to a deterministic sequence of events written to <path>,
followed by an exit code. Lets every test assert "subprocess emitted these
events and exited cleanly" without spinning up real backtests.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# We import from the real package — we only need the emitter
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from tradelab.web.progress_events import ProgressEmitter


SCRIPTS = {
    "happy_short": [
        ("start", {"stage": "backtest"}),
        ("complete", {"stage": "backtest", "duration_s": 0.01}),
        ("done", {"exit_code": 0}),
    ],
    "happy_with_progress": [
        ("start", {"stage": "monte_carlo"}),
        ("progress", {"stage": "monte_carlo", "i": 100, "total": 500}),
        ("progress", {"stage": "monte_carlo", "i": 320, "total": 500}),
        ("complete", {"stage": "monte_carlo", "duration_s": 0.05}),
        ("done", {"exit_code": 0}),
    ],
    "fails_immediately": [
        ("error", {"message": "synthetic failure for testing"}),
        ("done", {"exit_code": 1}),
    ],
    "no_events_then_crashes": [],  # exits 1 with no emit
    "long_running": [
        # caller controls duration via SLEEP_S env var; default 10s
        ("start", {"stage": "monte_carlo"}),
    ],
}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--progress-log", default="")
    p.add_argument("--script", required=True)
    p.add_argument("--exit", type=int, default=None,
                   help="Override final exit code (used by fails_immediately etc.)")
    args = p.parse_args()

    if args.script not in SCRIPTS:
        print(f"unknown script: {args.script}", file=sys.stderr)
        return 2

    em = ProgressEmitter(args.progress_log)
    final_exit = 0
    for type_, fields in SCRIPTS[args.script]:
        if type_ == "done":
            final_exit = fields.get("exit_code", 0)
            em.done(exit_code=final_exit)
        else:
            em.emit(type_, **fields)

    if args.script == "long_running":
        import os
        sleep_s = int(os.environ.get("SLEEP_S", "10"))
        try:
            time.sleep(sleep_s)
        except KeyboardInterrupt:
            em.error("cancelled")
            em.done(exit_code=130)
            em.close()
            return 130
        em.done(exit_code=0)

    if args.exit is not None:
        final_exit = args.exit
    em.close()
    return final_exit


if __name__ == "__main__":
    sys.exit(main())
