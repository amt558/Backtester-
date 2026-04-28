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


def test_build_alpaca_client_reads_nested_config_with_bom(tmp_path):
    """Real alpaca_config.json has nested alpaca block + UTF-8 BOM.
    Builder constructs alpaca-py TradingClient (not the deprecated old SDK)."""
    from tradelab.cli_retrospective_calibration import (
        _build_alpaca_client, _AlpacaPyListOrdersAdapter,
    )
    cfg = tmp_path / "alpaca_config.json"
    cfg.write_bytes(
        b"\xef\xbb\xbf"
        + b'{"alpaca": {"api_key": "ak_test", "secret_key": "sk_test", '
        + b'"base_url": "https://x", "paper_trading": true}}'
    )
    from unittest.mock import patch, MagicMock
    with patch("alpaca.trading.client.TradingClient") as fake_client_cls:
        fake_client_cls.return_value = MagicMock()
        adapter = _build_alpaca_client(cfg, paper=True)
    args, kwargs = fake_client_cls.call_args
    # alpaca-py's TradingClient takes positional (api_key, secret) + paper kwarg
    assert args[0] == "ak_test"
    assert args[1] == "sk_test"
    assert kwargs["paper"] is True
    assert isinstance(adapter, _AlpacaPyListOrdersAdapter)


def test_alpaca_py_adapter_translates_list_orders():
    """Adapter must convert alpaca-py Order objects to old-SDK dict shape."""
    from tradelab.cli_retrospective_calibration import _AlpacaPyListOrdersAdapter
    from unittest.mock import MagicMock
    from datetime import datetime, timezone

    fake_client = MagicMock()
    fake_order = MagicMock()
    fake_order.id = "order_abc"
    fake_order.symbol = "AAPL"
    fake_order.qty = 100
    fake_order.side = MagicMock(value="buy")
    fake_order.filled_qty = 100
    fake_order.filled_avg_price = 180.10
    fake_order.filled_at = datetime(2026, 1, 15, 14, 31, 0, tzinfo=timezone.utc)
    fake_order.client_order_id = "S4_InsideDayBreakout-AAPL-123"
    fake_order.status = MagicMock(value="filled")
    fake_client.get_orders.return_value = [fake_order]

    adapter = _AlpacaPyListOrdersAdapter(fake_client)
    out = adapter.list_orders(
        status="filled", after="2026-01-01T00:00:00Z", limit=500, direction="desc",
    )
    assert len(out) == 1
    assert out[0]["symbol"] == "AAPL"
    assert out[0]["status"] == "filled"
    assert out[0]["filled_qty"] == "100"
    assert out[0]["filled_avg_price"] == "180.1"
    assert out[0]["client_order_id"] == "S4_InsideDayBreakout-AAPL-123"
    assert out[0]["side"] == "buy"


def test_alpaca_py_adapter_filters_non_filled():
    """Adapter must drop CLOSED-but-not-filled orders (canceled, expired, etc.)."""
    from tradelab.cli_retrospective_calibration import _AlpacaPyListOrdersAdapter
    from unittest.mock import MagicMock

    fake_client = MagicMock()
    canceled = MagicMock()
    canceled.id = "x"; canceled.symbol = "TSLA"; canceled.qty = 10
    canceled.side = MagicMock(value="buy"); canceled.filled_qty = 0
    canceled.filled_avg_price = None; canceled.filled_at = None
    canceled.client_order_id = "c"; canceled.status = MagicMock(value="canceled")
    fake_client.get_orders.return_value = [canceled]

    adapter = _AlpacaPyListOrdersAdapter(fake_client)
    out = adapter.list_orders(status="filled", after="2026-01-01T00:00:00Z")
    assert out == []
