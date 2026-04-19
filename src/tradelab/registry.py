"""
Strategy registry.

Reads the `strategies:` section of tradelab.yaml and dynamically imports
strategy modules. This lets users add strategies by (1) writing a file in
src/tradelab/strategies/ and (2) adding an entry to tradelab.yaml — no
code changes needed anywhere else.
"""
from __future__ import annotations

import importlib
from typing import Optional

from .config import get_config, StrategyEntry


class StrategyNotRegistered(Exception):
    pass


class StrategyModuleMissing(Exception):
    pass


def list_registered_strategies() -> dict[str, StrategyEntry]:
    """Return the raw dict of registered strategies from config."""
    return get_config().strategies


def get_strategy_entry(name: str) -> StrategyEntry:
    """Look up a registered strategy's config entry by friendly name."""
    strategies = list_registered_strategies()
    if name not in strategies:
        import difflib
        available = sorted(strategies.keys())
        close = difflib.get_close_matches(name, available, n=3, cutoff=0.5)
        suggestion = ""
        if close:
            suggestion = f" Did you mean: {', '.join(close)}?"
        available_str = ", ".join(available) or "(none)"
        raise StrategyNotRegistered(
            f"Strategy '{name}' not registered.{suggestion} "
            f"Available: {available_str}"
        )
    return strategies[name]


def load_strategy_class(name: str):
    """
    Dynamically import the Python class for a registered strategy.
    Returns the class itself (not an instance).
    """
    entry = get_strategy_entry(name)
    try:
        module = importlib.import_module(entry.module)
    except ImportError as e:
        raise StrategyModuleMissing(
            f"Cannot import '{entry.module}' for strategy '{name}': {e}\n"
            f"Check that the file exists and is syntactically valid."
        ) from e

    if not hasattr(module, entry.class_name):
        raise StrategyModuleMissing(
            f"Module '{entry.module}' does not contain class '{entry.class_name}'"
        )

    return getattr(module, entry.class_name)


def instantiate_strategy(name: str, param_overrides: Optional[dict] = None):
    """
    Instantiate a strategy with its configured params, optionally overridden.
    Returns a strategy object ready for use by the engines.
    """
    entry = get_strategy_entry(name)
    StrategyClass = load_strategy_class(name)

    # Merge: default params from strategy class ← config overrides ← caller overrides
    params = {}
    # Config-level params
    params.update(entry.params)
    # Caller-level overrides
    if param_overrides:
        params.update(param_overrides)

    return StrategyClass(name=name, params=params)
