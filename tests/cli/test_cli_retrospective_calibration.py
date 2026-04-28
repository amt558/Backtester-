"""Slice -1 Task 3: verify the retrospective-calibration CLI subcommand
exposes the right args and dispatches to the orchestrator.
"""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from tradelab.cli import app


runner = CliRunner()
FIXTURES = Path(__file__).parent.parent / "fixtures" / "retrospective"


def test_help_lists_retrospective_calibration_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "retrospective-calibration" in result.output


def test_retrospective_calibration_help_lists_alpaca_and_bot_log_args():
    result = runner.invoke(app, ["retrospective-calibration", "--help"])
    assert result.exit_code == 0
    assert "--alpaca-config" in result.output
    assert "--bot-log" in result.output
    assert "--reports" in result.output
    assert "--output" in result.output


def test_retrospective_calibration_runs_with_mocked_alpaca(tmp_path, monkeypatch):
    """Smoke: end-to-end CLI invocation with patched Alpaca client.

    We patch the _build_alpaca_client helper to avoid needing real credentials,
    then verify the orchestrator runs and writes the expected JSON.
    """
    fake_api = MagicMock()
    fake_api.list_orders.side_effect = [
        json.loads((FIXTURES / "alpaca_orders_sample.json").read_text()),
        [],
    ]
    monkeypatch.setattr(
        "tradelab.cli_retrospective_calibration._build_alpaca_client",
        lambda config_path, paper: fake_api,
    )

    fake_config = tmp_path / "alpaca_config.json"
    fake_config.write_text('{"api_key": "x", "secret_key": "y"}')
    out = tmp_path / "retro.json"

    result = runner.invoke(app, [
        "retrospective-calibration",
        "--alpaca-config", str(fake_config),
        "--bot-log", str(FIXTURES / "bot_log_sample.log"),
        "--reports", str(FIXTURES),
        "--output", str(out),
        "--paper",
    ])
    assert result.exit_code == 0, f"stderr/stdout: {result.output}\n{result.stderr_bytes}"
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["code_divergence_caveat"] is True
    assert "attribution_quality" in data
