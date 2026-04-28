"""One-time backfill: derive returns.csv for every existing pine_archive card.

Idempotent — skips cards that already have returns.csv unless --force is passed.

Usage:
    python -m tradelab.scripts.backfill_returns                    # dry run
    python -m tradelab.scripts.backfill_returns --apply            # write
    python -m tradelab.scripts.backfill_returns --apply --force    # overwrite existing
"""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
from tradelab.io.returns import derive_daily_returns, write_returns_csv


def find_archive_root() -> Path:
    """pine_archive is at <repo_root>/pine_archive. Resolve from this script's location.

    Script lives at src/tradelab/scripts/backfill_returns.py:
      parents[0] = src/tradelab/scripts/
      parents[1] = src/tradelab/
      parents[2] = src/
      parents[3] = repo root
    """
    here = Path(__file__).resolve()
    return here.parents[3] / "pine_archive"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write files (default: dry-run)")
    parser.add_argument("--force", action="store_true", help="overwrite existing returns.csv")
    parser.add_argument("--archive-root", type=Path, default=None, help="override pine_archive path")
    args = parser.parse_args(argv)

    archive_root = args.archive_root or find_archive_root()
    if not archive_root.exists():
        print(f"ERROR: pine_archive not found at {archive_root}", file=sys.stderr)
        return 1

    n_processed = 0
    n_written = 0
    n_skipped = 0
    n_failed = 0
    for card_dir in sorted(archive_root.iterdir()):
        if not card_dir.is_dir():
            continue
        tv_csv = card_dir / "tv_trades.csv"
        returns_csv = card_dir / "returns.csv"
        if not tv_csv.exists():
            continue
        n_processed += 1
        if returns_csv.exists() and not args.force:
            n_skipped += 1
            continue
        try:
            rows = derive_daily_returns(tv_csv)
            if not rows:
                print(f"  skip {card_dir.name}: no usable trades")
                n_skipped += 1
                continue
            if args.apply:
                write_returns_csv(returns_csv, rows)
                print(f"  wrote {card_dir.name}: {len(rows)} days")
                n_written += 1
            else:
                print(f"  would write {card_dir.name}: {len(rows)} days")
        except Exception as e:
            print(f"  ERROR {card_dir.name}: {e}", file=sys.stderr)
            n_failed += 1

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"\n[{mode}] processed={n_processed} written={n_written} skipped={n_skipped} failed={n_failed}")
    return 0 if n_failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
