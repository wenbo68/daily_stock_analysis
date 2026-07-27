# Technicals Report Spec — Swing Trading (LLM-consumed)

Purpose: feed an LLM enough pre-computed technical state to output (a) an outlook
(bullish / bearish / neutral) and (b) a trade plan (entry, target, stop, shares).

Design principle: **every field ships as number + label.** LLMs reason more
reliably over pre-classified states ("extended", "contracting") than raw floats,
but the trade-plan math (stop distance, share count, R:R) needs the numbers.
Compute the label in code — never make the LLM re-derive a threshold.

Bars to fetch: **300 daily, 130 weekly** (see §10).
Units convention: distances in **ATR multiples** wherever comparability matters;
% only for returns and ranges.

---

## 1. Meta

| Field | Calculation | Why the LLM needs it |
|---|---|---|
| `as_of` | Timestamp of last completed bar | Staleness check; refuse to plan on old data |
| `daily_bars`, `weekly_bars` | Count fetched | Validity check — if < required, downstream fields are unreliable and the LLM should say so |
| `data_ok` | `daily_bars >= 300 and weekly_bars >= 130` | Single boolean gate |

## 2. Market regime (index-level, computed once per run)

Most long setups fail in a down market regardless of the individual chart.
This section should be the LLM's first read.

| Field | Calculation | Interpretation |
|---|---|---|
| `index_above_200d` | Benchmark close > its SMA200 | Base risk-on/risk-off gate |
| `index_pct_of_1y_range` | `(close − 1y low) / (1y high − 1y low) × 100` on the index | >70 strong tape, <30 weak tape |
| `index_20d_return_pct` | Index % change over 20 bars | Short-term tape direction |
| `regime_label` | `bullish` if above 200d and range% > 50; `bearish` if below 200d and range% < 50; else `mixed` | LLM instruction: in `bearish`, demand A+ setups only and cut position size; in `mixed`, reduce targets |

## 3. Relative strength vs benchmark

Highest-value section for stock selection. A clean chart that lags the index is
usually a trap.

| Field | Calculation | Interpretation |
|---|---|---|
| `rs_1m`, `rs_3m`, `rs_6m` | Stock % return − index % return over 21 / 63 / 126 bars | Positive = leader, negative = laggard |
| `rs_trend` | Sign pattern across the three horizons | `improving` (1m > 3m > 6m ordering), `deteriorating` (reverse), `stable` |
| `rs_label` | `leader` if rs_3m > 0 and rs_1m > 0; `laggard` if both < 0; else `neutral` | LLM instruction: prefer longs in leaders; a laggard long needs an explicit catalyst from the other reports |

## 4. Price & range position

| Field | Calculation | Interpretation |
|---|---|---|
| `close` | Last daily close | Anchor for all distances |
| `chg_1d_pct`, `chg_5d_pct` | % change over 1 / 5 bars | Immediate momentum; also flags "already moved" — a +8% 1d bar means the easy entry is gone |
| `high_1y`, `low_1y` | Max high / min low over 253 bars (intraday extremes, not closes) | Range boundaries |
| `days_since_high_1y`, `days_since_low_1y` | Bars elapsed | Recent high (<10 bars) = breakout context; distant high (>120) = basing or downtrend |
| `pct_of_1y_range` | `(close − low_1y) / (high_1y − low_1y) × 100` | >80: strength but breakout-chase risk. 40–80: pullback-buy zone if trend intact. <20: falling knife unless basing evidence |
| `dist_to_high_1y_atr` | `(high_1y − close) / ATR14` | Overhead supply proximity — a target beyond the 1y high needs breakout logic, not pullback logic |

## 5. Weekly timeframe (outlook)

| Field | Calculation | Interpretation |
|---|---|---|
| `sma10w`, `sma30w`, `sma40w` | Simple MA of weekly closes | Levels |
| `sma10w_slope_pct` | `(SMA10w_now − SMA10w_6w_ago) / SMA10w_6w_ago × 100` | Direction and steepness of intermediate trend. Flat = < ±0.5% per 6w |
| `weekly_stack` | `bull` if 10w > 30w and close > 10w; `bear` if inverse; else `mixed` | Weinstein-style stage read |
| `close_vs_10w_atr` | `(close − SMA10w) / weekly_ATR` | Extension: > +1.5 = extended, wait for pullback; −0.5 to +1 = pullback-buy zone in an uptrend |
| `weekly_pivot_structure` | From last 4–5 weekly swing points (pivot = bar with N higher/lower bars each side, N=2) | `HH_HL` / `LL_LH` / `sideways` |
| `weekly_trend` | Combine stack + pivots: agree bullish → `bullish`; agree bearish → `bearish`; disagree → `neutral` | **Primary outlook input.** LLM instruction: daily signals only generate trades in the direction of `weekly_trend`; against it, best output is "no trade" |

## 6. Daily timeframe (trade plan)

### Trend
| Field | Calculation | Interpretation |
|---|---|---|
| `sma20d`, `sma50d`, `sma200d` | Daily simple MAs | Levels; 50d is the classic swing pullback magnet |
| `sma50d_slope_pct` | 15-bar lookback, as weekly | Trend health |
| `daily_stack` | `bull` if close > 20 > 50, `bear` if inverse, else `mixed` | |
| `close_vs_50d_atr` | `(close − SMA50d) / ATR14` | Entry timing: −1 to +1 in an uptrend = pullback entry zone; > +3 = extended, chase risk |
| `daily_pivot_structure` | Same method as weekly, daily bars | `HH_HL` / `LL_LH` / `sideways` |
| `daily_trend` | Stack + pivot combine, same rule as weekly | |

### Momentum
| Field | Calculation | Interpretation |
|---|---|---|
| `rsi14` | Wilder RSI, 14 | >70 stretched up, <30 stretched down, ~50 neutral. In strong trends RSI pins — do not auto-fade |
| `rsi14_slope` | `rsi_now − rsi_5_bars_ago` | Strength building (+) or draining (−) |
| `macd_hist` | `MACD(12,26) − signal(9)` | Momentum of momentum |
| `macd_hist_direction` | Sign of 3-bar change | `expanding` / `contracting` |
| `macd_above_zero` | MACD line > 0 | Trend direction (12 EMA vs 26 EMA). Histogram positive while line negative = bounce in downtrend, not pullback in uptrend |
| `momentum_label` | `strong` (RSI > 55, hist expanding, line > 0) / `weak` (mirror) / `fading` (RSI > 55 but hist contracting) / `basing` (RSI < 45 but hist expanding) / `neutral` | Pre-resolved RSI-vs-MACD disagreement so the LLM doesn't have to |

### Divergence (optional but high value)
| Field | Calculation | Interpretation |
|---|---|---|
| `rsi_divergence` | Price makes new 20-bar high/low but RSI doesn't | `bearish_div` / `bullish_div` / `none` — early exhaustion warning, weight it below structure |

## 7. Volatility

| Field | Calculation | Interpretation |
|---|---|---|
| `atr14` | Wilder ATR, 14, in $ | The unit for stops, targets, and sizing |
| `atr14_pct` | `ATR14 / close × 100` | Cross-stock comparability; >6% = high-volatility name, halve size |
| `atr_trend` | ATR14 vs ATR14 20 bars ago, ±10% bands | `expanding` (widen stops, shrink shares) / `contracting` (squeeze — often precedes a move) / `stable` |

## 8. Volume & liquidity

| Field | Calculation | Interpretation |
|---|---|---|
| `avg_vol_60b` | Mean volume, 60 bars | Baseline |
| `vol_ratio_5b` | `avg_vol_5b / avg_vol_60b` | >1.5 on a breakout = confirmed; <0.7 = suspect move |
| `dollar_vol_60b` | `avg_vol_60b × close` | Liquidity gate: LLM instruction — position must stay under ~0.5% of daily dollar volume; below ~$5M/day flag as thin |
| `up_down_vol_ratio` | Sum of volume on up days / down days, 20 bars | >1.3 accumulation, <0.7 distribution |

## 9. Levels & risk (what makes the trade plan computable)

This section turns structure into numbers the LLM can do arithmetic on.

| Field | Calculation | Interpretation |
|---|---|---|
| `support_1`, `support_2` | Nearest pivot lows below close (price levels) | Stop goes below one of these, not at an arbitrary % |
| `resistance_1`, `resistance_2` | Nearest pivot highs above close | Target candidates |
| `dist_support_1_atr` | `(close − support_1) / ATR14` | Stop distance in risk units |
| `dist_resistance_1_atr` | `(resistance_1 − close) / ATR14` | Reward distance |
| `rr_to_r1` | `dist_resistance_1_atr / (dist_support_1_atr + 0.5)` | Pre-computed reward:risk assuming stop 0.5 ATR below support. LLM instruction: skip trades below 2.0 |
| `typical_pullback_atr` | Median depth of last 4–5 completed pullbacks, in ATR | Reality check: if `dist_support_1_atr` < typical pullback, a normal wiggle stops you out — widen or wait |
| `max_drawdown_1y_pct` | Largest peak-to-trough % decline in 253 bars | Tail behavior; >50% = character flag |
| `gap_frequency` | Count of >2×ATR overnight gaps, 60 bars | Gappy names need wider stops and smaller size; stops don't protect through gaps |

## 10. Events

| Field | Calculation | Interpretation |
|---|---|---|
| `days_to_earnings` | Calendar days to next confirmed report | **Hard gate**: if < planned hold period (~10 days), LLM must either exit-before-earnings the plan or decline the trade. Technicals do not survive earnings |
| `ex_div_within_hold` | Boolean | Minor, affects stop math on high-yield names |

---

## Bar requirements (why 300 / 130)

Snapshot feeds take the **max** across fields, not the sum:

- 1y extremes, range %, max drawdown → 253 daily
- SMA200 + 15-bar slope → 215
- RSI/MACD (recursive, need ~3× period to converge) → ~100
- Pivot structure (4–5 swings) → ~120
- **Daily = 300** (253 binds, margin for holidays)
- SMA40w + 6-bar slope → 46; pivots ~100 weekly bars
- **Weekly = 130**

Exception: any *percentile-over-window* field (e.g. "today's extension ranked
against the past year") adds instead of maxing: 253 + indicator period. Adding
one on SMA200 distance pushes daily to ~460 bars.

## Suggested LLM decision skeleton (system-prompt material, not report fields)

1. `data_ok` false → report only, no plan.
2. `days_to_earnings` < hold period → no new position (or explicit pre-earnings exit).
3. `regime_label` bearish → longs need `rs_label = leader` AND `weekly_trend = bullish`; otherwise pass.
4. Outlook = `weekly_trend`, moderated by `momentum_label` and divergence.
5. Trade direction must match weekly trend; entry timing from `close_vs_50d_atr` (enter in pullback zone, never when extended > +3).
6. Stop = 0.5 ATR below `support_1`; sanity-check against `typical_pullback_atr`.
7. Target = `resistance_1` (or `resistance_2` if `rr_to_r1` < 2 but structure supports it).
8. Shares = `risk_budget_$ / (entry − stop)`, capped by `dollar_vol_60b` liquidity rule; halve if `atr_trend = expanding` or `atr14_pct` > 6.
