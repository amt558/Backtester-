"""
Standalone self-test for the tier-1 validation suite.

Loads a saved run's `backtest_result.json`, runs the validation suite, and
prints each record. No server, no dashboard, no verdict. By default it only
PRINTS — it writes `validation.json` into the run folder only when given
`--write`, so it can be pointed at locked baseline run folders (Viprasol v8.2,
CG-TFE v1.5) without mutating them.

Usage:
    python -m tradelab.validation._selftest <run_folder> [--write]
    python -m tradelab.validation._selftest          # auto-pick a sample run

Examples:
    python -m tradelab.validation._selftest reports/s2_pocket_pivot_2026-05-02_044106
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..results import BacktestResult
from .suite import run_validation_suite


def _auto_pick_run() -> Path | None:
    """Pick the most recent reports/* folder that has a backtest_result.json."""
    root = Path("reports")
    if not root.is_dir():
        return None
    candidates = [p.parent for p in root.glob("*/backtest_result.json")]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _run_deep(bt: BacktestResult, n_sims: int) -> list:
    """Reconstruct (strategy, data) from the saved run via the registry + parquet
    cache (same path cli_run uses) and run the tier-3 engine re-runs. Best-effort:
    prints a skip note and returns [] if the strategy isn't registered or no
    cached data is available. Universe is approximated from the run's traded
    tickers (a real --full run uses the full configured universe)."""
    from ..marketdata import download_symbols, enrich_universe
    from ..registry import instantiate_strategy
    from .deep import run_validation_suite_deep

    tickers = sorted({t.ticker.upper() for t in bt.trades})
    symbols = sorted(set(tickers) | {"SPY"})
    print(f"\n[deep] reconstructing {bt.strategy} over {len(tickers)} traded "
          f"tickers (cache only, no fetch) ...")
    try:
        strat = instantiate_strategy(bt.strategy)
    except Exception as e:
        print(f"[deep] skipped — strategy not in registry: {e}")
        return []
    try:
        data = download_symbols(symbols, start=bt.start_date, end=bt.end_date,
                                allow_yfinance_fallback=False)
    except Exception as e:
        print(f"[deep] skipped — data load failed: {e}")
        return []
    if not data:
        print("[deep] skipped — no cached data for traded tickers")
        return []
    data = enrich_universe(data, benchmark="SPY")
    spy_close = None
    if "SPY" in data and "Close" in data["SPY"].columns:
        spy_close = data["SPY"].set_index("Date")["Close"]
    return run_validation_suite_deep(
        strat, data, bt, spy_close=spy_close,
        start=bt.start_date, end=bt.end_date, n_sims=n_sims,
    )


def _load_backtest(folder: Path) -> BacktestResult:
    bt_path = folder / "backtest_result.json"
    if not bt_path.is_file():
        raise FileNotFoundError(f"no backtest_result.json in {folder}")
    raw = bt_path.read_text(encoding="utf-8-sig")
    return BacktestResult.model_validate(json.loads(raw))


# ASCII-only labels — the Windows console (cp1252) mangles Unicode glyphs.
_OUTCOME_GLYPH = {"robust": "ROBUST", "fragile": "FRAGILE",
                  "inconclusive": "INCONC."}


def main(argv: list[str] | None = None) -> int:
    # Reason strings use ≤/≥ to match verdict.py's convention. Force UTF-8 so
    # the Windows console (cp1252 default) doesn't choke when printing them.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    ap = argparse.ArgumentParser(description="Run the tier-1 validation suite on one run folder.")
    ap.add_argument("run_folder", nargs="?", help="path to a reports/<run> folder")
    ap.add_argument("--write", action="store_true",
                    help="also write validation.json into the run folder (off by default)")
    ap.add_argument("--deep", action="store_true",
                    help="also run tier-3 engine re-runs (reconstructs strategy + data "
                         "from the registry/parquet cache; slow)")
    ap.add_argument("--sims", type=int, default=30,
                    help="random-entry sims for --deep (default 30; production 200)")
    args = ap.parse_args(argv)

    folder = Path(args.run_folder) if args.run_folder else _auto_pick_run()
    if folder is None:
        print("No run folder given and none auto-discovered under reports/.", file=sys.stderr)
        return 2
    if not folder.is_dir():
        print(f"Not a directory: {folder}", file=sys.stderr)
        return 2

    bt = _load_backtest(folder)
    report = run_validation_suite(bt)

    print(f"\nValidation suite v{report.suite_version}  —  {report.strategy}")
    print(f"Run folder : {folder}")
    print(f"Trades     : {len(bt.trades)}   |   timeframe {bt.timeframe}   symbol {bt.symbol}")
    print("=" * 78)
    for s in report.signals:
        glyph = _OUTCOME_GLYPH.get(s.outcome, s.outcome)
        val = "—" if s.value is None else f"{s.value}"
        print(f"\n  {s.name:<22} [{glyph}]   value={val}")
        print(f"    reason: {s.reason}")
        # one-line detail digest (full payload lives in the model)
        digest = {k: v for k, v in s.detail.items() if not isinstance(v, list)}
        print(f"    detail: {json.dumps(digest, default=str)}")
    deep_signals = []
    if args.deep:
        deep_signals = _run_deep(bt, args.sims)
        for s in deep_signals:
            glyph = _OUTCOME_GLYPH.get(s.outcome, s.outcome)
            val = "—" if s.value is None else f"{s.value}"
            print(f"\n  {s.name:<22} [{glyph}]   value={val}")
            print(f"    reason: {s.reason}")
            digest = {k: v for k, v in s.detail.items() if not isinstance(v, list)}
            print(f"    detail: {json.dumps(digest, default=str)}")

    print("\n" + "=" * 78)
    print("(report-only layer -- feeds nothing into compute_verdict)")

    if deep_signals:
        report.signals.extend(deep_signals)

    if args.write:
        out = folder / "validation.json"
        out.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        print(f"\nWrote {out}")
    else:
        print("\n(print-only; pass --write to serialize validation.json)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
