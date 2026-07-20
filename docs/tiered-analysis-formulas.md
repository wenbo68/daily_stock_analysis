# Tiered Analysis — Formula Reference

> Companion to `docs/tiered-analysis-design.md` and `docs/tiered-analysis-v2-plan.md`.
> Every deterministic number in the tiered-analysis feature is defined here, with a
> plain-English explanation of what it measures and why the formula looks the way it
> does. The slice-7 frontend "formula modals" render from the same definitions.
> Convention: all levels are written for a **buy**; v2 does not size short positions.

## 1. Technical indicators (v1, `providers/technicals.py`)

These are computed from daily price bars (open/high/low/close) — no AI involved.

### SMA — simple moving average

```
SMA(n) = (close₁ + close₂ + … + closeₙ) / n        (last n trading days)
```

The average closing price over the last *n* days. It smooths daily noise into a
trend line. Traders watch SMA-20 (≈ one trading month) as short-term support and
SMA-60 (≈ one quarter) as deeper support — prices often pause or bounce there
because so many participants anchor on the same lines.

### EMA — exponential moving average

```
EMA_today = close_today × k + EMA_yesterday × (1 − k),   k = 2 / (n + 1)
```

Like the SMA but weighting recent days more heavily, so it reacts faster to new
moves. Used here as the ingredient for MACD (n = 12 and 26).

### RSI — relative strength index (Wilder, 14-day)

```
RSI = 100 − 100 / (1 + avg_gain / avg_loss)        (14-day Wilder smoothing)
```

Scores 0–100 how one-sided recent movement has been. Above ~70 the stock has risen
unusually persistently ("overbought" — pullback risk); below ~30 it has fallen
unusually persistently ("oversold").

### MACD — moving average convergence/divergence

```
MACD line = EMA(12) − EMA(26)
signal    = EMA(9) of the MACD line
histogram = MACD line − signal
```

Measures whether short-term momentum is pulling away from the longer trend.
Histogram above zero and rising = strengthening momentum; crossing down = fading.

### ATR — average true range (14-day)

```
true_range_day = max(high − low, |high − prev_close|, |low − prev_close|)
ATR = Wilder average of true_range over 14 days
```

The stock's **typical daily swing in currency units**, gap days included. ATR is
the volatility yardstick every level formula below leans on: "1 ATR" means "one
ordinary day's worth of movement".

### BIAS-20

```
BIAS = (close − SMA(20)) / SMA(20) × 100
```

How far (in %) today's price has stretched away from its own 20-day average.
Large positive = extended above trend (chasing); large negative = washed out.

### Technicals score (0–100)

A weighted composite of the indicators above (trend position, momentum, RSI zone,
extension) produced by deterministic rules in `technicals.py` — higher = technically
stronger. It is a ranking aid, not a probability.

### Swing lows and highs (20- and 60-day), 52-week range

```
swing_low(n)  = min(low  of each of the last n trading days)    n = 20, 60
swing_high(n) = max(high of each of the last n trading days)    n = 20, 60
high_52w / low_52w = the same over the last 250 trading days (~1 year)
```

Swing lows are floors the market has already defended; swing highs are ceilings
where sellers appeared before. The outlook redesign (2026-07) extended the price
history to ~250 bars so the 52-week range and the 60-day swings exist.

### Average daily volume (20-day) and worst single day

```
avg_volume_20 = mean(volume of the last 20 trading days)        (None if no volume data)
worst_day_1y  = the single worst daily return of the last ~250 bars
```

Both feed the display-only risk card (§7) only — they never move levels or
sizing. (`worst_day_1y` replaced the softer `worst_day_5pct` percentile,
2026-07-21; old stored runs still carry the retired key.)

## 2. Price levels — formula-only (outlook redesign, `levels.py`)

Owner decision 2026-07-20: **levels are pure formulas at every depth. The AI level
adjuster is deleted** — no nudging, no bands. What the formulas print is the plan.

### Trend gate

```
if close ≤ SMA(60):  no buy plan at all (warning explains)
if SMA(60) missing:  gate skipped, warning notes it
```

Pullback-buying only makes sense in an uptrend. Below the one-quarter average the
"support" anchors are falling with the price, so the whole plan is withheld rather
than printed with false confidence.

### Ideal entry

```
support candidates = {SMA(20), SMA(60), swing_low_20, swing_low_60, round_number_below(close)}
ideal_entry = min(close, max(candidates))
```

"Buy the pullback to the nearest real support." The candidate set grew in the
redesign: both averages, both swing lows, and the nearest round number below the
price (10s above 100, 5s above 20, …) — round numbers act as psychological floors
because many resting orders sit exactly there. The `min(close, …)` cap makes sure
we never suggest paying more than the current price.

### Backup entry — retired (owner decision, 2026-07-21)

The plan is one order at the ideal entry; a resting limit order fills when the
price reaches it, so a second lower entry added confusion without value. Old
stored runs may still carry a `secondary_entry`; new runs never compute one and
the UI shows no backup column.

### Stop-loss

```
stop_loss = ideal_entry − 2 × ATR
```

Two typical days of adverse movement below the planned entry. Far enough that
ordinary daily noise doesn't eject you; close enough that a real breakdown gets you
out. Volatile stocks automatically get wider stops.

### Target / take-profit — resistance-aware, user-chosen ratio

```
R           = the user's reward-to-risk ratio (run form "Reward" field, default 2)
geometric   = ideal_entry + R × (ideal_entry − stop_loss)
resistances = {swing_high_20, swing_high_60, high_52w} strictly above close
target      = min(geometric, nearest resistance above close)
```

Demand R times the upside of the accepted downside — but never pretend the price
can sail through a ceiling where sellers already showed up once. If overhead
resistance caps the target, the target honestly stops there; if the capped ratio
falls below the user's chosen R (but clears the 1.5 floor), the plan carries a
visible "reward below goal" warning instead of bending any level.

### Room gate

```
if (target − ideal_entry) / (ideal_entry − stop_loss) < 1.5:  no plan (warning)
```

If the nearest ceiling is so close that the capped trade cannot pay at least
1.5-to-1, the whole plan is withheld — a trade without room is not worth printing.
The 1.5 floor is absolute; the user's chosen R only warns (above), never voids.

### Dependency chain

`trend gate → supports → ideal entry → stop → target → room gate`. A
missing upstream input makes the downstream levels explicitly unavailable (with a
warning) — never silently guessed.

## 3. Outlook → action table (outlook redesign, `schema.py`)

The run's judgment splits into two things: the **outlook** on the stock itself
(bullish / neutral / bearish — the tier-2 vote's direction, or tier 1's at depth 1)
and the **action** for this user, derived by a pure code table from outlook ×
ownership (the share count the user holds; the API still accepts it, but the
alt form no longer collects it — the input is deferred to the future portfolio
feature, so runs from that page always use ownership = 0):

```
outlook   ownership = 0    ownership > 0
bullish   enter            keep_holding      (deliberately NOT "buy more")
neutral   no_trade         keep_holding
bearish   no_trade         sell_all          (sell_shares = the full holding)
unknown   unknown          unknown           (failed run — re-run)
```

Next-earnings date (US tickers, yfinance): fetched per run, **warning-only** — a
"{N} days until next earnings — expect turbulence" note when within 7 calendar
days. It never gates a plan and never moves a number. No expiry mechanism exists;
a report from a previous trading day just shows a "re-run for a fresh plan" note.

## 4. Position sizing (v2 slice 1, `sizing.py`)

```
loss_per_share = (entry − stop_loss) + entry × fee_fraction
risk_budget    = capital × risk_fraction
shares         = floor(risk_budget / loss_per_share)          then:
                 capped so shares × entry ≤ capital × 25%
                 rounded down to the market's lot size (CN: 100)
```

You choose the money you can lose on one trade (`capital × risk_fraction`, e.g.
$50,000 × 1% = $500). The entry-to-stop gap plus round-trip trading costs
(`fee_fraction`, default 0 — broker-specific) is what being wrong costs per share.
Division gives the share count, so **every losing trade costs the same planned
amount**. The 25% cap stops a tight stop from producing an oversized position; lot
rounding keeps the count orderable. Any unmet precondition (no stop, stop above
entry, missing settings, count rounds to zero…) produces an explicit refusal with a
reason — never a silent zero. Spread and slippage are deliberately out of scope:
they can't be known in advance.

Outlook redesign: the tier-3 size multiplier is gone. A bearish outlook while
holding exits the **full** holding (`sell_shares = ownership`); shares are never
scaled by any AI-derived factor.

## 5. Constants

| Constant | Value | Where | Why this value |
| --- | --- | --- | --- |
| ATR period | 14 days | technicals | Wilder's original; the de-facto standard |
| Swing lookbacks | 20 / 60 days | levels | one trading month / one quarter |
| Year of bars | 250 trading days | technicals | 52-week range and worst-day history |
| Stop distance | 2 × ATR | stops | classic noise-vs-breakdown balance point |
| Reward-to-risk (geometric target) | user-chosen, default 2.0 | levels | the run form's "Reward" field; below it → warning |
| Reward-to-risk (room gate) | 1.5 | levels | a resistance-capped plan below this is withheld |
| Position cap | 25% of capital | sizing | concentration guard when stops are tight |
| CN lot size | 100 shares | sizing | A-share board-lot rule |
| Earnings warning window | 7 calendar days | earnings | close enough that turbulence is imminent |
| Bullet weight range | 1–5 | debate | very minor → very important (thesis-changing) |
| Risk-card ADV flag | 5% of avg volume | risk card | above this, a one-day exit moves the price |
| Risk-card volatility flag | 4% ATR/close | risk card | above this, daily noise dominates tight stops |
| Risk-card gap scenario | 1 × ATR past stop | risk card | one ordinary day's jump beyond the stop |

## 6. Tier-2 evidence vote (v11 — weighted 1–5, `debate.py` + `debate_models.py`)

No roles, no personas — membership in the evidence pool is a majority
vote with at most three votes per bullet, and no AI authors any number
(owner spec 2026-07-18; full design in
`.claude/reviews/tier2-v5-design.md`, v6/v7/v8 revision sections):

```
step 1  Two ANALYSTS independently list ALL evidence (bullish +
     ‖  bearish) per dimension, blind to each other — each list runs
        through the code citation check + fix loop
step 2  MERGE call: a match map only (same evidence + same direction =
        the same bullet; an opposite-direction clash is a dispute and
        stays unmatched so both versions face the votes). Code
        assembles the merged list.
step 3  CHECK round: every bullet's author is automatically its first
        valid vote, so a bullet BOTH analysts listed independently is
        confirmed 2-0 on the spot; single-author bullets get the second
        vote here (2-0 in, or 1-1 tied)
step 4  DECIDING round, only when there are ties: sees the claim and
        the objection, casts the third vote — 2-1 in, 1-2 out. Three
        votes, so a tie is impossible.
step 5  summary prose around the computed numbers (never voids)
```

Per-dimension bullet counts: floor 2, ceiling = the number of leaf
fields in that dimension's report (sentiment: verified sources × 2) —
room for the whole report, not a quota. Macro-econ ids are E1, E2….

Citations are `{ref, value}`; sentiment bullets cite sources with bare
`{ref: citation:N}`, rendered by the UI as trailing [N] hyperlinks (a
model-written literal "[N]" in the sentence is stripped by code). The
prompts render every payload number through `display_value` — the same
formatting the web report pages use — so the model never sees raw
floats. Code verifies each link: the ref resolves to a single leaf, the
value equals the report's display string exactly, and that string
appears in the sentence (thousands separators tolerated; digit
boundaries stop `205` matching inside `1205` or `205.4`). Failures go
back to the same AI in up to `MAX_FIX_ROUNDS = 3` focused fix calls
carrying only the broken bullets; bullets still broken are STRUCK —
crossed out, never voted on, in no pool. VOTE reasons follow the same
contract (a reason stating a decimal or percentage must cite it; links
inside reasons are code-checked with the same fix loop) — votes that
cannot be fixed are discarded and carry no weight.

Weights (v11, owner spec 2026-07-20; v10 used a 1–3 scale): every
voter also RATES each bullet's importance 1–5 — 1 = very minor, 3 =
normal evidence, 5 = very important (could change the whole thesis
alone) — and gives ONE short plain sentence saying why
(`weight_reason`, shown in the UI's check modals; report numbers are
banned there — they belong in the cited claim/reason). Listers rate
their own bullets in the same call (the second author's rating and its
reason ride in on the merge match map; stored per lister in
`author_votes`); check and deciding votes carry a rating regardless of
their verdict. An omitted rating degrades to 3 (the middle, which
reproduces flat counting exactly); citation-fix rounds freeze the
original rating and its reason so a fix reply cannot silently reset
them.

The score (code, pure arithmetic):

```
bullet_weight = median of its voters' 1-5 ratings
                (two voters → their mean, so halves like 2.5 happen)

score = 10 × Σweight(bullish) / Σweight(all)     over the pool (2 decimals)

initial = the merged list, weighted by the authors' own ratings
          (struck bullets excluded; stored for the audit trail)
final   = the bullets holding a majority of valid votes, weighted by
          the full voter median — the displayed score

direction = sell if final < 4, hold if 4 ≤ final ≤ 6, else buy
empty final pool → 5.00, hold, warning
```

Every vote requires a short reason (the UI shows it when the user
clicks the vote's ✓/✗ mark).

5-6 base calls per run (the two lists parallel, each with its fix loop;
the deciding round only when there are ties; fix rounds add one call
each), all at temperature 0 (`deterministic_summarizer`). Failure
rules: both lists failing voids the run (NO tier-1 fallback since the
outlook redesign — a failed vote is an honest UNKNOWN with a "re-run"
warning); one list failing proceeds with the other; a failed merge
drops the second list; a failed check round counts bullets on the
author's vote alone; a failed deciding round excludes ties as
unresolved; the summary's failure never voids anything.

Depth semantics since the redesign: depth 1 runs the one-blob tier-1
judge as before; depth 2 SKIPS the blob entirely — the run builds a
data-layer foundation report (levels + dimensions, direction unknown)
and the vote above is the sole judge. Depth 3 is a validation error
(tier 3 is retired; `risk.py`, `risk_models.py`, `adjustments.py` are
deleted).

## 7. Display-only risk card (outlook redesign, `risk_card.py`)

Six deterministic pre-trade checks — computed from data the run
already has. ZERO LLM calls, and by explicit owner decision the card
affects NOTHING: outlook, action, levels and sizing never read it.
Each entry is `{id, status, values}` with status `ok`, `flag` (a
threshold crossed) or `na` (inputs missing on this run); all wording
lives in the frontend i18n layer, and every number in the UI opens a
receipt modal showing its computation.

The 6 entries, in frozen order (`RISK_CARD_IDS`):

```
 1 liquidity          shares / avg_volume_20; flags > 5% of a day's volume
 2 gap_stress         two overnight scenarios: (a) worst_day_1y drop from the
                      entry — if the open lands below the stop, the sale price,
                      total loss and extra loss vs plan (flags when it gaps);
                      (b) open = stop − 1 ATR, same outputs
 3 volatility         ATR / close; flags > 4%
 4 reward_risk        (target − entry) / (entry − stop); flags below the
                      user's chosen ratio (run form "Reward" field)
 5 stop_atr           (entry − stop) / ATR
 6 stop_vs_swing_low  flags a stop at/above the 20-day low
```

Trimmed from 13 (owner decision, 2026-07-21): concentration, cash,
max-planned-loss, one-day VaR (folded into the gap check's worst-day
scenario), staleness, both-entries (gone with the backup entry) and
ownership-context (returns with the future portfolio feature). Old
stored runs keep rendering their 13-entry cards.
