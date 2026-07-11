# Tiered Analysis v2 — Implementation Plan (Slices)

> Companion to `docs/tiered-analysis-design.md` (§8 "v2 — Quantities + Tier 2/3").
> Written 2026-07-11, before any v2 code. This file is committed to the repo so the
> plan survives; per-slice working notes may accumulate in `.claude/reviews/`
> (local-only, not tracked by git).

## What v2 delivers, in plain language

v1 answers **"should I buy this stock, and at what prices?"** v2 adds two things:

1. **"How many shares?"** — position sizing. This is pure arithmetic, never AI:
   given how much money you have, what fraction of it you're willing to lose on one
   trade, and the gap between the entry price and the stop-loss price, a formula
   computes the share count. Off by default; only shown when the user opts in by
   entering their capital and risk tolerance.
2. **Deeper AI scrutiny of the call** — two new analysis layers on top of Tier 1:
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

## Slice 3 — Tier 2: bull/bear debate stage

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

## Slice 4 — Tier 3: risk stress test stage

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

## Slice 5 — Pipeline, persistence, and API integration

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

## Slice 6 — Web surface

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
- All new vocabulary goes through the popup system (`metricLabels.ts` /
  `tiered.help.*`), tap-friendly; both languages.
- **Acceptance**: lint + build green, component tests for the depth selector and
  sizing card states (on / off / refused), old stored v1 runs render unchanged,
  live check in the browser.

---

## Order and rationale

1 → 2 are pure deterministic code (cheap, fully testable offline) and everything else
depends on them. 3 → 4 are the LLM stages, each independently shippable behind the
existing placeholders. 5 wires and persists; 6 makes it visible. After each slice:
scoped offline tests, commit; live verification at slices 3, 5, and 6.

## Explicitly out of scope for v2

- Backtesting (v3 — the trust pillar *validating* these share counts).
- Portfolio awareness / Tier 4 (v4).
- Chatbot/MCP, node GUI, native retail-forum sentiment (v5+).
- Automatic daily deep runs — depth stays a manual, per-run choice in v2.

## Status

| Slice | Status |
| --- | --- |
| 1. Sizing engine | **done** (2026-07-11) — `src/tiered_analysis/sizing.py`, 19 offline tests in `tests/test_tiered_sizing.py` |
| 2. ATR stops | not started |
| 3. Tier 2 debate | not started |
| 4. Tier 3 risk stress | not started |
| 5. Pipeline/API integration | not started |
| 6. Web surface | not started |
