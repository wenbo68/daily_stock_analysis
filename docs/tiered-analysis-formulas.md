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

### Swing low (20-day)

```
swing_low = min(low of each of the last 20 trading days)
```

The lowest price actually traded in the last month — a floor the market has already
defended once. Added to the technicals payload in v2 slice 3 as a support anchor.

## 2. Price levels — deterministic bases (v2 slice 3, `levels.py`)

Design rule (anchor-and-adjust): **formulas produce a base for every level; the AI
may only nudge a base within a bounded band, with cited evidence; code re-validates.**

### Ideal entry (base)

```
ideal_entry = min(close, max(SMA(20), swing_low))
```

"Buy the pullback to the nearest real support." The higher of the two support
anchors (20-day average, 20-day swing low) is the nearest floor; the `min(close, …)`
cap makes sure we never suggest paying more than the current price.

### Backup entry (base)

```
backup_entry = highest support anchor strictly below ideal_entry
               (candidates: SMA(60), swing_low)
```

The "if it falls further" level: the next genuine floor beneath the ideal entry.
If no candidate sits below the ideal entry, there is no backup — the report says so
instead of inventing one.

### Stop-loss (base)

```
stop_loss = ideal_entry − 2 × ATR
```

Two typical days of adverse movement below the planned entry (v2 slice 2,
`stops.py`). Far enough that ordinary daily noise doesn't eject you; close enough
that a real breakdown gets you out. Volatile stocks automatically get wider stops.

### Target / take-profit (base)

```
target = ideal_entry + 2 × (ideal_entry − stop_loss)
```

A reward-to-risk multiple: demand twice as much upside as the downside you accept.
With the ATR stop above, this works out to entry + 4 × ATR. If a trade can't
plausibly pay 2-to-1, it isn't worth taking — that discipline is the formula.

### Dependency chain

`swing_low/SMA → ideal entry → stop → target`. A missing upstream input makes the
downstream levels explicitly unavailable (with a warning) — never silently guessed.

## 3. AI adjustment guardrails (v2 slice 3, `adjustments.py` + `levels.py`)

The AI reads the collected evidence and may propose a new value per level, with a
reason. Code then enforces:

```
band:      |adjusted − base| ≤ 1 × ATR            else adjustment rejected
ordering:  stop < backup ≤ ideal < target          checked after each adjustment
reward:    (target − ideal) / (ideal − stop) ≥ 1.5 checked after each adjustment
evidence:  every reason must cite ≥ 1 verifiable ref
           (a dimension payload key, or a verified sentiment citation [n])
```

A rejected adjustment never edits the number — the base stands and the rejection is
shown as a warning. Rationale: an adjustment bigger than one typical day's swing is
no longer "context on top of the formula", it's a different number without an audit
trail; and a reason that cites nothing verifiable is indistinguishable from a
hallucination.

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

## 5. Constants

| Constant | Value | Where | Why this value |
| --- | --- | --- | --- |
| ATR period | 14 days | technicals | Wilder's original; the de-facto standard |
| Swing-low lookback | 20 days | levels | ≈ one trading month, matches SMA-20 |
| Stop distance | 2 × ATR | stops | classic noise-vs-breakdown balance point |
| Reward-to-risk (base target) | 2.0 | levels | common minimum for a trade to be worth it |
| Reward-to-risk (validation floor) | 1.5 | levels | adjusted set may not degrade below this |
| Adjustment band | 1 × ATR | levels | beyond one typical day's swing = re-invention |
| Position cap | 25% of capital | sizing | concentration guard when stops are tight |
| CN lot size | 100 shares | sizing | A-share board-lot rule |

## 6. Tier-2 evidence debate (v5 redesign, `debate.py` + `debate_models.py`)

One evidence pool, three roles, no forced bull/bear personas
(owner spec 2026-07-17; full design in `.claude/reviews/tier2-v5-design.md`):

```
step 1  DEFENDER lists ALL evidence (bullish + bearish) per dimension
        (2-4 items per dimension with data) + initial position score
     ‖  ATTACKER independently builds its own list (blind, in parallel)
step 2  ATTACKER matches the two lists (uncovered own items become
        additions), then checks every defender item on two axes:
        citation and logic
step 3  DEFENDER responds to every challenge by running the same two
        checks ON the challenge itself: both valid → accept (concede /
        adopt), either invalid → rejection; then the adjusted score
        (whole 0-10 or "keep"). Skipped when nothing was challenged.
step 4  JUDGE, final say, binary rulings only: its own checks on every
        defender item, attack_right/attack_wrong per attack,
        real/bogus per addition
step 5  summary prose around the computed numbers (never voids)
```

Every stage fills a strict Pydantic form; an invalid reply gets one
retry with the validation errors shown. Defender/judge failures void the
tier-2 verdict (direction falls back to tier 1); attacker failures
degrade loudly (checks-only review, or no challenges at all). Citations
must resolve to a single payload value (leaf paths — `technicals.macd`
is rejected, `technicals.macd.signal` passes) or an in-range sentiment
`citation:N`; invalid refs are stripped by code.

The weight ledger (code, not LLM — one principle):

```
1/1  every item the defender correctly kept in the pool
0/1  every item the defender got wrong (kept bad / dropped good,
     per the judge)
0/0  items correctly removed (conceded reasons, rejected bogus
     additions) — they don't count at all

weight = correct keeps / (correct keeps + errors)      (0 on 0/0 ledger)
final  = 5 + weight × (adjusted − 5)                   2 decimals
direction = sell if final < 4, hold if 4 ≤ final ≤ 6, else buy
```

The weight shrinks the defender's conviction toward neutral 5 by exactly
the share of the evidence pool it mishandled; garbage arguments can
never produce a strong verdict, only "do nothing". Flags that never
change numbers: the defender accepting an attack the judge ruled wrong,
and a thin base (more than half the initial reasons died). All tier-2
LLM calls run at temperature 0 (`deterministic_summarizer`); 6 calls per
run across 5 sequential steps (the two openings run in parallel; the
defender-reply call is skipped when there are no challenges).
