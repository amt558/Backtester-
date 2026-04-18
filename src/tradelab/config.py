"""
Configuration loader for tradelab.

Reads tradelab.yaml from the project root and exposes a typed Config object.
Searches up the directory tree from the current working directory.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


class PathsConfig(BaseModel):
    data_dir: str
    reports_dir: str
    cache_dir: str


class BenchmarksConfig(BaseModel):
    primary: str = "SPY"


class DefaultsConfig(BaseModel):
    initial_capital: float = 100_000.0
    commission_per_trade: float = 1.0
    position_size_pct: float = 25.0
    max_concurrent_positions: int = 5
    data_start: str = "2024-04-08"
    data_end: str = "2026-04-14"
    warmup_days: int = 50


class BacktestConfig(BaseModel):
    timeframe_default: str = "1D"
    session_filter: bool = True


class OptunaConfig(BaseModel):
    n_trials_default: int = 50
    seed: int = 42
    fitness_formula: str = "pf_sqrt_trades_dd"
    min_trades_threshold: int = 20


class WalkForwardConfig(BaseModel):
    train_months: int = 6
    test_months: int = 2
    step_months: int = 2
    n_trials_per_window: int = 30
    warmup_months: int = 2


class RobustnessConfig(BaseModel):
    monte_carlo_shuffles: int = 1000
    noise_sigma_pct: float = 0.05
    param_sensitivity_pct: float = 10.0
    entry_delay_bars: list[int] = Field(default_factory=lambda: [-2, -1, 0, 1, 2])


class StrategyEntry(BaseModel):
    module: str
    class_name: str
    description: str = ""
    status: str = "registered"
    params: dict = Field(default_factory=dict)


class Config(BaseModel):
    paths: PathsConfig
    benchmarks: BenchmarksConfig = BenchmarksConfig()
    defaults: DefaultsConfig = DefaultsConfig()
    backtest: BacktestConfig = BacktestConfig()
    optuna: OptunaConfig = OptunaConfig()
    walkforward: WalkForwardConfig = WalkForwardConfig()
    robustness: RobustnessConfig = RobustnessConfig()
    strategies: dict[str, StrategyEntry] = Field(default_factory=dict)

    # Populated at load time
    config_path: Optional[Path] = None

    def data_path(self) -> Path:
        return Path(self.paths.data_dir)

    def reports_path(self) -> Path:
        p = Path(self.paths.reports_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def cache_path(self) -> Path:
        p = Path(self.paths.cache_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p


def find_config_file(start: Optional[Path] = None) -> Path:
    """
    Walk up from `start` (default: cwd) looking for tradelab.yaml.
    Raises FileNotFoundError if not found after reaching filesystem root.
    """
    cur = (start or Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        path = candidate / "tradelab.yaml"
        if path.exists():
            return path
    raise FileNotFoundError(
        "tradelab.yaml not found. Run from inside the tradelab project folder "
        "or set the TRADELAB_CONFIG environment variable to its path."
    )


def load_config(config_path: Optional[Path] = None) -> Config:
    """Load tradelab.yaml and return a typed Config object."""
    import os

    if config_path is None:
        env_override = os.environ.get("TRADELAB_CONFIG")
        if env_override:
            config_path = Path(env_override)
        else:
            config_path = find_config_file()

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    config = Config(**data)
    config.config_path = config_path
    return config


# Module-level cached config (loaded on first access)
_config: Optional[Config] = None


def get_config(reload: bool = False) -> Config:
    """Get the active config. Caches the first load; pass reload=True to refresh."""
    global _config
    if _config is None or reload:
        _config = load_config()
    return _config
