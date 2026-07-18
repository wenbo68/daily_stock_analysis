# Tiered analysis — file map for frontend tweaking

A guide to every folder and file behind the **/tiered** page, written for editing the
look and layout yourself. Terms are defined as they appear.

## The 30-second picture

```
backend (Python)                          frontend (React, what you'll edit)
─────────────────                         ──────────────────────────────────
src/tiered_analysis/  ──produces──▶  JSON over the API  ──▶  src/api/tiered.ts
api/v1/endpoints/tiered.py                                    │ (fetches + describes the JSON)
                                                              ▼
                                                  src/pages/TieredAnalysisPage.tsx
                                                              │ (page skeleton)
                                                              ▼
                                                  src/components/tiered/*  (the cards)
                                                              │ all text comes from
                                                              ▼
                                                  src/i18n/uiText.ts  (every sentence, zh + en)
```

Everything frontend lives under **`apps/dsa-web/src/`**. All paths below are relative
to that folder unless stated otherwise.

---

## 1. The page itself

### `pages/TieredAnalysisPage.tsx`
The whole /tiered screen, top to bottom:

- **the run form** — stock-code box, depth picker, capital & risk inputs, Run button
  (it also remembers capital/risk in the browser's localStorage — a small key-value
  store the browser keeps between visits);
- **the run-history list** (left column) and the polling that refreshes it while a
  run is going;
- **`ResultView`** — the function inside this file that decides the *order* of cards
  in the result: Final verdict → Tier 1 → Debate → Risk → Suggested order size →
  the four dimension cards. **Reordering sections happens here.**
- **`DimensionCard` and `PayloadTable`** — also defined inside this file. They draw
  the four data cards (technicals / fundamentals / macro / sentiment) and their
  metric tables. Each table row carries an invisible anchor id so "evidence" links
  elsewhere on the page can scroll to it.

The route (the URL → page mapping) is registered in `App.tsx` line ~87:
`<Route path="/tiered" ...>`.

## 2. The cards — `components/tiered/`

One file per visual block. Each is a React *component*: a function that takes data
in (called *props*) and returns the HTML for one piece of screen.

| File | What it draws |
|---|---|
| `FinalVerdictCard.tsx` | Top card on deep runs: symbol, the big final direction badge, "issued by tier N", and the tier 1 → 2 → 3 "how the verdict evolved" trail. |
| `DepthSelector.tsx` | The 3-way depth picker on the run form (Standard / + Debate / + Risk stress test). |
| `LevelTiles.tsx` | The four price-level tiles (entry / backup entry / stop-loss / target), each with a formula-base number and an AI-adjusted number, plus the two pop-ups: the formula modal (formula, numbers plugged in, clickable inputs) and the AI-adjustment modal (reason + evidence links). The biggest file here. |
| `DebateCard.tsx` | Tier 2: judge's ruling, confidence, reasons for/against with evidence links, and the fold-away bull/bear transcript. |
| `RiskCard.tsx` | Tier 3: final stance, the size-multiplier chip (1 / ½ / 0 with plain-words label), stop-loss advice, key risks, the three reviewers' takes. |
| `SizingCard.tsx` | "Suggested order size (computed result)": the big share-count headline (number, 0, or — with the refusal reason), the stat tiles, and the input/output explainer subtitle. |
| `TieredModal.tsx` | The generic pop-up dialog the level tiles use (dark backdrop, Escape/click-outside to close). Restyle all modals here at once. |
| `terms.tsx` | Small reusable pieces: `HelpTerm` (dotted-underline word with a definition pop-up), `MetricTerm` (metric name with its definition), `NarrativeWithCitations` (turns [1] [2] markers into links), `EvidenceRef` (an evidence link that either opens a news source or scrolls to a metric row). |
| `termHelpers.ts` | Non-visual helpers: which badge color each direction/coverage gets (`DIRECTION_BADGE`, `COVERAGE_BADGE`), number formatting, and the scroll-and-flash-highlight logic for evidence jumps. |
| `__tests__/` | Automated checks for the components above. If you change layout/wording enough to break one, that's expected — update the test to match the new intent. |

> Why two files for "terms"? A repo lint rule says a file may export *either*
> components *or* plain functions, not both. `terms.tsx` holds the components,
> `termHelpers.ts` the functions.

## 2b. The alternate skin — `/tiered-alt`

A second, parallel version of the page in a flat dark style (modeled on showplayer.net)
so the two looks can be compared side by side. Same API, same data, same wording file.

| File | What it is |
|---|---|
| `pages/TieredAltPage.tsx` | The alt page: two gray-900 section cards with UPPERCASE titles sitting above them. Section 1 is the new-run form, section 2 the run history. The page owns all data state (runs list + 5s polling while anything runs, per-run report cache, start/expand handlers, the tier of runs it just started, and the server's saved capital/risk defaults for the on-entry pills). |
| `components/tiered-alt/AltRunForm.tsx` | Section 1: write-only fields (ticker / tier / capital / risk) whose choices land as removable `Label: value` pills below, plus the indigo Start pill. Tier and risk show default pills on entry; picking a ticker auto-fills capital (in the ticker market's currency — see `altCurrency.ts`), and removing the ticker removes capital with it. Start requires all four fields and explains in a popup otherwise; setting capital before a ticker also gets a popup. Picking an already-picked dropdown option clears it, same as clicking its pill. |
| `components/tiered-alt/AltRunHistory.tsx` | Section 2: filters (ticker / capital Min–Max / risk Min–Max / tier / verdict / shares Min–Max / date Min–Max) that apply the moment they're entered and show as pills; ticker, tier and verdict are multi-pick dropdowns (ticker lists every ticker seen in history). Then the run rows (10 per page) sharing the filter grid's exact column template, so every fact sits directly under its filter: ticker, capital, risk, tier, verdict (plain colored text, not a pill), shares, date `yyyy/mm/dd, hh:mm`. Rows expand inline into the full report, paged by the showplayer-style numbered page buttons. The pill row keeps its height when empty (no `No filters` placeholder, no layout shift). |
| `components/tiered-alt/altCurrency.ts` | Ticker → trading-currency helper (6-digit = CNY, hk/5-digit = HKD, .T/.KS/.TW suffixes, letters = USD) — a simplified mirror of the backend's market rules for the capital field's label and pill. |
| `components/tiered-alt/AltFields.tsx` | The write-only form controls: `AltSelect` (dropdown/suggestions, single or multi-pick), `AltCommitInput`/`AltTextField`/`AltPairField` (Enter-to-commit boxes), `AltPill`/`AltPillRow`, `AltPageSelector` (first/prev/numbers/next/last square buttons — always rendered, a single page shows an active "1"). |
| `components/tiered-alt/altStyles.ts` | The alt design tokens: badge recipes (`bg-*-500/20 text-*-300 ring-*-500/30`), the numbered pill palette handed out per field in order (`ALT_COLOR`), status-dot colors, link color (`ALT_LINK` carries `!` because an unlayered `a { color: inherit }` in index.css outranks Tailwind's layered utilities on anchor tags). |
| `components/tiered-alt/AltUi.tsx` | Alt primitives: card, modal (`panelClassName` lets formula modals fit their widest line), `FVar` (italic formula variable — variables are never underscored or parenthesized), data-notes mark, narrative-with-citations, evidence links (news references render as `sentiment.citation:N`). |
| `components/tiered-alt/AltResult.tsx` | The result skeleton — identical at every depth, each block titled in caps above its card: FOUR-DIMENSION REPORTS → TIER 1: PRELIMINARY STANCE → TIER 2: POSITION DEBATE → TIER 3: RISK DEBATE → SHARES COMPUTATION. Tier cards open with one row of `Label: value` facts — quiet gray label, brighter semibold value; the verdict value carries the same buy/hold/sell tint as history rows. Tier 1 shows only the verdict (its stored score is the analyzer's bullishness composite, not a judge confidence, so it is not shown as Score). Tier 2's `Score: 7/10` is the scored debate's computed final position score (rounded whole number; old judged runs fall back to judge confidence × 10); tier 3's is the risk judge's confidence; tier 3 inserts `Size: 0.5x` and `Stop loss: keep`/`Stop loss: 285.60` before the score. The tier-2 card renders six generations: tree (v5-v9, `format: 5|…|9`) runs show `Score: 6.50/10` (the 2-decimal final) and the debate tree (see AltDebateTree) with no scoring foldable and no bull/bear columns — the arithmetic lives in the tree's own Scores block; threaded (v4) runs show six transcript turns labeled by kind (argument / attack / response) with the `position score N/10` on response turns; scored (v3) runs keep round-numbered turns; v3/v4 show the judge's corrected Bull case / Bear case summaries and a `Scoring and calculation` foldable below the transcript (see AltDebateScoring); judged (v2) stored runs keep the reasons-for/against columns and What-would-change-the-verdict. No verdict pills anywhere. The shares card is a bare three-line formula fully expanded to numbers that already exist — *capital* × *risk* × *multiplier* / (*entry* − *stop loss*), variables italic, parentheses only for real math grouping — each number linking to its source: run-row capital/risk cells, the tier-3 multiplier, the levels table's entry/stop cells (or the tier-3 tightened stop when that's what sizing used). A logged signal renders as one link, `Recorded to AI signals #N`, deep-linking to `/decision-signals?signal=N`. |
| `components/tiered-alt/AltDebateScoring.tsx` | The scored debate's `Scoring and calculation` foldable. v4 runs: per side the `position score: 8/10` line, then one line per validity grade with the judge's comment — `N/A` at 5/5, otherwise the offending sentence quoted verbatim plus why it is wrong. v3 runs keep the compact grade facts line plus the judge's notes. Then the fixed formulas in the shared three-line words/plugged/result shape — weight = (citation + knowledge + logic) / 15, final score = validity-weighted average of the two position scores, and the verdict block (rounds-to line, `0–3 sell · 4–6 hold · 7–10 buy`, mapped verdict). Every plugged number appears in the lines above it. |
| `components/tiered-alt/AltDebateTree.tsx` | The debate tree, two renderers. v8/v9 (`VoteTree`) is the evidence vote as ONE page — no steps: per-dimension groups headed `Technicals: ↑3, ↓4` (counting only surviving bullets, so the header numbers sum to the score's fraction), each bullet a two-column grid row (hanging indent on wrap) of id + ↑/↓ arrow + its history as clickable marks — ✓✓ listed independently by both analysts, one ✓/✗ per check/deciding vote, a code ✗ on citation-struck bullets — each mark opening an AltModal with the reasoning (vote reasons render with the same inline value links and trailing [N] source links as claims). No pills, no colors on arrows/marks: crossed out = not counted (struck or voted out). The Scores block is just the flat formula `10 × bullish / total` plugged in (hidden for stored format-8 runs whose score was a per-dimension mean) and the verdict bands. v5/v6/v7 stored runs keep the `RoleDebateTree` renderer: the 4-step selector, defender/attacker/judge threads, chips/weight (v5), amber value-check lines + badges (v6), single-axis threads (v7). Voided runs render the partial tree without the Scores block. |
| `components/tiered-alt/AltLevels.tsx` | The tier-1 levels as a Computed/Adjusted table (columns: ideal entry, backup entry, stop loss, target; untouched levels say `keep`). Clicking a computed number opens a modal titled `<level>: formula` — formula in words (variables italic, human names like `ideal entry`), plugged-in numbers (each linking to a technicals row or another computed cell), result; all three lines share one font/size/spacing and never wrap (the modal widens to fit). The backup entry's stored prose formula renders as `max(sma 60, swing low 20)` plus a one-line condition ("only values below the ideal entry N are kept", N linking to the computed entry cell), with only qualifying candidates plugged in. Clicking an adjusted number opens `<level>: adjustment` — the AI's reason and references. Old runs without the audit trail fall back to a single row of stored values. |
| `components/tiered-alt/AltDimensions.tsx` | The four data cards, alt-styled. Each ends in a single `Sources` list — non-link sources first, links after (shown as their URL, not their headline), every entry keeping the `[n]` number its inline marks refer to. |
| `components/tiered-alt/altWarningText.ts` | Rewrites the backend's technical "data notes" into plain-English sentences (the raw message stays in a hover popup). Add a new pattern here when a new note shape shows up untranslated. |

Once one version wins, delete the loser (page + its components folder + its nav entry).

## 3. Where the words live

### `i18n/uiText.ts`
**Every sentence on the page, in Chinese and English.** Hover-help texts (`tiered.help.*`) follow a fixed style: concise, minimalist, and one sentence per line — sentences are separated by `\n` and the popup renders with `whitespace-pre-line`. Two big lists keyed by names
like `tiered.sizing.title`; the `zh` block is around line 800, the matching `en`
block around line 1750. To reword anything: search for the current text, change it
in **both** blocks. Adding a new key: add it to `zh` first (that block defines the
allowed key names), then `en`.

### `i18n/metricLabels.ts`
The plain-language dictionary behind metric pop-ups — what "SMA 20", "ATR 14",
"PE (TTM)" etc. mean. Feeds `MetricTerm`.

## 4. Shared building blocks (used by many pages — restyle with care)

- **`components/common/`** — the app-wide kit: `Card`, `Badge` (the colored pills),
  `Button`, `Input`, `Tooltip` (the hover pop-up under HelpTerm), `Collapsible`
  (the fold-away transcript), `InlineAlert`, `EmptyState`, `PageHeader`, `AppPage`.
  Changing these changes every page, not just /tiered.
  (Note: `Card` ignores unknown props like `data-testid` — put test ids on an inner div.)
- **`index.css`** — the design tokens: color variables (`--color-cyan`, success/
  warning/danger, surface colors) and the `terminal-card` style that gives cards
  their look. Change the palette here.
- **`tailwind.config.js`** — Tailwind setup. Tailwind is the styling system used
  throughout: classes like `mt-3 text-xs text-secondary-text` on elements *are* the
  styles. Most visual tweaks = editing those class strings right in the components.

## 5. What feeds the page

### `api/tiered.ts`
The bridge to the backend: the fetch calls (start a run, list runs, get one run)
plus TypeScript *types* — written descriptions of the JSON's exact shape
(`TieredResult`, `TieredFinal`, `TieredSizing`, …). Read this to know what data a
card can show. Note many fields are optional because old stored runs predate v2 —
every card must survive those fields being missing.

## 6. Backend (context only — no need to touch for UI work)

Repo root, Python:

- `api/v1/endpoints/tiered.py` — the HTTP endpoints and the code that shapes the JSON.
- `src/tiered_analysis/` — the engine: `integration.py` (orchestrates a run),
  `levels.py` (price-level formulas), `debate.py` / `risk.py` (tiers 2–3),
  `sizing.py` (share-count math), `signal_log.py` (ledger entries), `settings.py`
  (env-var sizing settings), `llm_support.py` (AI-call plumbing + cost counting).
- `tests/test_tiered_*.py` — backend tests; `docs/tiered-analysis-formulas.md` — the
  formula reference the level modals mirror; `docs/tiered-analysis-v2-plan.md` — the
  slice-by-slice build plan.
- Results are stored in `data/stock_analysis.db` (SQLite).

## 7. How to work on it

### Starting the server

The backend server (uvicorn — the program that runs the Python API and also serves
the built website at http://localhost:8000) is started **from the repo root**
(`~/developer/personal/daily_stock_analysis`), not from `apps/dsa-web`:

```bash
cd ~/developer/personal/daily_stock_analysis
.venv/bin/python -m uvicorn server:app --host 0.0.0.0 --port 8000
```

This runs it **in the foreground**: logs print straight to the terminal, and
**stopping it is just Ctrl+C** in that terminal. The terminal is occupied while
it runs, and closing the terminal kills the server — for day-to-day use that's
the simplest setup.

If you instead want it to survive after closing the terminal, use the
**background** variant (`nohup ... &` = "keep running after the terminal
closes, in the background"; output goes to `logs/uvicorn-manual.log`):

```bash
nohup .venv/bin/python -m uvicorn server:app --host 0.0.0.0 --port 8000 >> logs/uvicorn-manual.log 2>&1 &
```

**Before starting, check whether one is already running** — starting a second
copy is harmless (it dies with `Exit 3` because port 8000 is taken) but noisy:

```bash
pgrep -f "uvicorn server:app"        # is it running? (prints its process id, or nothing)
tail -20 logs/uvicorn-manual.log     # latest log lines (background variant only)
```

To **stop** a background server (a foreground one is just Ctrl+C):

```bash
pgrep -f "uvicorn server:app"        # get its process id
kill <that id>                       # ask it to shut down cleanly
```

To **restart** (needed whenever backend Python code changes — frontend-only
changes just need `npm run build` + a hard refresh): stop it, then start it
again.

> Gotcha: don't use `pkill -f "uvicorn server:app"` inside a combined command —
> the pattern matches the command you're typing and can kill your own shell.
> `pgrep` first, then `kill` the printed id.

### Frontend commands

```bash
cd apps/dsa-web
npm run dev        # live-editing server at http://localhost:5173/tiered
                   #   (auto-reloads on save; talks to the backend on :8000,
                   #    so keep uvicorn running)
npm run test       # run the automated checks (or: npx vitest run src/components/tiered)
npm run lint       # style/correctness checker
npm run build      # production build → repo-root static/, which uvicorn serves
                   #   at http://localhost:8000/tiered (hard-refresh after)
```

Two repo tripwires that fail tests/lint if hit:

1. **No native `title="..."` attributes** on elements (a governance test bans them —
   use `aria-label` for icon/link labels, or `HelpTerm`/`Tooltip` for hover text).
2. **Component files must export only components** (split plain helpers into a
   separate `.ts` file, as `termHelpers.ts` does).

And one habit: never hardcode a visible string in a component — add a key to
`uiText.ts` (both languages) and render it with `t('the.key')`, matching how
everything else on the page does it.
