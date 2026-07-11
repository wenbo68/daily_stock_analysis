# Tiered Analysis v2 — Implementation Plan (Slices)

> Companion to `docs/tiered-analysis-design.md` (§8 "v2 — Quantities + Tier 2/3").
> Every formula referenced by these slices is defined and explained in
> `docs/tiered-analysis-formulas.md` — keep the two in sync when a slice adds or
> changes a formula. Written 2026-07-11, before any v2 code. This file is committed
> to the repo so the plan survives; per-slice working notes may accumulate in
> `.claude/reviews/` (local-only, not tracked by git).

## What v2 delivers, in plain language

v1 answers **"should I buy this stock, and at what prices?"** v2 adds two things:

1. **"How many shares?"** — position sizing. This is pure arithmetic, never AI:
   given how much money you have, what fraction of it you're willing to lose on one
   trade, and the gap between the entry price and the stop-loss price, a formula
   computes the share count. Off by default; only shown when the user opts in by
   entering their capital and risk tolerance.
2. **Explainable price levels (anchor-and-adjust)** — added 2026-07-11 after design
   discussion. Today all four levels (ideal/backup entry, stop, target) are parsed out
   of LLM prose. v2 replaces that: **deterministic formulas compute a base for every
   level**, then the AI may **adjust each base within a bounded band**, but only with a
   reason anchored to collected evidence (dimension payloads or verified news
   citations). Code re-validates the adjusted set. The UI shows both numbers — base and
   adjusted — each with a click-open modal explaining exactly where it came from. This
   also makes the AI's judgment measurable: v3's backtest can replay base-only vs
   adjusted levels and settle whether the adjustments add value.
3. **Deeper AI scrutiny of the call** — two new analysis layers on top of Tier 1:
   - **Tier 2, the debate**: one AI argues the case *for* the stock (bull), another
     argues *against* (bear), both restricted to the evidence Tier 1 already collected.
     A third AI (the judge) weighs the arguments and issues an updated verdict.
   - **Tier 3, the stress test**: three AI risk reviewers — conservative, aggressive,
     and neutral — poke at the Tier 2 verdict. A risk judge combines them into a final
     stance plus a **size multiplier** (e.g. "conviction is shaky → take half the
     computed position").

Everything follows v1's first principle: **AI decides direction and narrative;
deterministic code computes every number** (shares, stops, multipliers applied).

## Hard constraints carried over from v1

- Never touch the DSA decision path (`src/analyzer.py`, `src/stock_analyzer.py`,
  `src/core/pipeline.py`).
- New config → update `.env.example`. No hardcoded secrets.
- Every slice ships with offline tests (`pytest -m "not network"`), fake-LLM based
  where an LLM is involved. Coverage badges and fail-loud warnings, never silent blanks.
- Sizing **gates on data quality**: if a dimension needed for the numbers is
  `unavailable` (or `is_actionable` is false), the engine refuses to print a share
  count and says why — a missing number is safer than a fake one.
- Old v1 stored runs must keep rendering (additive schema only).

---

## Slice 1 — Deterministic position-sizing engine

**Goal**: `src/tiered_analysis/sizing.py` — pure functions, no I/O, no LLM.

- Core formula (fixed-fractional risk sizing):
  `shares = floor((capital × risk_fraction) / (entry − stop_loss))` for a buy.
- Guardrails, each with an explicit refusal reason instead of a silent 0:
  - no stop-loss, or stop ≥ entry on a buy → refuse ("can't measure risk per share");
  - position value cap (max % of capital in one name, default e.g. 25%);
  - lot-size rounding (A-shares trade in lots of 100; US in single shares);
  - direction is `hold`/`sell` → no size (nothing to open);
  - required inputs missing or non-positive → refuse with reason.
- Trading costs (added 2026-07-11 after user question): optional `fee_fraction` —
  round-trip commission/duty as a fraction of traded value, folded into loss per
  share (`(entry − stop) + entry × fee_fraction`). Default 0 because costs are
  broker- and market-specific; spread/slippage stay out of scope (unknowable here).
- Output: a `SizingResult` (shares, position_value, risk_amount, applied caps,
  refusal reason if any) that fills the `SizingSlots` reserved in `schema.py` since v1.
- **Acceptance**: table-driven offline tests covering the formula, every refusal
  path, lot rounding per market, and the cap. No LLM anywhere in this module.

## Slice 2 — ATR volatility stops

**Goal**: a deterministic stop-loss suggestion so sizing never depends on an
AI-invented stop.

- ATR (average true range — the stock's typical daily price swing) is already computed
  by the v1 technicals provider. Add `suggest_stop(entry, atr, k)` (default k≈2:
  stop = entry − 2×ATR for a buy) in the technicals/sizing layer.
- Precedence rule, recorded in the report: use the Tier 1 level-derived stop when
  present **and** sane (below entry, within a max distance); otherwise fall back to
  the ATR stop; label which one was used.
- **Acceptance**: offline tests for the suggestion math, the precedence rule, and the
  sanity checks; report payload says which stop source was chosen.

## Slice 3 — Deterministic base levels + AI adjustment layer

**Goal**: every price level gets a formula-computed base; the AI becomes a bounded,
evidence-cited editor of those bases instead of the author of the numbers.

- **Base formulas** (`src/tiered_analysis/levels.py`, pure code, inputs already in the
  technicals payload):
  - ideal entry — pullback anchor: max(SMA-20, recent swing low) capped at the current
    close (never suggest buying above the market's own reference);
  - backup entry — deeper support: SMA-60 (or swing low if lower/sounder);
  - stop — `resolve_stop` from slice 2 (level precedence + ATR fallback);
  - target — reward-to-risk multiple: entry + R_MULTIPLE × (entry − stop), default 2.
  - Each base records its formula name and input values so the UI can render
    "formula + plugged-in numbers".
- **Adjustment contract** (`src/tiered_analysis/adjustments.py` — a small
  tiered-package-owned LLM call; the original "extend the Tier 1 synthesis call" idea
  was wrong: Tier 1's synthesis happens inside DSA's protected decision path, which we
  never modify): for each level the AI may return an adjusted value, a reason, and
  evidence references. Hard rules enforced by code, echoing the sentiment anti-fabrication
  contract:
  - band: an adjustment may move a level at most ±1 ATR from its base; outside the
    band → rejected, base used, warning shown;
  - anchoring: every reason must reference collected evidence — a dimension payload
    key or a verified sentiment citation number; unanchored reasons → rejected;
  - post-validation: the adjusted set must still order correctly
    (stop < backup ≤ ideal < target for a buy) and keep a minimum reward-to-risk
    (≥ 1.5); violations → the offending adjustment is rejected, not "fixed" by the LLM.
- **Sizing consumes exactly one stop**: the final validated one. No ambiguity about
  which number feeds the share formula.
- Storage: additive — the report keeps base + adjusted + reasons + citations per level;
  old runs keep rendering.
- **Frontend spec (recorded here; implemented in slice 7)**, per user direction
  2026-07-11: each level tile shows the **deterministic base number** (click → modal
  with the formula, then the formula with plugged-in values; each plugged-in number is
  a hyperlink — technicals inputs anchor-jump to their row on the technicals dimension
  card, whose data source is named there). Below it, the **AI-adjusted number**
  (click → second modal with the AI's reasoning, inline-cited `[n]` like the sentiment
  report, plus a deduped numbered reference section; inline markers and reference
  entries are hyperlinks to the sources).
- **Acceptance**: offline tests for every base formula, the band, anchoring and
  ordering rejections, and the "adjustment rejected → base survives with warning"
  path (fake LLM). Live run shows base + adjusted levels stored.

## Slice 4 — Tier 2: bull/bear debate stage

**Goal**: replace the `Tier2Stage` placeholder in `src/tiered_analysis/tiers.py`
with a real stage. (Reference pattern: TradingAgents `graph/setup.py:122-138`.)

- Inputs: the Tier 1 report + the four dimension results (payloads, sentiment
  narrative with its verified citations).
- Structure: bull argues → bear argues (configurable rounds, default 1) →
  research-manager judge outputs a structured verdict: direction, confidence (0–1),
  key reasons for/against, and what evidence would change its mind.
- **Anti-fabrication contract, same spirit as v1 sentiment**: debaters and judge may
  only reference the supplied evidence bundle; the prompt forbids new facts, and the
  judge's cited claims must point at dimension payload keys or sentiment citation
  numbers. Un-anchored claims are flagged in warnings, not silently trusted.
- Failure handling: any LLM failure → the stage returns `unavailable` coverage with a
  warning and the pipeline falls back to the Tier 1 direction (fail-loud, no crash).
- **Acceptance**: offline tests with a fake LLM covering verdict parsing, evidence
  anchoring, round count, and the fallback path. Live smoke on one ticker.

## Slice 5 — Tier 3: risk stress test stage

**Goal**: replace the `Tier3Stage` placeholder. (Reference: TradingAgents
`graph/setup.py:140-165`.)

- Three risk personas (conservative / aggressive / neutral) each critique the Tier 2
  verdict; a risk judge merges them into: final stance, a **size multiplier**
  ∈ {0, 0.5, 1.0} (deterministic enum, not a free number), stop-loss keep/tighten
  advice, and a plain-language risk summary.
- The multiplier is applied by the slice-1 engine (code), never by the LLM;
  multiplier 0 = "direction stands but don't open a position now", stated explicitly.
- Same evidence-anchoring and fail-loud rules as Tier 2.
- **Acceptance**: fake-LLM offline tests for persona fan-out, judge merging, the
  multiplier being applied by code, and fallback to Tier 2 output on failure.

## Slice 6 — Pipeline, persistence, and API integration

**Goal**: wire tiers 1→2→3 + sizing into the run flow, opt-in and additive.

- `TieredPipeline.run(..., up_to_tier=N)` exercised for N=2,3; per-run depth choice.
- User sizing settings (capital, risk % per trade, position cap) stored with the
  product's existing settings mechanism; **absent settings = sizing stays off**
  (v1 behavior unchanged). `.env.example` updated if any env knob is added.
- `tiered_runs` storage extended additively: tier-2 debate section, tier-3 risk
  section, sizing block. Old rows render as before.
- `POST /api/v1/tiered/analyze` accepts `depth` (1 | 2 | 3, default 1) and optional
  per-run sizing override; responses expose the new sections.
- `signal_log.py` records the final (deepest-tier) direction and, when present, the
  sized position — so the ledger later grades what the user actually saw.
- Cost visibility: the run stores LLM call/token counts per tier, so the UI can say
  what a deeper run cost.
- **Acceptance**: offline tests for depth routing, storage round-trip of old + new
  rows, API contract; live end-to-end run at depth 3 on one ticker.

## Slice 7 — Web surface

**Goal**: expose v2 on the `/tiered` page without cluttering the v1 flow.

- Depth selector at run time ("Standard / + Debate / + Risk stress"), with a
  plain-language popup explaining each level and that deeper = more AI calls = slower
  and costlier.
- Tier 2 card: bull case, bear case, judge verdict with confidence; Tier 3 card:
  three persona takes + final stance and multiplier. Same visual language as v1
  dimension cards (coverage badge, Data notes, popups on every term, en/zh).
- Sizing card: shares, position value, risk amount, which stop was used — or the
  refusal reason in plain words. Settings UI for capital/risk %/cap, with an explicit
  "sizing is off until you fill this in" state.
- Level tiles per the slice-3 frontend spec: base number with a formula modal
  (formula, plugged-in values, inputs hyperlinked to their technicals-card rows),
  AI-adjusted number below it with a reasoning modal (inline `[n]` citations +
  deduped hyperlinked reference section, same machinery as the sentiment report).
- All new vocabulary goes through the popup system (`metricLabels.ts` /
  `tiered.help.*`), tap-friendly; both languages.
- **Acceptance**: lint + build green, component tests for the depth selector and
  sizing card states (on / off / refused), old stored v1 runs render unchanged,
  live check in the browser.

---

## Order and rationale

1 → 2 are pure deterministic code (cheap, fully testable offline) and everything else
depends on them. 3 gives every level a deterministic base plus the bounded AI
adjustment contract — it comes before the debate because the debate argues over the
levels. 4 → 5 are the LLM stages, each independently shippable behind the existing
placeholders. 6 wires and persists; 7 makes it visible. After each slice: scoped
offline tests, commit; live verification at slices 3, 4, 6, and 7.

## Explicitly out of scope for v2

- Backtesting (v3 — the trust pillar *validating* these share counts).
- Portfolio awareness / Tier 4 (v4).
- Chatbot/MCP, node GUI, native retail-forum sentiment (v5+).
- Automatic daily deep runs — depth stays a manual, per-run choice in v2.

## Status

| Slice | Status |
| --- | --- |
| 1. Sizing engine | **done** (2026-07-11) — `src/tiered_analysis/sizing.py`, 19 offline tests in `tests/test_tiered_sizing.py` |
| 2. ATR stops | **done** (2026-07-11) — `src/tiered_analysis/stops.py`, 13 offline tests in `tests/test_tiered_stops.py`; report/pipeline wiring lands with slice 5 |
| 3. Base levels + AI adjustment | **done** (2026-07-11) — `levels.py` + `adjustments.py` + `swing_low_20` payload metric, wired into `run_tiered_analysis`; 39 offline tests; live AAPL run verified (stop/target adjustments accepted in band with cited evidence, entry adjustment rejected by the reward-to-risk floor) |
| 4. Tier 2 debate | not started |
| 5. Tier 3 risk stress | not started |
| 6. Pipeline/API integration | not started |
| 7. Web surface (incl. level modals) | not started |
