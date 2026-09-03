"""S6 (2026-09-03) — the override policy inside the paper engine: capped
sizing while active, zero once expired, auto-Off on the tick."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tradelab import override as ov
from tradelab.live import strategy_runner as sr

NOW = datetime(2026, 9, 3, 14, 0, tzinfo=timezone.utc)


def _card(**over):
    c = {"card_id": "adv-v1", "symbol": "NVDA", "status": "enabled", "source": "python", "mode": "paper",
         "timeframe": "1D", "allocation_usd": 1000.0, "strategy": "adv"}
    c.update(over)
    return c


def _override(days_left):
    return {"reason": "x" * 20, "granted_at": (NOW - timedelta(days=1)).isoformat(),
            "expires_at": (NOW + timedelta(days=days_left)).isoformat(), "allocation_cap_pct": 50.0}


def test_effective_allocation_policy():
    assert ov.effective_allocation(_card(), NOW) == 1000.0                       # no override → as is
    assert ov.effective_allocation(_card(override=_override(10)), NOW) == 500.0  # active → capped
    assert ov.effective_allocation(_card(override=_override(-1)), NOW) == 0.0   # expired → nothing
    assert ov.is_active(_card(override=_override(10)), NOW) and ov.is_expired(_card(override=_override(-1)), NOW)
    assert ov.days_left(_card(override=_override(10)), NOW) == 10


def test_reconcile_sizes_from_capped_allocation_while_active():
    sent = []
    r = sr.reconcile_card(card=_card(override=_override(10)), desired="long", actual_qty=0, price=100.0,
                          bar_date="2026-09-03", submit_fn=lambda *a, **k: sent.append((a, k)), now=NOW)
    assert r == {"action": "buy", "qty": 5}          # 1000 × 50% / 100 = 5, not 10
    assert sent[0][0][:3] == ("NVDA", "buy", 5)


def test_reconcile_never_enters_on_an_expired_override_but_still_exits():
    sent = []
    r = sr.reconcile_card(card=_card(override=_override(-1)), desired="long", actual_qty=0, price=100.0,
                          bar_date="2026-09-03", submit_fn=lambda *a, **k: sent.append(a), now=NOW)
    assert r["action"] == "skip" and "override expired" in r["reason"] and sent == []
    r = sr.reconcile_card(card=_card(override=_override(-1)), desired="flat", actual_qty=7, price=100.0,
                          bar_date="2026-09-03", submit_fn=lambda *a, **k: sent.append(a), now=NOW)
    assert r == {"action": "sell", "qty": 7}         # exits are never capped or blocked


def test_run_tick_switches_off_expired_overrides_and_stamps_them(monkeypatch):
    updates = []

    class _Reg:
        def __init__(self):
            self.cards = {"adv-v1": _card(override=_override(-1)),
                          "ok-v1": _card(card_id="ok-v1", override=_override(5)),
                          "plain-v1": _card(card_id="plain-v1")}
        def all(self):
            return {k: dict(v) for k, v in self.cards.items()}
        def update(self, cid, fields):
            updates.append((cid, fields)); self.cards[cid].update(fields)

    seen = []
    monkeypatch.setattr(sr, "run_once", lambda cards, *, deps, bar_date, now=None: seen.extend(cards) or {k: {"action": "none"} for k in cards})
    reg = _Reg()
    sr.run_tick(registry=reg, deps={}, now=NOW)
    assert [u[0] for u in updates] == ["adv-v1"]
    assert updates[0][1]["status"] == "disabled" and updates[0][1]["override_expired_at"].startswith("2026-09-03")
    assert sorted(seen) == ["ok-v1", "plain-v1"]      # the expired card was not traded this tick
    # idempotent: the next tick does not re-stamp
    sr.run_tick(registry=reg, deps={}, now=NOW + timedelta(hours=1))
    assert len(updates) == 1
