# Tiered Analysis — Design & Roadmap

> Status: **draft v0** — design of record.
> This work only adds an independent module `src/tiered_analysis/`; it does **not** modify
> the existing single-shot analysis main path
> (`src/analyzer.py` / `src/stock_analyzer.py` / `src/core/pipeline.py`).
>
> This document is the complete record of our discussion conclusions. It is written in
> English, with key market terms kept in Chinese where they are domain-specific.
>
> Companion documents:
> - `docs/tiered-analysis-formulas.md` — every deterministic formula (indicators,
>   price levels, adjustment guardrails, position sizing) with plain-English
>   explanations and the constants table.
> - `docs/tiered-analysis-v2-plan.md` — the v2 implementation plan (slices + status).

---

## 0. Background & goal

On top of DSA's existing **product shell** (web frontend, WeChat/notification integrations,
watchlist tracking, scheduling, multi-market routing via `data_provider/base.py:_market_tag`),
incrementally build a **tiered** per-stock analysis product:

- For a given ticker, the user first gets **Tier 1** (four-dimension data collection + a
  directional call).
- They can deepen on demand: **Tier 2** (bull/bear debate), **Tier 3** (risk stress test),
  **Tier 4** (portfolio level).
- Each tier outputs a **report + a decision**; higher tiers cost more and take longer, but
  produce better-grounded decisions.

**Why DSA as the base**: Tier 1 is essentially what DSA already does; the frontend,
notifications, watchlist, scheduling, and multi-market routing already exist. Starting a new
repo from scratch would mean rebuilding the entire shell. TA / VT are US-market-first agent
frameworks with no reusable product shell.

**Positioning of the three reference repos** (all conclusions below have been verified
against the code):

- **DSA**: single-shot pipeline — deterministic technical analysis → one LLM call → a
  guardrail layer that rewrites the decision. Deepest data for A-shares (China); US/HK/JP/KR
  go through a thinner yfinance path. No position sizing; its portfolio awareness is a
  "phantom" (see §3.3).
- **TA (TradingAgents)**: multi-agent debate (4 analysts → bull/bear → research manager →
  trader → three-way risk debate → portfolio manager). All-LLM prose output. US/global
  markets, no A-shares. No enforced position sizing, no portfolio awareness.
- **VT (Vibe-Trading)**: conversational ReAct agent + deterministic backtest engine + 29
  YAML swarm presets + an MCP server. The only place that actually computes share counts is
  the backtest engine; its recommendations are prose with no quantities; decisions are made
  without awareness of real holdings.

The shared gap across all three = **real position sizing + portfolio awareness**. That is
exactly this product's differentiation space.

---

## 1. First principle: the numeric-vs-textual rule

The core classification rule for the entire data layer:

| Type | How it's produced | Reproducible | Backtestable | Can feed position sizing |
| --- | --- | --- | --- | --- |
| **NUMERIC** | Deterministic code computed from data sources | ✅ | ✅ | ✅ |
| **TEXTUAL** | LLM + web search synthesis, **must carry verifiable citations** | ❌ | ❌ | ❌ |

**The rule, stated plainly**:

- Any number a user might **trade on** (prices, indicators, ratios, economic series, market
  breadth) → must be produced by deterministic code. Reproducible, cheap, fast,
  backtestable, and safe to feed into position sizing.
- Any **qualitative judgment** (sentiment, narrative) → goes to LLM + search + citations.
  Because it is not reproducible, it **never enters the quantitative sizing path**.

**Two anti-patterns that must be avoided**:

1. **Hard-coding scrapers** for qualitative sentiment (fragile, high-maintenance, one per
   platform per language).
2. Using **LLM search to "guess" numeric values** (e.g. market breadth or the count of
   limit-up stocks 涨停家数 — no article publishes "2,347 stocks advanced today"; search
   cannot reliably recover it and will at best grab a sentence like "the market was mixed",
   or simply fabricate a number).

**Analogy with Claude Code skills**: a skill is prompt + LLM improvisation, but it still
calls **deterministic tools** (bash, file I/O) to obtain facts. The LLM handles
**orchestration and narration**; deterministic tools produce **every number**. This design
adopts the same division of labor.

---

## 2. The four dimensions

For each dimension: its type, data sources per market, implementation approach, and coverage
notes.

### 2.1 Technicals — **NUMERIC**, lowest regional coupling

- **Type**: NUMERIC. Indicators are pure math over normalized OHLCV series, independent of
  the exchange.
- **Data source**: daily OHLCV for any market. v1 uses Yahoo Finance (global suffix coverage
  `.KS/.KQ/.HK/.T/.SS/.SZ`), but yfinance is unofficial scraping (rate-limited / brittle /
  no SLA), so in production it should sit behind DSA's existing multi-source
  `data_provider`, not be a direct dependency.
- **Implementation**: a deterministic pure-Python indicator core (SMA / EMA / Wilder-RSI /
  MACD / **ATR** / BIAS + a 0–100 composite score), decoupled from fetching.
  **Implemented**: `src/tiered_analysis/providers/technicals.py`.
- **Notes**:
  - **ATR is a new addition** — the existing `stock_analyzer.py` lacks ATR (verified: zero
    hits across `src/`), and ATR is the standard input for later volatility-based stops and
    risk-based sizing, so it must be added.
  - **Chip distribution (筹码分布)** is an A-share retail-culture concept; keep it as an
    optional CN overlay, not shown for US stocks.
- **Regional conclusion**: **implement once, works globally (~90%)**. Extending this
  dimension to US stocks is essentially free.

### 2.2 Fundamentals — **NUMERIC**, high regional coupling (data sources)

- **Type**: NUMERIC (structured numbers: valuation / growth / profitability / balance-sheet
  health, etc.).
- **Data sources (per market — no single vendor covers everything)**:
  - US: **SEC EDGAR XBRL** (authoritative raw statements; VT already demonstrates this in
    `financial_statements_tool.py:316`) + Yahoo summary (valuation ratios, earnings dates).
  - CN (A-shares): AkShare / Eastmoney 东方财富 (valuation, growth, institutional holdings,
    money flow, 龙虎榜 dragon-tiger list, concept boards) — DSA already has this and it is
    the deepest.
  - HK: Eastmoney F10 / Yahoo.
  - KR: **gap** — needs DART (filings) / Naver / paid sources. yfinance is very thin for KR
    fundamentals.
- **Implementation**: define a **unified normalized schema** (valuation / growth /
  profitability / balance-sheet health), with one adapter per market filling it in. DSA
  already has this seam (`AkshareFundamentalAdapter` / `YfinanceFundamentalAdapter`); reuse
  and extend it.
- **Important clarification (verified)**: Yahoo provides **summary numbers only**, not
  "documents"; and its non-US coverage is uneven (HK ownership often returns `ok:true` with
  empty sections — a silent blank, which is worse than an error). Yahoo can serve as the US
  v1 fallback; depth requires native sources.
- **Regional conclusion**: **data sources must be customized per market**, but the schema is
  unified. This is one of the main workloads for the US expansion.

### 2.3 Macro — **split in two**

Macro is really two different things:

**(a) Economic indicators — NUMERIC, low regional coupling**

- **Type**: NUMERIC (time series: rates / CPI / GDP / unemployment / PMI, etc.).
- **Data sources**: FRED (which includes many international series) / OECD / World Bank /
  Trading Economics can supply a "many countries from one place" core set; national central
  banks (BOK ECOS for KR, PBoC/NBS for CN, BOJ for JP) as native enhancements. TA already
  demonstrates FRED (`dataflows/fred.py`) + Polymarket.
- **Implementation notes**: economic data is **low-frequency** (monthly/quarterly) and
  **shared by every ticker in the same market** — **cache once per region per day; never
  fetch per ticker**. Extremely cheap. A US-centric shared base (US rates, DXY, oil, VIX) is
  valid background context for every market.
- **Regional conclusion**: **a one-time shared feed covers ~70%**; local central-bank data
  is an enhancement.

**(b) Market internals — NUMERIC, high regional coupling (per exchange)**

- **Type**: NUMERIC (breadth, limit-up/limit-down counts 涨跌停家数, sector/concept
  rotation, turnover).
- **Inherently per-exchange**: A-share breadth is meaningless for US stocks; the price-limit
  (涨跌停) concept does not exist in the US and is ±30% in Korea. Must be computed per
  exchange over that exchange's full universe.
- **DSA today (verified in `market_analyzer.py`)**: only A-shares produce **structured**
  internals (`limit_up_count`/`top_concepts`/`top_sectors`, `:96-105`); US/HK/JP/KR go
  through **a different branch** (`:197`) that only does currency-formatted LLM prose
  review, with **no** structured breadth/limit data.
- **⚠️ Cannot be implemented with LLM search**: market internals are **full-market numeric
  aggregates**; search can't find them and will fabricate. Must come from a dataset feed
  (AkShare provides it for CN).
- **Regional conclusion**: **fully per-exchange**; some concepts don't port at all. Can be
  **deferred** in v1.

### 2.4 Positioning — **NUMERIC**, high regional coupling (disclosure regimes)

> **History (2026-07-24)**: this slot originally held the TEXTUAL **news-sentiment**
> dimension (LLM + search + verbatim-quote citation verification, provider
> `providers/sentiment.py`, dimension id `"sentiment"`). It was retired and replaced by
> this fully deterministic positioning dimension; the citation-ref (`citation:N`) plumbing
> was removed from the debate/plan-review layers with it. Old stored runs still carry
> sentiment cards and citation links — the frontend keeps rendering them.

- **Type**: **NUMERIC**. Who holds the stock and who can be forced to transact — the four
  questions a thesis defense always meets: who is on the other side, how crowded the trade
  is, who can be squeezed, and what informed parties are doing. Every number is a published
  disclosure; no LLM anywhere (`providers/positioning.py`, dimension id `"positioning"`).
- **Four blocks (US, all via yfinance)**:
  - **Short interest** — short % of float, days to cover, shares short, change vs the prior
    report. FINRA settlement data, published twice a month with ~2 weeks' lag; the payload
    carries `as_of` so the staleness is always visible.
  - **Ownership** — institutional % and insider % (13F, quarterly, up to 45 days late),
    top-10 institutional concentration, float vs shares outstanding.
  - **Insider activity (6m)** — open-market Form 4 buys/sells counts and net notional;
    awards/exercises/gifts excluded (only trades made with the insiders' own money count).
  - **Options** — put/call open-interest and volume ratios plus total OI over the nearest
    expirations (≤4 fetched); the freshest block, daily.
- **Degradation**: each block fails independently into `warnings` (partial coverage);
  everything failing → `unavailable`. An ok-but-empty summary is surfaced, never blanked.
- **Per-field notes (2026-08-05, all NUMERIC providers)**: alongside `warnings`, every
  `DimensionResult` may carry `field_notes` — the same note strings keyed by the payload
  field (`"group.key"`) each is about. The alt report page shows each note behind a small
  exclamation mark beside its own field (blank fields render a plain `n/a` next to it);
  only notes attached to no field — and all notes on old stored runs — fall back to the
  card-level notes button. Unavailable dimensions keep the card-level red X.
- **Regional conclusion**: **per-disclosure-regime**. US ships first. A-shares have a
  *better* local staple (per-stock margin-trading balances 融资融券, daily via AkShare, plus
  quarterly shareholder counts 股东户数); HK has SFC weekly short positions and HKEX daily
  short-sell turnover. Those are separate provider designs, deferred.

### 2.5 Summary table

| Dimension | Type | Regional customization | v1 data source | LLM-search viable? |
| --- | --- | --- | --- | --- |
| Technicals | NUMERIC | Very low | Yahoo OHLCV (behind data_provider) | ❌ not needed |
| Fundamentals | NUMERIC | High (sources) | US=EDGAR/Yahoo; CN=AkShare | ❌ needs data sources |
| Macro-econ | NUMERIC | Low | FRED/OECD (cached daily per region) | ❌ needs data sources |
| Macro-internals | NUMERIC | High (exchange) | AkShare (CN); others deferred | ❌ never use search |
| Positioning | NUMERIC | High (disclosure) | US=FINRA/13F/Form 4/options via yfinance | ❌ never use search |

---

## 3. Decision layer

### 3.1 Direction vs sizing

- **v1 outputs direction only** (buy/hold/sell + the "sniper point" levels: entry /
  stop-loss / target price), **no shares/$ quantities**.
- **Rationale**: the eval/backtest burden comes from **false precision**. "Buy, entry ≈1800,
  stop 1750" is a qualitative judgment DSA already produces and users already accept; "**buy
  137 shares**" is a quantitative claim — the moment you print that number you owe a
  justification (a backtest). Therefore **sizing and backtesting are coupled and deferred
  together**.
- **Two cheap things v1 still does** (paving the way):
  1. **Reserve sizing slots in the output schema** (`capital`/`risk_fraction`/`shares`),
     even though v1 leaves them empty.
  2. **From day one, log every recommendation + the subsequent price path** — this is the
     raw material for future backtests/evals, and reconstructing it after the fact is
     extremely painful.

### 3.2 Sizing is deterministic — not the LLM's job

The classic risk-based formula (implemented in v2+):

```
shares = (account_capital × risk_fraction) / (entry_price − stop_loss)
```

- DSA's "sniper points" already produce `entry` and `stop_loss`
  (`report_schema.py:92-98`); we only need two more inputs: **user capital** and
  **per-trade risk %** (e.g. 1%). Zero LLM involvement.
- **Where it lives**: inside DSA's existing **guardrail layer**
  (`phase_decision_guardrail.py:314` already rewrites advice after the decision), not in the
  prompt. The LLM sets direction, code sets quantity — exactly VT's division of labor.
- **Requires ATR**: volatility-adaptive stops use ATR (added in this layer), more robust
  than fixed sniper points.

### 3.3 Portfolio awareness (Tier 4)

- All three reference repos **pretend** to have portfolio awareness (DSA's
  `portfolio_context` never reaches the prompt — verified phantom: the context-pack prompt
  renderer intentionally drops item values; VT's committee prompt asks for the "existing
  book" but has no tool to fetch holdings). This is **net-new** space.
- Tier 4 is harder because single-ticker sizing ignores **correlation and total exposure**
  (5 semiconductor tickers are not 5 positions, they are 1 bet). Needs: per-sector /
  per-ticker exposure caps, correlation-aware sizing, optional risk-parity / mean-variance
  (VT already has borrowable machinery in `engines/base.py:139-157`).
- **Simplified start**: portfolio = holdings + cash. First, actually feed **real holdings
  into the Tier 2/3 prompts** (the thing DSA pretends to do but doesn't) + hard exposure
  caps. That alone beats all three reference repos.

---

## 4. Tier structure

| Tier | Input | Processing | Output | Reference implementation |
| --- | --- | --- | --- | --- |
| **Tier 1** | ticker | four-dimension collection → one LLM synthesis | report + **direction** (no quantity) | ≈ current DSA (`core/pipeline.py:696`) |
| **Tier 2** | Tier 1 result | bull/bear debate → research-manager verdict | debate report + updated direction + **first position size** | TA `graph/setup.py:122-138` |
| **Tier 3** | Tier 2 result | Conservative/Aggressive/Neutral three-way | risk report + stress-tested position & size | TA `graph/setup.py:140-165` |
| **Tier 4** | Tier 2/3 + real portfolio | correlation/exposure constraints | portfolio-level advice (sizes adjusted to the book) | net-new (none of the three repos have it) |

- By default the watchlist runs **Tier 1 only** daily; users can manually trigger, or
  toggle automatic, higher tiers.
- Tiers are connected as a **deterministic graph** (borrowing VT's YAML DAG + topological
  scheduling, `runtime.py:256`: deterministic orchestration, LLM improvisation inside
  nodes). A node GUI (editable prompts/edges) is **deferred** (see §7).

---

## 5. Architecture conventions

- **Provider interface** (implemented in `src/tiered_analysis/providers/base.py`):
  - `DimensionProvider`: one implementation per (dimension × market family), declaring
    `NUMERIC` / `TEXTUAL`.
  - `DimensionResult`: unified return body. NUMERIC uses `payload`; TEXTUAL uses
    `narrative` + `citations`.
  - `Coverage`: `full` / `partial` / **`unavailable`** — **explicit degradation**, no silent
    blanks. This corrects DSA's current behavior (auxiliary data silently degrades to
    `None`/`[]`, `data_provider/base.py:401-445`).
  - `is_actionable`: true only when NUMERIC with a payload — numeric consumers such as
    sizing gate on it, so thin data can never silently flow into a share count.
- **Failure-handling principle**: borrow VT's fail-loud (errors bubble up to the
  orchestration layer as structured results, `agent/src/agent/tools.py:77-84`) rather than
  DSA's silent None/[]. For a product users trade on, a "data incomplete" badge is more
  trustworthy than a fake-complete report.
- **Orchestration vs execution**: the LLM decides **what to run / how to narrate**;
  deterministic engines produce **every number** (backtests, indicators, loaders).

---

## 6. Backtesting (v3)

- **Definition**: replay a set of **decision rules** over historical prices to estimate
  performance (returns / max drawdown / Sharpe) before risking real money. VT's engine steps
  bar by bar (`engines/base.py:503-548`), fills at next-bar open, tracks cash/commissions,
  and outputs an equity curve + Monte Carlo permutation / bootstrap Sharpe CIs /
  walk-forward validation (`validation.py`).
- **Its role in this product — backtest not just "strategies" but "our tiered decision
  policy as the strategy"**: "If I had run my watchlist for the past 2 years on Tier-2
  signals + our sizing rule, what would the returns/drawdown be?" This **validates sizing**
  (so users can trust the share counts) and makes the tiers measurable and comparable.
- **Implementation advice**: do **not** port VT's heavy "LLM writes sandboxed code" engine;
  first build a small **deterministic replayer** of our own tier outputs. It comes **after**
  sizing + portfolio, because there must be something to backtest first.

---

## 7. Chatbot / MCP and node GUI (deferred)

- **Chatbot controlling the site**: first expose site capabilities as **internal service
  functions**; MCP is then a one-day adapter layer (VT demonstrates this:
  `mcp_server.py:66`, FastMCP + 40+ `@mcp.tool`).
  - Use MCP when: the chatbot is a separate runtime, or third-party clients (Claude Desktop)
    should also be able to drive it.
  - Use direct function-calling when: the chatbot lives in the same backend — saves a
    network hop.
  - **Write operations must be confirmation-gated** (triggering a tier, changing holdings) —
    following VT's mandate + kill-switch pattern.
- **Node/edge GUI editor** (deferred, expensive): requires first **externalizing the
  workflow as data** (adopt VT's YAML DAG + topological scheduling model); DSA today is a
  hard-coded Python pipeline. Risks: user-editable prompts = broken eval baselines + a
  prompt-injection surface. Ship as an "expert mode" with versioning and "restore defaults";
  the official tiers remain the blessed path.

---

## 8. Roadmap

> Principle: don't build everything at once; each increment is self-contained, verifiable,
> and zero/low-risk to the DSA core.

### v1 — Foundation + Tier 1 (direction, no quantity)

> **Status: DONE (2026-07-10).** All items below shipped; see §9 for the as-built summary.

- Provider interface + the numeric/textual rule encoded + the
  **technicals provider** (with ATR) + market routing + offline tests.
- Tier pipeline skeleton (Tier 1/2/3 stages + shared state; Tier 1 delegates to the
  existing DSA analysis).
- Wire up all four dimension providers (technicals numeric is ready; fundamentals
  US=EDGAR/Yahoo; macro-econ=FRED cached per region; sentiment=LLM+search+citations as the
  generic fallback).
- **Citations** wired into all four dimensions; `coverage` badges shown explicitly in
  reports/UI.
- **Recommendation log** (record advice + subsequent price path).
- Output schema **reserves sizing slots** (left empty).
- Markets: get **US** working across all four dimensions first (technicals are free,
  macro-econ FRED is cheap, fundamentals via EDGAR, sentiment via search fallback);
  A-shares keep DSA's existing depth; **KR** becomes a separate data-source milestone.

### v2 — Quantities + Tier 2/3

- **Deterministic position sizing** (capital + risk% + entry/stop → shares), placed in the
  guardrail layer, off by default, opt-in.
- Tier 2 (bull/bear debate) + Tier 3 (three-way risk) plug into the same sizing engine;
  quantities update as depth increases.
- Volatility stops via ATR.

### v3 — Backtesting (validates sizing)

- Deterministic replay of our own tiers + sizing policy; returns/drawdown/Sharpe + basic
  statistical validation.
- This is the trust pillar for "daring to print share counts", and takes **priority over**
  fancy GUI/chatbot work.

### v4 — Portfolio layer (Tier 4)

- Real holdings/cash into Tier 2/3 prompts + hard exposure caps; correlation awareness;
  optional risk-parity / mean-variance.

### v5+ — Chatbot/MCP, then node/edge GUI

- Service functions → MCP adapter (write operations confirmation-gated).
- Externalize the workflow as a YAML DAG → node/edge GUI (expert mode + versioning).
- Native per-market **retail sentiment** sources (Xueqiu 雪球 / Guba 股吧 / Naver), as the
  real differentiation.

---

## 9. Implemented so far — v1 complete (2026-07-10)

> **History note (2026-07-06/07)**: an earlier version of this section described code that
> was never committed. The work was re-implemented from scratch starting 2026-07-07 and
> completed through 2026-07-10; the list below reflects the actual code.

v1 shipped in full on branch `claude/trading-repos-verification-analysis-pe4qts`
(153 offline tests, `pytest -m "not network"`; live-verified end to end on AAPL):

- **Provider layer** (`src/tiered_analysis/providers/`): base contracts
  (`Market` / `SourceKind` NUMERIC|TEXTUAL / `Coverage` full|partial|unavailable /
  `Citation` / `DimensionResult` / `is_actionable`); technicals — pure-Python
  deterministic SMA/EMA/Wilder-RSI/MACD/**ATR**/BIAS + 0–100 score; fundamentals —
  US via SEC EDGAR filings + Yahoo valuation; macro — FRED, cached per region;
  sentiment — search + LLM under the anti-fabrication citation contract (verbatim-quote
  verification, one deduped reference per source, inline `[n]` markers renumbered to the
  deduped list and stripped when their citation is dropped) — **retired 2026-07-24,
  replaced by the deterministic positioning provider (§2.4)**; registry with market
  routing delegating to `data_provider/base.py:_market_tag`.
- **Tier 1 synthesis + integration** (`src/tiered_analysis/integration.py`,
  `scripts/run_tiered_analysis.py`): four-dimension collection → one LLM synthesis →
  direction + price levels. Sizing slots reserved and left empty by design (v2).
- **Recommendation log**: thin adapter `src/tiered_analysis/signal_log.py` into DSA's
  existing `decision_signals` ledger (`source_agent="tiered_analysis"`; coverage maps to
  the data-quality tag so thin-data calls can be discounted when scored later).
- **Web surface** (`apps/dsa-web`): `/tiered` page — ticker input, background run via
  `POST /api/v1/tiered/analyze`, persistent run history (`tiered_runs` table +
  `/api/v1/tiered/runs` endpoints), dimension cards with coverage badges, price-level
  tiles, inline-citation hyperlinks with a deduped numbered source list, warnings shown
  as "Data notes", and plain-language tap-friendly popups (en/zh) for every metric
  (`i18n/metricLabels.ts`) and every verdict-card term (`tiered.help.*` keys).

## 10. Boundaries & governance

- This package does **not import or modify** the `analyzer.py` decision path; it ships as an
  independent capability first.
- Technicals conceptually overlap with `stock_analyzer.py` and **should converge long-term**
  (the latter is A-share-leaning and lacks ATR); until convergence the two coexist, but they
  must **not** compute duplicates on the decision chain.
- Per `AGENTS.md` §0 (personal-fork overrides, 2026-07-07): committing is allowed without
  asking; push only to the origin fork and only when asked — **never** to the upstream
  ZhuLinsen repo; CHANGELOG maintenance is disabled; `.env.example` must still be updated
  when adding config.
