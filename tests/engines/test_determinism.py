"""Determinism regression tests."""
from __future__ import annotations

import numpy as np
import pandas as pd

from tradelab.determinism import (
    env_fingerprint, hash_config, hash_dataframe, hash_universe, render_footer,
)


def _sample_df(seed=0):
    rng = np.random.default_rng(seed)
    n = 100
    return pd.DataFrame({
        "Date": pd.date_range("2023-01-03", periods=n, freq="B"),
        "Open": rng.normal(100, 1, n),
        "High": rng.normal(101, 1, n),
        "Low":  rng.normal(99,  1, n),
        "Close": rng.normal(100, 1, n),
        "Volume": rng.integers(1000, 10000, n),
    })


def test_hash_dataframe_is_stable():
    df = _sample_df(42)
    assert hash_dataframe(df) == hash_dataframe(df.copy())


def test_hash_dataframe_detects_change():
    df = _sample_df(42)
    df2 = df.copy()
    df2.loc[df2.index[0], "Close"] = df2.loc[df2.index[0], "Close"] + 0.01
    assert hash_dataframe(df) != hash_dataframe(df2)


def test_hash_universe_order_independent():
    a = {"A": _sample_df(1), "B": _sample_df(2)}
    b = {"B": _sample_df(2), "A": _sample_df(1)}
    assert hash_universe(a) == hash_universe(b)


def test_hash_config_stable_on_dict():
    cfg = {"a": 1, "b": [1, 2, 3], "c": {"nested": True}}
    assert hash_config(cfg) == hash_config(cfg)
    assert hash_config(cfg) == hash_config({"c": {"nested": True}, "a": 1, "b": [1, 2, 3]})


def test_env_fingerprint_has_required_keys():
    env = env_fingerprint()
    for key in ("python", "tradelab", "git_commit", "numpy", "pandas"):
        assert key in env


def test_render_footer_is_deterministic():
    a = render_footer("abc123", "def456", {"optuna": 42, "mc": 101})
    b = render_footer("abc123", "def456", {"optuna": 42, "mc": 101})
    assert a == b
    assert "data_sha:   abc123" in a
    assert "seed[optuna]: 42" in a
