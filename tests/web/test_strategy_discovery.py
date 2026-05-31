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


def test_import_discovered_appends_yaml_entry(tmp_path, monkeypatch):
    from tradelab.web.new_strategy import import_discovered
    yaml = tmp_path / "tradelab.yaml"
    yaml.write_text("strategies:\n  s2_pocket_pivot:\n    module: tradelab.strategies.s2_pocket_pivot\n    class_name: S2PocketPivot\n    params: {}\n")
    monkeypatch.setattr("tradelab.web.new_strategy._is_registered", lambda n: False)

    res = import_discovered("viprasol_v83", "ViprasolV83", yaml_path=yaml)
    assert res["error"] is None and res["registered"] is True
    text = yaml.read_text()
    assert "  viprasol_v83:" in text
    assert "module: tradelab.strategies.viprasol_v83" in text
    assert "class_name: ViprasolV83" in text


def test_import_discovered_rejects_duplicate(tmp_path, monkeypatch):
    from tradelab.web.new_strategy import import_discovered
    yaml = tmp_path / "tradelab.yaml"
    yaml.write_text("strategies:\n")
    monkeypatch.setattr("tradelab.web.new_strategy._is_registered", lambda n: True)
    res = import_discovered("s2_pocket_pivot", "S2PocketPivot", yaml_path=yaml)
    assert res["error"] is not None and res["registered"] is False


def test_discoverable_route_returns_records():
    import json
    from tradelab.web import handlers
    body, status = handlers.handle_get_with_status("/tradelab/strategies/discoverable")
    assert status == 200
    data = json.loads(body)["data"]
    assert "strategies" in data and isinstance(data["strategies"], list)


def test_import_route_rejects_missing_fields():
    import json
    from tradelab.web import handlers
    body, status = handlers.handle_post_with_status(
        "/tradelab/strategies/import", json.dumps({"name": "x"}).encode())
    assert status == 400
