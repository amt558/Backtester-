# Option H Project — Handoff & State Document

**Date:** 2026-04-24
**Author:** Amit + Claude (session of 2026-04-24)
**Purpose:** Complete project state so a future session can continue without reading the full conversation transcript.

---

## 0. TL;DR

We pivoted away from "validate the tradelab verdict engine against live trading data" (impossible — the engine was scoring placeholder strategies that aren't really trading) toward **Option H: Pine Script on TradingView is the single source of truth; Python scores via CSV import and executes via webhook bridge.**

**Session 1 is DONE.** TradingView alerts round-trip end-to-end to Alpaca paper through a FastAPI receiver exposed via ngrok. Proven with 4 real consecutive TV fires at 13:20–13:23 ET on 2026-04-24, all 200 OK, all filled at Alpaca.

**Remaining:** Session 2 (CSV scoring adapter), Session 3 (dashboard card UI), Session 4 (retire the old bot).

---

## 1. The pivot — why we're here

Original framing (top of this session):
- "Validate the verdict engine by comparing its predictions against live paper trading outcomes"
- Assumed: engine had predictive power worth measuring; live trading was real

Revelations during audit:
1. **The 6 strategies on the Alpaca bot are placeholders** (S2/S4/S7/S8/S10/S12). Amit is developing real strategies in Pine Script, and they'll replace the placeholders.
2. **Live trading is near-empty:** 20 Alpaca fills total over 3 days (Apr 15-17), bot dead since Apr 16, position_map empty. Retrospective calibration is impossible.
3. **Architectural split:** live bot loads strategies from `C:/TradingScripts/FINAL STRATEGYIE/` using a self-contained pandas interface; tradelab loads from `tradelab.strategies.*` using a framework interface. Two separate codebases for each strategy, inevitable drift.

New framing (agreed):
- Current objective is **mechanical readiness**, not verdict validity.
- When a real Pine-converted strategy arrives, the plumbing must work.
- Verdict calibration is deferred until real strategies accumulate history.

**Chosen path: Option H** (from a 4-option set A/B/C/D/E/F/G/H/I/J/K researched via web agents):
- Pine authoring + execution stays on TradingView
- tradelab scores by importing the trade CSV TradingView exports
- Live execution via self-hosted FastAPI webhook receiver (not the old bot)
- Zero Python translation of strategy logic

---

## 2. Amit's approved workflow design (immutable)

1. Write Pine in TradingView (optionally with Claude-chat help).
2. Backtest in TV Strategy Tester → export CSV.
3. Paste CSV into dashboard Research tab → tradelab scores it → verdict + tearsheet displayed.
4. If acceptable → click Accept → dashboard freezes source + params + symbol + CSV + verdict into a `pine_archive/{card_id}/` folder and creates a strategy card (starts OFF).
5. Toggle card ON → webhook receiver routes Pine alerts for that card_id to Alpaca paper orders.
6. To change a strategy: cards are **immutable**. Disable + Flatten + Delete, then re-approve with a new name.
7. Auto-versioning: user types base name + symbol (e.g., `viprasol-amzn`), dashboard auto-appends `-v1`, `-v2` on reuse.
8. Historical trades survive card deletion (audit DB keeps them; only UI card goes away).

Drift is eliminated by design — cards cannot mutate. No fingerprint validation needed in the receiver because card_id IS the version.

See `project_option_h_workflow_design.md` memory + `option_h_walkthrough.pdf` in this folder.

---

## 3. Current state (as of end of Session 1)

### Processes running (may survive Windows reboot? NO — need manual restart)

| Process | Port | PID at end of session | Purpose |
|---|---|---|---|
| uvicorn receiver | 8878 | (new after restart mid-session) | FastAPI webhook handler |
| ngrok tunnel | 4040 (inspector) | 37572 | Public URL routing to :8878 |
| dashboard `launch_dashboard.py` | 8877 | 38108 | Existing TradingScripts dashboard |

### Public webhook URL (ephemeral — changes on ngrok restart)

```
https://deliverer-prorate-manpower.ngrok-free.dev
```

Free-tier ngrok URLs are per-session. Windows reboot = new URL. To make stable: migrate to Cloudflare Tunnel (named tunnel, free forever) — noted as a side-quest for Session 2 start.

### Credentials in use

All in `C:/TradingScripts/alpaca_config.json` (gitignored):
- `api_key`: `PKTOZ23SKKN4KUNTASEVDMZE5B`
- `secret_key`: `7gYjyGoghJhC8BWYkqdkyjWan3L7PJW6mBwPDVgWqGtC`
- `paper_trading`: true

Also in transcript (all three):
- Two older Alpaca keys not yet revoked at alpaca.markets: `PKWSZYOGPBP67Y4WTMFJYYO6X5` (pre-Session work) and `PKKOHFVXTZ5VQ7G3ZLKDNYRJ7U` (Part 2 rotation). Amit should revoke these.
- Twelve Data key unrotated (same `02d795…27bc8b` value re-sent in earlier transcripts). Low blast radius but on Amit's list.
- Ngrok authtoken (`3CoNVHQUGUjwsBfHuDvfsqVIwaU_83wb1w2hGD9tSTpwGxCGx`) now stored at `C:/Users/AAASH/AppData/Local/ngrok/ngrok.yml`. Can be regenerated anytime at ngrok.com.

### Card registry (`C:/TradingScripts/tradelab/live/cards.json`)

Three test cards:
- `test-amzn-v1` — enabled, AMZN, 1 share fixed, test secret
- `test-amzn-disabled` — disabled (used to verify rejection path)
- `smoke-test-v1` — enabled, AMZN, 1 share (matches the card_id Amit used in his TV smoke-test alert)

All use the same non-production secret `test-secret-not-for-production`. **Delete these cards before going to real production.**

---

## 4. What's done in Session 1 (detailed)

### Code (all version-controlled)

```
C:/TradingScripts/tradelab/src/tradelab/live/
├── __init__.py         Package docstring only
├── schema.py           Pydantic AlertPayload (TV webhook JSON) + OrderResult
├── cards.py            CardRegistry — JSON-backed, thread-safe read
├── alpaca_client.py    Thin alpaca-py wrapper; reads creds from alpaca_config.json once
└── receiver.py         FastAPI app. Endpoints: GET /health, POST /webhook
```

### Dependencies installed (via pip + winget)

- `fastapi` 0.136.1
- `uvicorn` 0.46.0
- `alpaca-py` 0.43.2 (modern SDK; the old bot uses `alpaca-trade-api` which will be retired in Session 4)
- `httpx` 0.28.1
- `ngrok` 3.38.0 (via winget, then self-updated)

### Runtime data (gitignore candidate)

```
C:/TradingScripts/tradelab/live/
├── cards.json          Card registry state
└── alerts.jsonl        Append-only log of every webhook event (accepted + rejected)
```

### Validation completed

Local curl battery (6/6 pass):
- valid buy → 200 + Alpaca order ✅
- bad secret → 403 ✅
- disabled card → 403 ✅
- unknown card_id → 404 ✅
- symbol mismatch → 422 ✅
- invalid JSON → 400 ✅

Public URL battery (via ngrok):
- `GET /health` from internet → 200 ✅
- `POST /webhook` with valid card → 200 + filled Alpaca order ✅
- Round-trip buy + sell through public URL ✅

**Live TradingView integration (the real proof):**
- User created a TV alert on a 1-minute AMZN chart with the smoke Pine
- 4 consecutive TV alerts at 13:20–13:23 ET → all 200 OK → all filled at Alpaca
- Source IP `34.212.75.30` confirmed as TradingView's webhook IP
- Position ended flat; user paused the alert

---

## 5. What remains

### Session 2 — CSV scoring adapter (~2-3 days)

**Goal:** user pastes a TradingView Strategy Tester CSV into a dashboard textarea, tradelab's verdict engine scores it, dashboard displays the result.

**Build tasks:**
1. New CLI command: `tradelab score-from-trades <csv-path> [--universe <name>] [--symbol <sym>] [--name <card-base-name>]`
2. TV CSV parser:
   - Input format: Trade# / Type / Date/Time / Signal / Price / Contracts / Profit / Run-up / Drawdown / Cum P&L
   - Pair up entry/exit rows by trade number
   - Normalize to tradelab's internal trade-record schema (see `src/tradelab/engines/*` for the existing format)
3. Feed to verdict engine — DSR, LOSO (if per-symbol CSVs provided), MC drawdown, regime spread, verdict aggregation
4. Write a `run_record` into audit DB so the run appears in the dashboard's Research tab pipeline row
5. Store the CSV into `reports/{card_base_name}_{timestamp}/` folder alongside a synthetic `dashboard.html` + `executive_report.md`

**Known degradations vs code-based scoring (accepted):**
- No Optuna optimization
- No automated walk-forward (user can approximate by testing in TV over rolling windows and importing each CSV)
- No what-if sliders
- No entry-delay / noise-injection stress tests (code required)
- LOSO only works with per-symbol CSVs (user runs Pine on each symbol separately)

**Session 2 deliverable:** user pastes Viprasol v8.2 AMZN CSV → sees a verdict.

### Session 3 — Dashboard card UI (~2 days)

**Goal:** the Accept button + card registry + delete flow, all in the Research tab of the existing dashboard.

**Build tasks:**
1. Research tab UI: textarea for CSV paste, Pine source paste, Accept button
2. POST /tradelab/approve-strategy backend handler → writes to `pine_archive/{card_id}/` + card.json registry entry + triggers Session 2 scoring + renders verdict
3. Live Strategies panel: extend existing strategy cards to include the new cards (from `tradelab/live/cards.json` + its Pine-archive record)
4. Delete flow: two-step confirm (type card name), block delete if card is ON or has open positions, offer Flatten + Disable + Delete combo button
5. Auto-versioning: base-name + symbol derivation → `-v{n}` increment on reuse
6. Receiver change: make `cards.py::CardRegistry.reload()` auto-trigger after card registry writes (probably via file-watch or explicit `/internal/reload` endpoint)

### Session 4 — Retire the old bot + cleanup (~half day)

**Goal:** remove the old dual-code architecture.

**Tasks:**
1. Delete `C:/TradingScripts/alpaca_trading_bot.py` (replaced by FastAPI receiver)
2. Delete `C:/TradingScripts/FINAL STRATEGYIE/` folder (no longer needed; Pine runs on TV)
3. Simplify `alpaca_config.json`: remove the `strategies[]` array (card registry replaces it); keep alpaca creds, trading limits, logging
4. Delete `C:/TradingScripts/launcher.py` and `C:/TradingScripts/run_dashboard.bat` (stale :8000 launcher per the mechanical readiness audit)
5. Update `Launch_Dashboard.bat` / `research_dashboard.bat` to also start the webhook receiver
6. Write the **runbook**: "how Amit adds a new strategy end-to-end" (doc, ~2h)
7. Migrate ngrok → Cloudflare Tunnel for stable URL

### Pre-Session-2 housekeeping (optional, can batch)

- Commit Session 1 code (not yet committed as of end-of-session 2026-04-24)
- Delete three test cards from `cards.json` once you have one real card
- Rotate the two old Alpaca keys at alpaca.markets
- Rotate Twelve Data key at twelvedata.com

---

## 6. The Option H end-state architecture

```
┌──────────────────┐       ┌────────────────────┐       ┌────────────┐
│   TradingView    │       │  Windows box       │       │   Alpaca   │
│  (single source) │       │                    │       │   paper    │
│                  │       │ ┌────────────────┐ │       │            │
│  Pine source ────┼──CSV──┼─▶ score-from-   │ │       │            │
│                  │       │ │  trades (CLI)  │ │       │            │
│                  │       │ └───────┬────────┘ │       │            │
│                  │       │         │          │       │            │
│                  │       │ ┌───────▼────────┐ │       │            │
│                  │       │ │ verdict engine │ │       │            │
│                  │       │ └───────┬────────┘ │       │            │
│                  │       │         │          │       │            │
│                  │       │ ┌───────▼────────┐ │       │            │
│                  │       │ │   Dashboard    │◀┼──positions (read)─│
│                  │       │ │  :8877         │ │       │            │
│                  │       │ │ (Research tab) │ │       │            │
│                  │       │ └───────┬────────┘ │       │            │
│                  │       │         │ Accept   │       │            │
│                  │       │ ┌───────▼────────┐ │       │            │
│                  │       │ │ pine_archive/  │ │       │            │
│                  │       │ │ cards.json     │ │       │            │
│                  │       │ └───────┬────────┘ │       │            │
│   Alerts ────────┼───────┼─▶ ngrok ────▶    │ │       │            │
│   (live bars,    │       │ ┌─────▼──────────┐│       │            │
│    strategy.*    │       │ │ FastAPI        │├──orders──▶         │
│    order fills)  │       │ │ receiver :8878 ││       │            │
│                  │       │ └────────────────┘│       │            │
└──────────────────┘       └────────────────────┘       └────────────┘
```

**Data flows:**
- Blue path (research): Pine → TV → CSV → tradelab → verdict → dashboard → archive
- Green path (live): Pine → TV alert → ngrok → receiver → Alpaca
- Dashboard reads Alpaca positions for the Live Strategies panel (unchanged from today)

**Retired:**
- `alpaca_trading_bot.py` (replaced by FastAPI receiver)
- `FINAL STRATEGYIE/*.py` (Pine lives on TV instead)
- `tradelab.strategies.s2/s4/s7/s8/…` placeholders (only canaries + new real Pine-backed cards remain)

---

## 7. Reference: the Pine strategy Amit is starting with

**Name:** Viprasol v8.2 (Pine port of viprasol_multi.py)
**Planned symbols:** AMZN, MU (separate cards per symbol — `viprasol-amzn-v1`, `viprasol-mu-v1`)
**Default timeframe:** 1H
**Key properties:**
- `process_orders_on_close = true` (good — backtest/live timing parity)
- `calc_on_every_tick = false` (good — deterministic)
- `pyramiding = 0` (one open position at a time)
- `default_qty_type = strategy.percent_of_equity, default_qty_value = 95`
- Score: 10 boolean components (vwap/ema/volume/rsi/macd/atr/rs) combined into 0-10 score; entry when `score >= min_score (5)`
- Uses `request.security(AMEX:SPY, ...)` for benchmark RS (SPY is data-only, not traded; CSV export handles this cleanly)

Full source is in Amit's conversation transcript (reply-before-last with "revid correted pisn script code"). Once Session 2+3 land, this source will live at `pine_archive/viprasol-amzn-v1/strategy.pine`.

**Alert JSON template** (paste into TV alert dialog Message field):
```json
{
  "card_id": "viprasol-amzn-v1",
  "secret": "<from card record>",
  "action": "{{strategy.order.action}}",
  "symbol": "{{ticker}}",
  "contracts": "{{strategy.order.contracts}}",
  "price": "{{strategy.order.price}}",
  "market_position": "{{strategy.market_position}}",
  "position_size_after": "{{strategy.position_size}}",
  "order_id": "{{strategy.order.id}}",
  "order_comment": "{{strategy.order.comment}}",
  "bar_time": "{{time}}",
  "bar_close": "{{close}}"
}
```

---

## 8. Key memories a future session must load

All in `C:/Users/AAASH/.claude/projects/C--Users-AAASH/memory/`:

- `project_option_h_workflow_design.md` — Amit's immutable-card workflow
- `project_tradelab_placeholder_strategies.md` — S2/S4/S7/S8/S10/S12 are scaffolding
- `project_tradelab.md` — general tradelab context
- `project_tradelab_web_dashboard.md` — v1 Research tab history
- `feedback_web_over_hotkeys.md` — Amit prefers web UI over hotkeys
- `feedback_plan_grep_verification.md` — verify plan selectors against code first
- `reference_alpaca_config_location.md` — creds in JSON, not env
- `reference_powershell_utf8_bom.md` — UTF-8 BOM gotcha for PS-written JSON
- `reference_launch_dashboard_probe.md` — namespace-package probe gotchas

---

## 9. Quick resume instructions

If this session ended cleanly and you're picking back up, first steps:

```powershell
# 1. Confirm directory
cd C:\TradingScripts\tradelab

# 2. Check git state
git status
git log --oneline -5

# 3. Check if receiver + ngrok are still running
Get-NetTCPConnection -LocalPort 8878 -State Listen -ErrorAction SilentlyContinue
Get-NetTCPConnection -LocalPort 4040 -State Listen -ErrorAction SilentlyContinue

# If BOTH are listening: everything's fine, skip to step 6
# If either is down, continue:

# 4. Restart the receiver (if not running)
$env:PYTHONPATH = "src"; $env:PYTHONIOENCODING = "utf-8"
Start-Process python -ArgumentList "-m uvicorn tradelab.live.receiver:app --host 127.0.0.1 --port 8878" -WindowStyle Hidden
# or in foreground for debugging:
python -m uvicorn tradelab.live.receiver:app --port 8878

# 5. Restart ngrok (if not running) — NOTE public URL will CHANGE
$NGROK = "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Ngrok.Ngrok_Microsoft.Winget.Source_8wekyb3d8bbwe\ngrok.exe"
Start-Process $NGROK -ArgumentList "http 8878" -WindowStyle Hidden
# wait 3s, then:
(Invoke-RestMethod "http://127.0.0.1:4040/api/tunnels").tunnels[0].public_url

# 6. Verify health
Invoke-RestMethod http://127.0.0.1:8878/health
Invoke-RestMethod http://localhost:8877/api/v2/account | Select-Object status, cash

# 7. Read this doc + the linked memories.
```

To start Session 2 work:
- Read `tradelab/src/tradelab/engines/` to find the internal trade-record format for the existing backtest engine. The CSV adapter must emit records in that shape.
- Read `tradelab/src/tradelab/audit/` (audit_reader.py etc.) to understand how runs are stored — Session 2's CSV import must write a compatible run row.
- Look at existing `tradelab/reports/s2_pocket_pivot_2026-04-22_182021/` for the report directory structure Session 2 must produce.

---

## 10. Open questions / decisions still pending

1. **Cloudflare Tunnel migration** — side-quest at Session 2 start. ~20 min. Gives stable URL so TV alerts don't break on ngrok restart. Recommended before any real Pine strategy goes on the receiver.
2. **Gitignore policy for `tradelab/live/`** — runtime data (cards.json, alerts.jsonl) contains secrets. Probably should gitignore `tradelab/live/*` but keep the `src/tradelab/live/` code. To decide at commit time.
3. **Receiver run-as-service** — currently manual uvicorn launch. For production 24/7, wrap as a Windows service (via `nssm` or `pywin32`) so it survives reboot. Session 4 task.
4. **Retry / reconciliation on missed alerts** — if receiver is down when TV fires, the alert is lost. Need nightly reconciliation job: compare Alpaca fills to expected-trades from Pine alerts. Session 4+ task.
5. **Commit the Session 1 code** — pending Amit's call.

---

## 11. Retired ideas (don't revisit)

These were considered and rejected during the research phase. Future sessions should NOT propose them again:

- **Pynescript (Pine runtime in Python):** parser-only, not executable.
- **PyneCore / PyneSys:** OSS runtime + closed-source SaaS compiler; lock-in risk + unverified bar-for-bar parity.
- **vectorbt Pine compat:** maintainer has no plans.
- **TradersPost SaaS ($49-$199/mo):** more expensive than self-host + "failed orders not retried" warning.
- **SignalStack per-signal pricing:** uneconomic at 5+ strategies.
- **Alertatron / 3Commas:** crypto only, no Alpaca stocks.
- **Forward parallel-paper calibration (30-60 day experiment):** requires real strategies trading; strategies are placeholders.
- **Retrospective engine calibration:** insufficient live-trade data (20 fills across 3 days, no strategy attribution).
- **Fingerprint-based drift validation in receiver:** unnecessary because cards are immutable.
- **Editing cards in place:** explicitly rejected by Amit; iteration = delete + recreate.

---

## 12. Success criteria for end-state (Option H fully shipped)

When all 4 sessions complete, the end-state is:

- [ ] User writes Pine in TradingView
- [ ] User backtests in TV Strategy Tester, exports CSV
- [ ] User opens dashboard Research tab → pastes CSV + Pine source → names base
- [ ] Dashboard scores with tradelab verdict engine + tearsheets
- [ ] User clicks Accept → card created (starts OFF), archived immutably
- [ ] User flips card ON → webhook receiver accepts matching alerts
- [ ] User creates TV alert pointing at stable Cloudflare Tunnel URL
- [ ] Pine alerts fire on live bars → receiver → Alpaca paper orders
- [ ] Dashboard Live Strategies panel shows positions from Alpaca
- [ ] To change a strategy: Disable + Flatten + Delete + new card (never edit)
- [ ] Old `alpaca_trading_bot.py` and `FINAL STRATEGYIE/` gone
- [ ] Runbook documents the full flow

**Proven end-to-end today** (Session 1): the last 3 lines of that list.
**Remaining:** the first 8 lines.

---

**End of handoff.** ~1 focused week of work remaining across 3 sessions to complete Option H.
