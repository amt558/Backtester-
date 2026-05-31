from pathlib import Path
from tradelab.web.new_strategy import discover_unregistered_strategies


def test_discovery_finds_unregistered_strategy_files(tmp_path, monkeypatch):
    # Registered set: only s2_pocket_pivot's module is registered.
    monkeypatch.setattr(
        "tradelab.web.new_strategy.list_registered_strategies",
        lambda: {"s2_pocket_pivot": type("E", (), {
            "module": "tradelab.strategies.s2_pocket_pivot", "class_name": "S2PocketPivot"})()},
    )
    found = discover_unregistered_strategies()
    names = {d["suggested_name"] for d in found}
    assert "s2_pocket_pivot" not in names
    assert "viprasol_v83" in names
    rec = next(d for d in found if d["suggested_name"] == "viprasol_v83")
    assert rec["class_name"] == "ViprasolV83"
    assert rec["module"] == "tradelab.strategies.viprasol_v83"
    assert rec["timeframe"] == "1D"
    assert rec["requires_benchmark"] is True
