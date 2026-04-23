"""Gate independence check — Pearson correlation between indicator gates.

Ported conceptually from deepvue_mcp/server.py's ``dv_gate_independence``.
Rationale: when a strategy combines multiple filter gates, you want them to
carry independent information. Two gates with correlation > 0.7 are
effectively redundant — dropping one should not change the signal much.
This is the "before you tune, verify" diagnostic tradelab didn't have.

Public entrypoint:

    check_gate_independence(symbols, gates, timeframe='1D')

Computes each gate's column via ``indicators.compute_all_indicators`` (or
picks from it by name), concatenates across all symbols, then computes
pairwise Pearson correlation. Returns a list of pair rows and a summary
DataFrame for CLI display.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

import numpy as np
import pandas as pd

from ..config import get_config
from ..indicators import compute_all_indicators
from ..marketdata import download_symbols


@dataclass
class GatePairResult:
    gate_a: str
    gate_b: str
    correlation: float
    overlap_pct: Optional[float]   # for boolean-ish gates only
    n_samples: int
    recommendation: str


def _recommend(corr: float) -> str:
    abs_c = abs(corr)
    if abs_c > 0.7:
        return "REDUNDANT (|r|>0.7) - drop one"
    if abs_c > 0.4:
        return "OVERLAPPING (|r|>0.4) - consider as soft score, not hard gate"
    if abs_c > 0.2:
        return "MILD OVERLAP (|r|>0.2) - usable as soft-weighted"
    return "INDEPENDENT (|r|<=0.2) - good hard-gate candidate"


def check_gate_independence(
    symbols: Iterable[str],
    gates: list[str],
    benchmark: str = "SPY",
) -> list[GatePairResult]:
    """Compute pairwise correlations across all listed gates.

    Args:
        symbols: iterable of ticker symbols to load
        gates: list of indicator column names (must appear in
               ``compute_all_indicators`` output, e.g. 'adr_pct_20d',
               'relative_volume_20d', 'sigma_spike', 'minervini_template')
        benchmark: benchmark symbol for RS-based indicators

    Returns:
        list of GatePairResult, one per unique pair
    """
    if len(gates) < 2:
        raise ValueError("Need at least 2 gates to compare")

    symbols = [s for s in symbols if s != benchmark]
    cfg = get_config()
    data = download_symbols(
        list({*symbols, benchmark}),
        start=cfg.defaults.data_start,
        end=cfg.defaults.data_end,
    )
    bench_df = data.get(benchmark)

    per_symbol_indicators: list[pd.DataFrame] = []
    for sym in symbols:
        if sym not in data:
            continue
        df = data[sym]
        try:
            all_ind = compute_all_indicators(df.set_index("Date"), bench_df.set_index("Date") if bench_df is not None else None)
        except Exception:
            continue
        missing = [g for g in gates if g not in all_ind.columns]
        if missing:
            raise ValueError(
                f"Unknown gate(s): {missing}. Available: {sorted(all_ind.columns)}"
            )
        per_symbol_indicators.append(all_ind[gates])

    if not per_symbol_indicators:
        raise ValueError("No symbols produced usable indicator data")

    stacked = pd.concat(per_symbol_indicators, axis=0)
    # Boolean-ish gates: coerce to float 0/1 for correlation
    for g in gates:
        if stacked[g].dtype == bool or str(stacked[g].dtype).startswith("Int"):
            stacked[g] = stacked[g].astype(float)

    out: list[GatePairResult] = []
    for i in range(len(gates)):
        for j in range(i + 1, len(gates)):
            a, b = gates[i], gates[j]
            col_a = stacked[a].dropna()
            col_b = stacked[b].dropna()
            common = col_a.index.intersection(col_b.index)
            if len(common) < 30:
                out.append(GatePairResult(
                    gate_a=a, gate_b=b, correlation=float("nan"),
                    overlap_pct=None, n_samples=len(common),
                    recommendation="INSUFFICIENT DATA (<30 aligned samples)",
                ))
                continue
            a_aligned = col_a.loc[common].astype(float)
            b_aligned = col_b.loc[common].astype(float)
            corr = float(a_aligned.corr(b_aligned))

            # Overlap % for boolean-valued series
            overlap: Optional[float] = None
            a_unique = set(np.unique(a_aligned.values))
            b_unique = set(np.unique(b_aligned.values))
            if a_unique <= {0.0, 1.0} and b_unique <= {0.0, 1.0}:
                both = ((a_aligned == 1.0) & (b_aligned == 1.0)).sum()
                either = ((a_aligned == 1.0) | (b_aligned == 1.0)).sum()
                overlap = float(both / either * 100) if either > 0 else 0.0

            out.append(GatePairResult(
                gate_a=a, gate_b=b, correlation=corr,
                overlap_pct=overlap, n_samples=int(len(common)),
                recommendation=_recommend(corr),
            ))
    return out
