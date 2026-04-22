"""Shared fixtures for web-layer tests."""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest


@pytest.fixture
def fake_tradelab_root(tmp_path: Path) -> Path:
    """Scaffolded tradelab root with data/, reports/, src/ subdirs."""
    (tmp_path / "data").mkdir()
    (tmp_path / "reports").mkdir()
    (tmp_path / "src" / "tradelab" / "strategies").mkdir(parents=True)
    (tmp_path / ".cache" / "ohlcv" / "1D").mkdir(parents=True)
    (tmp_path / ".cache" / "new_strategy_staging").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def fake_audit_db(fake_tradelab_root: Path) -> Path:
    """Audit DB pre-populated with 3 runs across 2 strategies."""
    db_path = fake_tradelab_root / "data" / "tradelab_history.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY,
            timestamp_utc TEXT NOT NULL,
            strategy_name TEXT NOT NULL,
            strategy_version TEXT,
            tradelab_version TEXT,
            tradelab_git_commit TEXT,
            input_data_hash TEXT,
            config_hash TEXT,
            verdict TEXT,
            dsr_probability REAL,
            report_card_markdown TEXT,
            report_card_html_path TEXT
        );
    """)
    now = datetime.now(timezone.utc)
    rows = [
        ("run-001", (now - timedelta(days=3)).isoformat(timespec="seconds"),
         "s2_pocket_pivot", None, None, None, None, None, "FRAGILE", 0.31, "# fragile", None),
        ("run-002", (now - timedelta(days=2)).isoformat(timespec="seconds"),
         "s4_inside_day_breakout", None, None, None, None, None, "ROBUST", 0.78, "# robust", None),
        ("run-003", (now - timedelta(days=1)).isoformat(timespec="seconds"),
         "s4_inside_day_breakout", None, None, None, None, None, "ROBUST", 0.81, "# robust2", None),
    ]
    conn.executemany(
        "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def fake_run_folder(fake_tradelab_root: Path) -> Path:
    """One run folder with backtest_result.json + placeholder HTML artifacts."""
    folder = fake_tradelab_root / "reports" / "s4_inside_day_breakout_2026-04-20_120000"
    folder.mkdir()
    metrics = {
        "strategy": "s4_inside_day_breakout",
        "metrics": {
            "total_trades": 44,
            "wins": 26,
            "losses": 18,
            "win_rate": 59.09,
            "profit_factor": 1.42,
            "net_pnl": 6340.12,
            "pct_return": 6.34,
            "annual_return": 3.12,
            "max_drawdown_pct": -6.8,
            "sharpe_ratio": 1.08,
        },
        "equity_curve": [
            {"date": "2024-01-01", "equity": 100000.0},
            {"date": "2026-04-20", "equity": 106340.12},
        ],
    }
    (folder / "backtest_result.json").write_text(json.dumps(metrics))
    (folder / "dashboard.html").write_text("<html>fake dashboard</html>")
    (folder / "quantstats_tearsheet.html").write_text("<html>fake qs</html>")
    (folder / "executive_report.md").write_text("# Verdict: ROBUST\n\nAll checks passed.\n")
    return folder


@pytest.fixture
def fake_parquet_cache(fake_tradelab_root: Path) -> Path:
    """Parquet cache dir with 3 fake symbol files with known mtimes."""
    cache = fake_tradelab_root / ".cache" / "ohlcv" / "1D"
    for sym in ("AAPL", "NVDA", "SPY"):
        p = cache / f"{sym}.parquet"
        p.write_bytes(b"fake")
    # Set mtimes: AAPL 2h old, NVDA 1h old, SPY just now
    now = time.time()
    (cache / "AAPL.parquet").touch()  # default = now
    import os
    os.utime(cache / "AAPL.parquet", (now - 7200, now - 7200))
    os.utime(cache / "NVDA.parquet", (now - 3600, now - 3600))
    return cache


@pytest.fixture
def fake_strategies_dir(fake_tradelab_root: Path) -> Path:
    """Empty tradelab strategies src dir."""
    return fake_tradelab_root / "src" / "tradelab" / "strategies"
