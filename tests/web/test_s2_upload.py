"""S2 (2026-09-02) — the upload path.

Covers: tickers declared on the strategy (`symbols`), discovery skipping
abstract bases (S0 F7), registry reload after import (S0 F8), the smoke
backtest honouring declared symbols, argv building without --universe for
symbol-declaring strategies, and the New-from-template route.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from tradelab.strategies.base import Strategy
from tradelab.strategies.simple import SimpleStrategy
from tradelab.web import new_strategy
from tradelab.web import handlers


# ── declared_symbols ────────────────────────────────────────────────────

def test_declared_symbols_normalises_and_filters():
    class S(Strategy):
        symbols = ["nvda", " avgo ", "NVDA", "bad ticker", 42, "BRK.B"]

        def generate_signals(self, data, spy_close=None):
            return data

    assert new_strategy.declared_symbols(S) == ["NVDA", "AVGO", "BRK.B"]


def test_declared_symbols_empty_by_default():
    class S(Strategy):
        def generate_signals(self, data, spy_close=None):
            return data

    assert new_strategy.declared_symbols(S) == []
    assert Strategy.symbols == []


# ── abstract-base marker (F7) ─────────────────────────────────────────

def test_simple_strategy_is_marked_abstract_and_subclasses_are_not():
    assert new_strategy._is_abstract_base(SimpleStrategy) is True

    class Child(SimpleStrategy):
        name = "child"

        def entry_signal(self, row, prev, params):
            return False

    assert new_strategy._is_abstract_base(Child) is False


def test_discovery_skips_abstract_base_and_reports_symbols(tmp_path, monkeypatch):
    # Build a fake src/tradelab/strategies tree with: a base-like module carrying
    # the marker, and a real strategy declaring symbols.
    src = tmp_path / "src"
    pkg = src / "tradelab" / "strategies"
    pkg.mkdir(parents=True)
    (src / "tradelab" / "__init__.py").write_text("")
    (pkg / "__init__.py").write_text("")
    (pkg / "base.py").write_text("")  # skipped by name, as before
    (pkg / "mybase.py").write_text(textwrap.dedent('''
        from tradelab.strategies.base import Strategy
        class MyBase(Strategy):
            _tradelab_abstract = True
            def generate_signals(self, data, spy_close=None):
                return data
    '''))
    (pkg / "real_one.py").write_text(textwrap.dedent('''
        from tradelab.strategies.base import Strategy
        class RealOne(Strategy):
            symbols = ["nvda", "avgo"]
            timeframe = "1D"
            def generate_signals(self, data, spy_close=None):
                return data
    '''))
    # Import through a private package name so we don't shadow the real one.
    import importlib, sys, types
    monkeypatch.setattr(new_strategy, "list_registered_strategies", lambda: {})

    calls = {}
    real_import = importlib.import_module

    def fake_import(module_path):
        stem = module_path.rsplit(".", 1)[-1]
        code = (pkg / f"{stem}.py").read_text()
        mod = types.ModuleType(module_path)
        exec(code, mod.__dict__)
        calls[module_path] = True
        return mod

    monkeypatch.setattr(importlib, "import_module", fake_import)
    found = new_strategy.discover_unregistered_strategies(src_root=src)
    names = {(r["class_name"], r["suggested_name"]) for r in found}
    assert ("RealOne", "real_one") in names
    assert not any(r["class_name"] == "MyBase" for r in found), "abstract base leaked into discovery (F7)"
    rec = next(r for r in found if r["class_name"] == "RealOne")
    assert rec["symbols"] == ["NVDA", "AVGO"]


# ── registry reload after import (F8) ─────────────────────────────────

def test_import_discovered_reloads_registry(tmp_path, monkeypatch):
    yaml_path = tmp_path / "tradelab.yaml"
    yaml_path.write_text("strategies:\n  existing:\n    module: tradelab.strategies.existing\n    class_name: Existing\n    params: {}\n")
    monkeypatch.setattr(new_strategy, "_is_registered", lambda name: False)
    reloaded = {"n": 0}

    def fake_get_config(reload=False):
        if reload:
            reloaded["n"] += 1
        return object()

    import tradelab.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "get_config", fake_get_config)
    out = new_strategy.import_discovered("brand_new", "BrandNew", yaml_path=yaml_path)
    assert out["error"] is None and out["registered"] is True
    assert "  brand_new:" in yaml_path.read_text()
    assert reloaded["n"] == 1, "import must drop the cached config so the running server sees it (F8)"


# ── smoke backtest honours declared symbols ───────────────────────────

def test_smoke_backtest_uses_declared_symbols(monkeypatch):
    import pandas as pd

    class Declared(SimpleStrategy):
        name = "declared"
        symbols = ["AAA", "BBB"]

        def entry_signal(self, row, prev, params):
            return False

    read_calls: list[str] = []

    def fake_read(sym, timeframe):
        read_calls.append(sym)
        return None  # nothing cached → RuntimeError with the label we assert on

    from tradelab.marketdata import cache
    monkeypatch.setattr(cache, "read", fake_read)
    with pytest.raises(RuntimeError) as ei:
        new_strategy._run_smoke_backtest(Declared())
    assert read_calls == ["AAA", "BBB"], "smoke must read exactly the declared tickers"
    assert "declared symbols" in str(ei.value)


def test_smoke_backtest_falls_back_to_smoke_5(monkeypatch):
    class Undeclared(SimpleStrategy):
        name = "undeclared"

        def entry_signal(self, row, prev, params):
            return False

    read_calls: list[str] = []
    from tradelab.marketdata import cache
    monkeypatch.setattr(cache, "read", lambda sym, tf: read_calls.append(sym))
    with pytest.raises(RuntimeError) as ei:
        new_strategy._run_smoke_backtest(Undeclared())
    assert len(read_calls) == 5 and "smoke_5" in str(ei.value)


# ── argv: no --universe injection for symbol-declaring strategies ─────

def test_build_argv_omits_universe_when_strategy_declares_symbols(monkeypatch):
    monkeypatch.setattr(handlers, "_strategy_declares_symbols", lambda name: True)
    monkeypatch.setattr(handlers, "_resolve_active_universe", lambda: "smoke_5")
    argv = handlers._build_tradelab_argv("declared", "run --robustness")
    assert argv is not None and "--universe" not in argv


def test_build_argv_injects_universe_otherwise(monkeypatch):
    monkeypatch.setattr(handlers, "_strategy_declares_symbols", lambda name: False)
    monkeypatch.setattr(handlers, "_resolve_active_universe", lambda: "smoke_5")
    argv = handlers._build_tradelab_argv("plain", "run --robustness")
    assert argv is not None and argv[argv.index("--universe") + 1] == "smoke_5"


def test_explicit_universe_still_wins_over_declared_symbols(monkeypatch):
    monkeypatch.setattr(handlers, "_strategy_declares_symbols", lambda name: True)
    argv = handlers._build_tradelab_argv("declared", "run --robustness", universe="big_tech_15")
    assert argv[argv.index("--universe") + 1] == "big_tech_15"


# ── template route ────────────────────────────────────────────────────

def test_template_route_renders_simple_strategy_with_symbols_line():
    import json
    body, status = handlers.handle_get_with_status("/tradelab/new-strategy/template?name=nvda-pullback")
    assert status == 200
    env = json.loads(body)
    assert env["error"] is None
    d = env["data"]
    assert d["name"] == "nvda_pullback" and d["class_name"] == "NvdaPullback"
    assert "class NvdaPullback(SimpleStrategy)" in d["code"]
    assert "symbols = []" in d["code"]
    assert "def entry_signal" in d["code"]


def test_template_route_rejects_bad_name():
    body, status = handlers.handle_get_with_status("/tradelab/new-strategy/template?name=9bad")
    assert status == 400


# ── zero-trade smoke is a failure, not a pass ─────────────────────────

def test_validate_and_stage_refuses_zero_trade_smoke(tmp_path, monkeypatch):
    code = textwrap.dedent('''
        from tradelab.strategies.simple import SimpleStrategy
        class Silent(SimpleStrategy):
            name = "silent"
            symbols = ["AAA"]
            def entry_signal(self, row, prev, params):
                return False
    ''')
    monkeypatch.setattr(new_strategy, "_is_registered", lambda name: False)
    monkeypatch.setattr(new_strategy, "_run_smoke_backtest", lambda strat: ({"total_trades": 0, "profit_factor": 0.0}, {}))
    out = new_strategy.validate_and_stage("silent", code, staging_root=tmp_path / "stage", src_root=tmp_path / "src")
    assert out["stage"] == "smoke" and "0 trades" in out["error"] and "AAA" in out["error"]
    assert not (tmp_path / "stage" / "silent.py").exists(), "staged file must be removed on a failed smoke"


def test_validate_and_stage_passes_when_it_trades(tmp_path, monkeypatch):
    code = textwrap.dedent('''
        from tradelab.strategies.simple import SimpleStrategy
        class Talks(SimpleStrategy):
            name = "talks"
            def entry_signal(self, row, prev, params):
                return True
    ''')
    monkeypatch.setattr(new_strategy, "_is_registered", lambda name: False)
    monkeypatch.setattr(new_strategy, "_run_smoke_backtest", lambda strat: ({"total_trades": 7, "profit_factor": 1.2}, {}))
    out = new_strategy.validate_and_stage("talks", code, staging_root=tmp_path / "stage", src_root=tmp_path / "src")
    assert out["error"] is None and out["stage"] == "complete" and out["class_name"] == "Talks"


def test_template_uses_absolute_imports_so_it_stages_from_the_paste_box():
    """The upload modal imports the pasted/dropped file in isolation (no parent
    package), so a relative `from .simple import ...` would fail at stage 2."""
    import json
    body, _ = handlers.handle_get_with_status("/tradelab/new-strategy/template?name=abs_check")
    code = json.loads(body)["data"]["code"]
    assert "from tradelab.strategies.simple import SimpleStrategy" in code
    assert "from .simple" not in code


# ── SimpleStrategy hook arity (the silent zero-trade bug) ─────────────

def _bars(n=60):
    import numpy as np, pandas as pd
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    close = np.linspace(100, 130, n)
    df = pd.DataFrame({"Date": idx, "Open": close, "High": close + 1, "Low": close - 1,
                       "Close": close, "Volume": 1_000_000, "ATR": 1.0})
    return {"AAA": df}


def test_simple_strategy_calls_three_arg_entry_signal():
    """The documented/template signature entry_signal(row, prev, params) must
    produce signals — before S2 the 4-arg call raised TypeError on it and the
    handler swallowed the error, so every template strategy had 0 trades."""
    class Three(SimpleStrategy):
        name = "three"
        def entry_signal(self, row, prev, params):
            return prev is not None

    out = Three().generate_signals(_bars())
    assert out["AAA"]["buy_signal"].sum() >= 50


def test_simple_strategy_still_supports_four_arg_entry_signal():
    class Four(SimpleStrategy):
        name = "four"
        def entry_signal(self, row, prev, params, prev2=None):
            return prev2 is not None

    out = Four().generate_signals(_bars())
    assert out["AAA"]["buy_signal"].sum() >= 50


def test_simple_strategy_warns_instead_of_hiding_a_broken_entry_rule():
    import warnings
    class Broken(SimpleStrategy):
        name = "broken"
        def entry_signal(self, row, prev, params):
            return row["NO_SUCH_COLUMN"] > 0

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        out = Broken().generate_signals(_bars())
    assert out["AAA"]["buy_signal"].sum() == 0
    assert any("entry_signal" in str(x.message) and "KeyError" in str(x.message) for x in w)


# ── Specialist code-level pass (2026-09-02) ───────────────────────────

def test_declared_symbols_string_is_one_ticker_not_letters():
    class S(Strategy):
        symbols = "TSLA"

        def generate_signals(self, data, spy_close=None):
            return data

    assert new_strategy.declared_symbols(S) == ["TSLA"]


def test_zero_trade_guard_fails_closed_when_trade_count_missing(tmp_path, monkeypatch):
    code = textwrap.dedent('''
        from tradelab.strategies.simple import SimpleStrategy
        class Quiet(SimpleStrategy):
            name = "quiet"
            def entry_signal(self, row, prev, params):
                return True
    ''')
    monkeypatch.setattr(new_strategy, "_is_registered", lambda name: False)
    monkeypatch.setattr(new_strategy, "_run_smoke_backtest", lambda strat: ({"profit_factor": 1.5}, {}))
    out = new_strategy.validate_and_stage("quiet", code, staging_root=tmp_path / "stage", src_root=tmp_path / "src")
    assert out["stage"] == "smoke" and "no trade count" in out["error"]


def test_smoke_requires_every_declared_symbol_to_be_cached(monkeypatch):
    import pandas as pd

    class Partial(SimpleStrategy):
        name = "partial"
        symbols = ["AAA", "BBB", "CCC"]

        def entry_signal(self, row, prev, params):
            return True

    have = {"AAA": pd.DataFrame({"Date": pd.date_range("2025-01-01", periods=3), "Open": 1.0, "High": 1.0,
                                 "Low": 1.0, "Close": 1.0, "Volume": 1})}
    from tradelab.marketdata import cache
    monkeypatch.setattr(cache, "read", lambda sym, tf: have.get(sym))
    with pytest.raises(RuntimeError) as ei:
        new_strategy._run_smoke_backtest(Partial())
    assert "BBB" in str(ei.value) and "CCC" in str(ei.value) and "AAA" not in str(ei.value).split("cache:")[1]


def test_call_hook_counts_only_positional_parameters():
    class KwOnly(SimpleStrategy):
        name = "kw"
        def entry_signal(self, row, prev, params, *, strict=False):
            return prev is not None

    out = KwOnly().generate_signals(_bars())
    assert out["AAA"]["buy_signal"].sum() >= 50


def test_cli_run_reports_strategy_load_error_not_missing_symbols(monkeypatch):
    from tradelab import cli_run
    import tradelab.registry as reg

    def boom(name):
        raise ImportError("bad module")

    monkeypatch.setattr(reg, "load_strategy_class", boom)
    syms, err = cli_run._declared_symbols_for("whatever")
    assert syms == [] and "ImportError" in err
