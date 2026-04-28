"""Endpoint tests for GET /tradelab/canary-status (Slice 0.5 Task 0.5.3).

The endpoint surfaces engine integrity at a glance: it reads the latest
verdict per canary from the audit DB and returns a JSON payload the
dashboard uses to render the Canary Panel + globally toggle the
`accepts-blocked` body class. Status query only — no re-runs.

Response shape (unenveloped, matches /tradelab/runs convention):

    {
      "all_match": bool,
      "canaries":  [ {name, expected, actual, status, last_run}, ... ],
      "last_run_at": "<iso8601>"
    }
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

import pytest

from tradelab.audit import record_run
from tradelab.web import handlers


def test_canary_status_endpoint_all_match(fake_audit_db: Path, monkeypatch):
    """Happy path: insert FRAGILE rows for all 4 canaries → endpoint returns
    all_match=True with 4 MATCH canary cells."""
    monkeypatch.setattr(handlers, "_db_path", lambda: fake_audit_db)

    # Seed the audit DB with FRAGILE rows for every canary.
    from tradelab.cli_canary import CANARY_NAMES
    for name in CANARY_NAMES:
        record_run(name, verdict="FRAGILE", dsr_probability=0.2, db_path=fake_audit_db)

    body, status = handlers.handle_get_with_status("/tradelab/canary-status")
    assert status == 200
    data = json.loads(body)
    assert data["all_match"] is True
    assert len(data["canaries"]) == 4
    assert all(c["status"] == "MATCH" for c in data["canaries"])
    assert data["last_run_at"]


def test_canary_status_endpoint_one_mismatch(fake_audit_db: Path, monkeypatch):
    """Insert a ROBUST row for leak_canary (engine broken) and FRAGILE for the
    rest. Endpoint must return all_match=False and that one MISMATCH."""
    monkeypatch.setattr(handlers, "_db_path", lambda: fake_audit_db)

    from tradelab.cli_canary import CANARY_NAMES
    for name in CANARY_NAMES:
        verdict = "ROBUST" if name == "leak_canary" else "FRAGILE"
        record_run(name, verdict=verdict, dsr_probability=0.5, db_path=fake_audit_db)

    body, status = handlers.handle_get_with_status("/tradelab/canary-status")
    assert status == 200
    data = json.loads(body)
    assert data["all_match"] is False
    by_name = {c["name"]: c for c in data["canaries"]}
    assert by_name["leak_canary"]["status"] == "MISMATCH"
    assert by_name["leak_canary"]["actual"] == "ROBUST"


def test_canary_status_endpoint_empty_db_returns_all_unknown(fake_audit_db: Path, monkeypatch):
    """No canary rows → all UNKNOWN, but all_match=True (don't block accepts on
    missing-data; only on proven engine drift)."""
    monkeypatch.setattr(handlers, "_db_path", lambda: fake_audit_db)

    body, status = handlers.handle_get_with_status("/tradelab/canary-status")
    assert status == 200
    data = json.loads(body)
    assert data["all_match"] is True
    assert all(c["status"] == "UNKNOWN" for c in data["canaries"])


def test_canary_status_endpoint_unknown_route_still_404(fake_audit_db: Path, monkeypatch):
    """Adding the canary-status route must not break the 404 fallback."""
    monkeypatch.setattr(handlers, "_db_path", lambda: fake_audit_db)
    _, status = handlers.handle_get_with_status("/tradelab/this-route-does-not-exist")
    assert status == 404
