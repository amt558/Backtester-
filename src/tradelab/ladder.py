"""The test ladder (S5): named rungs, what a run must be to count, and a
presentation score over the verdict's signals.

    Rung 0 Smoke       upload pipeline, in-process         seconds
    Rung 1 Trial       run --robustness                    minutes     → Tried
    Rung 2 Full trial  run --full --validation-deep        long        → accept-able
    Rung 3 Paper       the daemon (S7)                     weeks       → Paper-qualified

Nothing here touches the verdict engine (robustness/verdict.py is fenced):
the score is a read-only summary of the signals the engine already emitted,
for ranking two ADVISORY strategies — never for deciding anything.

Lives at package top level (not under web/) so the CLI can import it without
pulling in the web package and its job manager.
"""
from __future__ import annotations

import hashlib
import inspect
import json
from statistics import median
from typing import Iterable, Optional

TIER_BASIC, TIER_TRIAL, TIER_FULL = "basic", "trial", "full"

RUNGS = [
    {"rung": 0, "key": "smoke", "label": "Smoke", "command": None,
     "default_estimate": "seconds", "gate": "registers the strategy"},
    {"rung": 1, "key": "trial", "label": "Trial", "command": "run --robustness",
     "default_estimate": "~1–3 min", "gate": "verdict + promotion route"},
    {"rung": 2, "key": "full", "label": "Full trial", "command": "run --full --validation-deep",
     "default_estimate": "~15–40 min", "gate": "required before Accept"},
    {"rung": 3, "key": "paper", "label": "Paper evidence", "command": None,
     "default_estimate": "weeks", "gate": "Paper-qualified (S7)"},
]

COMMAND_TIER = {
    "run": TIER_BASIC,
    "run --robustness": TIER_TRIAL,
    "run --full": TIER_TRIAL,                     # robustness without deep validation
    "run --full --validation-deep": TIER_FULL,
}


def tier_for_flags(*, robustness: bool, full: bool, validation_deep: bool) -> str:
    """The rung a CLI invocation is, from its flags (cli_run records this)."""
    if full and validation_deep:
        return TIER_FULL
    if robustness or full:
        return TIER_TRIAL
    return TIER_BASIC


def code_hash_for_class(cls) -> Optional[str]:
    """sha256 of the strategy class's source FILE (not just the class body:
    helpers and imports in the same file are part of what was tested)."""
    try:
        path = inspect.getsourcefile(cls)
        if not path:
            return None
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except (OSError, TypeError):
        return None


def thresholds_hash(thresholds) -> str:
    """sha256 of the canonical JSON of the verdict configuration (a pydantic
    model or a plain dict). Callers pass the WHOLE RobustnessConfig — not
    only RobustnessThresholds — because knobs like monte_carlo_shuffles,
    noise_sigma_pct, entry_delay_bars and hold_out_window_months change which
    signals exist and what they say, i.e. the verdict."""
    if hasattr(thresholds, "model_dump"):
        thresholds = thresholds.model_dump()
    canon = json.dumps(thresholds, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def full_trial_status(
    run: Optional[dict],
    *,
    current_code_hash: Optional[str],
    current_thresholds_hash: Optional[str],
    canary_mismatch: bool = False,
) -> dict:
    """Does this run entitle the strategy to be accepted?

    Returns {"ok": bool, "reason": str | None, "code": str | None} where code is
    one of: no_run, not_full, unrecorded, code_changed, thresholds_changed,
    canary_mismatch. Fail-closed: anything unknown is a refusal."""
    if not run:
        return {"ok": False, "code": "no_run", "reason": "no trial on record"}
    tier = run.get("tier")
    if tier != TIER_FULL:
        return {"ok": False, "code": "not_full",
                "reason": "Full trial required — this run was a "
                          + ({"trial": "Trial (robustness only)", "basic": "plain backtest"}.get(tier or "", "run of unknown rung"))}
    if not run.get("code_hash") or not run.get("thresholds_hash"):
        return {"ok": False, "code": "unrecorded",
                "reason": "trialled before code/thresholds hashes were recorded — run a Full trial"}
    if not current_code_hash or not current_thresholds_hash:
        return {"ok": False, "code": "unverifiable",
                "reason": "cannot verify the trial against the current strategy file / config "
                          "(file missing or config unloadable) — fix that, then run a Full trial"}
    if run.get("code_hash") != current_code_hash:
        return {"ok": False, "code": "code_changed",
                "reason": "strategy file changed since this trial — run a Full trial again"}
    if run.get("thresholds_hash") != current_thresholds_hash:
        return {"ok": False, "code": "thresholds_changed",
                "reason": "verdict thresholds changed since this trial — run a Full trial again"}
    if canary_mismatch:
        return {"ok": False, "code": "canary_mismatch",
                "reason": "engine integrity check is failing (a canary verdict is out of its expected set) — fix that first"}
    return {"ok": True, "code": None, "reason": None}


_POINTS = {"robust": 1.0, "inconclusive": 0.5, "fragile": 0.0}


def score_from_signals(signals: Iterable[dict]) -> Optional[float]:
    """0–1 presentation score: mean of robust=1 / inconclusive=0.5 / fragile=0
    over the signals the suite emitted; a hard regime override caps it at
    0.25. None when there are no signals. Ranks; never decides."""
    sig = [s for s in signals if isinstance(s, dict) and s.get("outcome") in _POINTS]
    if not sig:
        return None
    pts = [_POINTS[s["outcome"]] for s in sig if s.get("name") != "regime_spread_hard"]
    if not pts:
        return 0.0
    score = sum(pts) / len(pts)
    # The engine's own aggregation rule (verdict.py): 2+ fragile, or 1 fragile
    # with no robust, is FRAGILE regardless of the rest. The presentation
    # score must never rank a FRAGILE mix above an INCONCLUSIVE one, so it is
    # capped below 0.5 in exactly that case.
    n_fragile = sum(1 for s in sig if s.get("outcome") == "fragile" and s.get("name") != "regime_spread_hard")
    n_robust = sum(1 for s in sig if s.get("outcome") == "robust")
    if n_fragile >= 2 or (n_fragile >= 1 and n_robust == 0):
        score = min(score, 0.49)
    if any(s.get("name") == "regime_spread_hard" and s.get("outcome") == "fragile" for s in sig):
        score = min(score, 0.25)
    return round(score, 3)


def split_signals(signals: Iterable[dict], diagnostics: Optional[dict] = None,
                  extras: Optional[list[dict]] = None) -> dict:
    """Gating = the verdict's own signals (they aggregate into the verdict).
    Read-anyway = diagnostics and other run-folder facts that never change
    the verdict. Each row: {name, outcome, reason}."""
    gating = [{"name": s.get("name"), "outcome": s.get("outcome"), "reason": s.get("reason")}
              for s in signals if isinstance(s, dict) and s.get("name") != "regime_spread_hard"]
    hard = [s for s in signals if isinstance(s, dict) and s.get("name") == "regime_spread_hard"]
    read_anyway: list[dict] = []
    for k, v in (diagnostics or {}).items():
        read_anyway.append({"name": k, "outcome": "info",
                            "reason": (f"{v:.3f}" if isinstance(v, (int, float)) and v is not None else str(v))})
    for e in extras or []:
        read_anyway.append(e)
    return {"gating": gating, "read_anyway": read_anyway,
            "hard_override": [{"name": s.get("name"), "reason": s.get("reason")} for s in hard]}


def rung_estimates(jobs: Iterable[dict], *, last_n: int = 5) -> dict[str, dict]:
    """Per rung: median wall-clock of the last N completed jobs with that
    command, or the default label. {key: {label, seconds|None, from_history}}"""
    from datetime import datetime
    durs: dict[str, list[float]] = {}
    for j in sorted(jobs, key=lambda x: x.get("started_at") or ""):
        if j.get("status") != "done" or not j.get("started_at") or not j.get("ended_at"):
            continue
        try:
            a = datetime.fromisoformat(str(j["started_at"]).replace("Z", "+00:00"))
            b = datetime.fromisoformat(str(j["ended_at"]).replace("Z", "+00:00"))
        except ValueError:
            continue
        durs.setdefault(j.get("command") or "", []).append((b - a).total_seconds())
    out = {}
    for r in RUNGS:
        hist = durs.get(r["command"] or "", [])[-last_n:]
        if hist:
            secs = median(hist)
            label = f"~{int(round(secs))} s" if secs < 90 else f"~{int(round(secs / 60))} min"
            out[r["key"]] = {"label": label, "seconds": round(secs, 1), "from_history": True}
        else:
            out[r["key"]] = {"label": r["default_estimate"], "seconds": None, "from_history": False}
    return out
