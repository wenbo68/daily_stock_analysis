# Intel Section Redesign — Agentic Qualitative Collector + 6 Subject Reports

Status: approved design, ready to implement (2026-07-23).
Scope: tiered (alt) analysis page only. Legacy DSA report untouched.

## 1. Goal

Replace the tiered page's flat 4-dimension report section with an **Intel**
section of six subject reports, and replace the current single-shot sentiment
pipeline with an **agentic qualitative collector** (ChatGPT-style iterative
search) whose output is forced into a pydantic schema.

```
INTEL
├── Econ          — deterministic (exists: MacroEconProvider)
├── Technicals    — deterministic (exists: TechnicalsProvider)
├── Fundamentals  — deterministic (exists: FundamentalsUSProvider;
│                    earnings-date fields MOVE OUT of this card → Events)
├── Behavioral    — sentiment chatter (agentic, NEW)
│                    ─────────── horizontal separator ───────────
│                    positioning numbers (roadmap placeholder, not built now)
├── Events        — existing/past news events (agentic, NEW)
│                    ─────────── horizontal separator ───────────
│                    forward events: upcoming announcement-catalysts (agentic)
│                    + deterministic calendar fields (next earnings date,
│                      moved from fundamentals payload)
└── Analyst       — sell-side ratings / price targets (agentic, NEW)
```

Key principle: **collection is organized by method, reports by subject.**
Deterministic providers stay as they are. ONE agentic run produces the
events/sentiment/analyst findings from one shared source pool; a thin
assembly step deals the results into the three subject cards. Do NOT run
three agents or three collector passes.

## 2. Decisions already made (do not relitigate)

1. **Own agent loop, provider-neutral.** No Claude Agent SDK, no server-side
   web search — must work with any tool-calling model via LiteLLM (user runs
   `LITELLM_MODEL=gemini/gemini-2.5-flash`; China users run DeepSeek/GLM/etc.).
   Reuse `src/agent/llm_adapter.py` (`LLMToolAdapter.call_with_tools`) and the
   tool-schema helpers in `src/agent/tools/registry.py`. Write a small
   dedicated loop for this provider; do NOT pull in the orchestrator/personas.
2. **One agentic run, no subagents.** Shared source pool, one budget, one
   citation numbering.
3. **Generic search tool with a category label, no hardcoded domain lists.**
   Category tags sources and enables the coverage nudge; it never restricts
   domains. Market-specific site knowledge goes in the prompt as hints
   (雪球/股吧 for CN, Reddit/Stocktwits for US, Naver boards for KR, …),
   with an explicit "if you can't find real social discussion, say so"
   instruction. Markets: CN/US/HK/JP/KR/TW (`providers/base.py` Market enum).
4. **Anti-fabrication contract preserved** (from current `sentiment.py`):
   the model never sees or emits URLs — only numbered sources; every report
   item carries a verbatim quote; quotes are verified against the actually
   fetched page text. Verification is **per-item** (drop failing items
   individually), not all-or-nothing. All sections empty after verification
   → `Coverage.UNAVAILABLE`.
5. **Qualitative scope excludes quantitative facts.** No financial metrics,
   no earnings numbers, no price moves (covered by other cards). The
   collector never searches for calendar data available from feeds (earnings
   dates come deterministically from `src/tiered_analysis/earnings.py`).
   Qualitative events = leadership changes, M&A, lawsuits/regulation, product
   launches, partnerships, scandals, labor actions, etc. A qualitative fact
   from an earnings call ("CEO announced pivot to X") is a valid event; the
   revenue beat itself is not.
6. **Budgets (hard, enforced in code, never by trusting the model):**

   | Knob | Value |
   |---|---|
   | Wall clock / run | 3 minutes (use the loop's wall-clock budget pattern; see `_remaining_timeout_seconds` in `src/agent/runner.py`) |
   | Rounds (LLM calls) / run | 8 max; on the final round the tool menu contains ONLY `submit_report` |
   | Searches / run | 8 max; exhausted → tool returns "budget used up, finish with what you have" |
   | Results / search | 5 |
   | Page reads / run | unlimited (bounded by rounds in practice) |
   | Chars / page | 15,000 of **cleaned** article text (newspaper3k via `src.search_service.fetch_url_content`; raise its current 1,500 cap for this path). Keep full fetched text server-side for quote verification. |

7. **Model config:** optional `QUALITATIVE_LLM_MODEL` env var, defaulting to
   `LITELLM_MODEL`. If the model lacks tool-calling support, or the agentic
   run fails/times out, **fall back to the existing single-shot pipeline**
   (keep the current `sentiment.py` path alive as fallback).
8. **Backend dimension id stays `"sentiment"`.** The debate tree, tier
   judges, and citation anchors (`sentiment.citation:N`) reference it. The
   six-card Intel layout is presentation: frontend/API assembly maps
   macro→Econ, technicals→Technicals, fundamentals→Fundamentals, and the
   sentiment dimension's structured payload → Behavioral/Events/Analyst.
9. **`DimensionResult` shape reused, no schema change:** structured sections
   go in `payload`; `narrative` keeps a plain-text rendition (the tier-1/2
   judges consume narrative today and keep working unchanged); `citations`
   stays the flat verified list (existing anchor/link mechanics depend on it).

## 3. Backend implementation

### 3.1 New module: `src/tiered_analysis/providers/qualitative_agent.py`

Pydantic models (the `submit_report` tool schema is generated from these):

```python
class QualitativeItem(BaseModel):
    text: str                          # one bullet, <= 40 words
    source_ids: list[int]              # must reference sources actually read
    quote: str                         # short verbatim quote backing the claim

class QualitativeEvent(QualitativeItem):
    timing: Literal["past", "upcoming"]

class QualitativeReport(BaseModel):
    events: list[QualitativeEvent]
    sentiment: list[QualitativeItem]
    sentiment_label: Literal["bullish", "bearish", "neutral", "mixed"]
    analyst_opinions: list[QualitativeItem]
```

Tools exposed to the model (schemas via `ToolDefinition`/`to_openai_tool`
from `src/agent/tools/registry.py`):

- `search(query: str, category: Literal["events","sentiment","analyst_opinions"])`
  → runs `SearchService` (existing provider chain: Tavily/SerpAPI/Bocha/…);
  `category="events"` may use the news topic mode. Harness assigns each new
  hit a stable source number; the model sees `[n] title — snippet` only.
- `read_source(source_id: int)` → fetch + clean the page (newspaper3k),
  return up to 15,000 chars to the model; store full text in the source
  registry for verification. Failed fetch → honest error string; the
  source's own snippet remains usable but items citing an unread source are
  dropped at verification.
- `submit_report(<QualitativeReport schema>)` → validate with pydantic; on
  validation error, return the error text as the tool result so the model
  retries (max 2 retries).

Loop (small, dedicated — modeled on `run_agent_loop`, not reusing the full
executor): rounds ≤ 8, wall clock ≤ 180 s, search budget 8. Tool calls
executed by our code; source registry owned by our code.

**Coverage nudge:** if `submit_report` arrives with an empty section AND no
search was made in that category, bounce back once: "you never searched
category=X — search or state that nothing was found."

Post-processing (deterministic):
1. Drop items citing unknown/unread source ids.
2. Per-item verbatim quote check against stored page text (case/whitespace
   insensitive, same normalization as current `_verify_citations`).
2.5. Claim-support check (`QUALITATIVE_CLAIM_CHECK`, default true): ONE
   batched LLM call over all surviving (item text, quote) pairs — "does the
   quote support the claim?" — drop unsupported items individually with a
   logged warning. Note: this is probabilistic (a model judging a model);
   it catches sloppy claim/quote mismatches that the deterministic string
   check cannot, but is not a guarantee, and may rarely false-drop. Counts
   as one extra LLM call outside the round budget.
3. Renumber surviving sources 1..N; rewrite `[n]` markers in item texts.
4. All sections empty → `Coverage.UNAVAILABLE`; some empty → keep, with an
   honest note (e.g. "no meaningful social discussion found").
5. Build `DimensionResult(dimension="sentiment", kind=TEXTUAL,
   payload={"qualitative": {events/sentiment/analyst sections, sentiment_label}},
   narrative=<plain-text rendition>, citations=[verified Citation...])`.

### 3.2 Wiring

- `SentimentProvider.collect` (or a new provider registered in its slot in
  `providers/registry.py`) tries the agentic path first, falls back to the
  current single-shot path on: model without tool calling, timeout, loop
  error, or `QUALITATIVE_AGENT_ENABLED=false`.
- LLM usage must flow into the run's existing `LlmUsageTracker`
  (`src/tiered_analysis/llm_support.py` / `integration.py`).
- Earnings-date move: stop writing `next_earnings_date`/`days_until_earnings`
  into the fundamentals payload display path and expose them for the Events
  card instead. Keep the plan-warning logic (`EarningsInfo.is_near`) intact —
  it is independent of which card displays the date.

### 3.3 Config (`.env.example` + docs)

```
# Agentic qualitative collector (tiered page)
# QUALITATIVE_LLM_MODEL=            # defaults to LITELLM_MODEL
# QUALITATIVE_AGENT_ENABLED=true
# QUALITATIVE_MAX_ROUNDS=8
# QUALITATIVE_MAX_SEARCHES=8
# QUALITATIVE_MAX_SECONDS=180
# QUALITATIVE_PAGE_CHAR_LIMIT=15000
# QUALITATIVE_CLAIM_CHECK=true
```

Defaults must make it work with zero new configuration.

## 4. API

`api/v1/endpoints/tiered.py` `_serialize_outcome` already passes `payload`,
`narrative`, `citations` through. Verify the new `payload["qualitative"]`
structure survives serialization; no endpoint changes expected.

## 5. Frontend (`apps/dsa-web/src/components/tiered-alt/`)

1. **Intel section layout:** replace the flat 4-card dimension block in
   `AltDimensions.tsx` with the six-card Intel arrangement (order: Econ,
   Technicals, Fundamentals, Behavioral, Events, Analyst).
2. **New card renderers** (reuse `AltNarrative`'s citation-marker mechanism —
   it does NOT render markdown; `[n]` markers become links only via the
   citations array):
   - **Behavioral:** sentiment_label chip + sentiment bullets; then a
     **horizontal separator**; below it a positioning block that renders
     only a muted "positioning data: coming soon" placeholder (or nothing —
     keep the separator logic ready for when positioning ships).
   - **Events:** past-event bullets; **horizontal separator**; forward
     block = deterministic calendar fields (next earnings date / days-until,
     sourced from the run data) followed by `upcoming`-tagged event bullets.
   - **Analyst:** opinion bullets.
   - Each of the three cards shows its own renumbered Sources sub-list
     (mapping into the dimension's flat citations array so the existing
     `alt-src-*` anchors and debate-tree `sentiment.citation:N` chips keep
     working).
3. **Legacy fallback:** runs whose sentiment dimension has no
   `payload.qualitative` (old history, or agentic-fallback runs) render the
   current single narrative card exactly as today. Old run history must not
   break.
4. Label the qualitative cards' i18n keys; keep dimension id `sentiment`
   internally.

## 6. Testing (offline; `pytest -m "not network"` scoped to touched code)

Backend:
- Loop honors budgets: rounds, searches (tool returns exhaustion message),
  wall clock, final-round tool menu = `submit_report` only.
- `submit_report` validation error → retry message → success.
- Source registry: numbering stable, model-facing text never contains URLs.
- Verification: bad quote → that item dropped, others survive; unread
  source id → item dropped; all-empty → UNAVAILABLE; renumbering rewrites
  `[n]` markers correctly.
- Coverage nudge fires once and only when the category was never searched.
- Fallback triggers on: no tool-calling support, timeout, disabled flag.
- Assembly: earnings fields land in Events data; fundamentals payload no
  longer carries them for display.
- All with fake searcher/fetcher/LLM injected (the current `sentiment.py`
  tests show the injection pattern).

Frontend: `npm run lint && npm run build`; component renders all three new
cards from a fixture payload, legacy fixture renders old card.

## 7. Delivery order

1. Backend collector module + unit tests (pure, offline).
2. Provider wiring + fallback + usage tracking + config + `.env.example`.
3. API serialization verification (likely no code).
4. Frontend Intel layout + three new cards + legacy fallback; lint/build.
5. Docs: this file updated to "implemented"; note behavior change in the
   tiered page docs if any exist.

Each step: run the scoped offline tests before moving on. Commit per step
with English conventional-commit messages, no Co-Authored-By (repo rule).

## 8. Explicit non-goals / roadmap (do not build now)

- Positioning provider (short interest, ownership, flows) — future 4th
  deterministic report feeding the Behavioral card below its separator.
- CN/HK/JP/KR/TW earnings calendars (deterministic, same pattern as
  `earnings.py`).
- Dedicated social APIs (Reddit/Stocktwits) as extra tools.
- Cheap-model page distiller for pages > 15k chars (Claude Code WebFetch
  pattern): localized swap inside `read_source` — distill oversized pages
  with a cheap model that must extract verbatim quotes so the existing
  quote-verification chain keeps working. Not built now: news articles fit
  in 15k, and it adds a second probabilistic layer + a second model config.
- Provider-native server-side search backends.
- Any change to the legacy (non-tiered) report pipeline.
