import type { UiLanguage } from './uiText';

// Vocabulary for tiered-analysis dimension payloads (backend keys stay
// snake_case on purpose — see api/tiered.ts). Each entry has the compact
// label shown in the table (`short`) and the plain-language definition
// shown in the hover/click popup (`full`). Entries may also carry
// `interp` — how to read the number as a trader; when present the popup
// renders "Meaning: … / Interpretation: …" as two blocks (owner format
// 2026-07-29). Unknown keys fall back to the raw key with no popup.
export interface MetricEntry {
  short: string;
  full: string;
  interp?: string;
}

const en: Record<string, MetricEntry> = {
  // ---- technicals ----
  close: {
    short: 'Closing price',
    full: "The last traded price of the most recent trading day.\nUnit: the stock's own currency (USD for US stocks).",
    interp: 'The anchor every distance in this report is measured from.',
  },
  bars_count: {
    short: 'Bars',
    full: 'How many trading days of price history were used for these calculations.',
  },
  sma_20: {
    short: 'SMA 20',
    full: '20-day simple moving average — the average closing price over the last 20 trading days.\nSmooths out daily noise to show the short-term trend.',
  },
  sma_60: {
    short: 'SMA 60',
    full: '60-day simple moving average — the average closing price over the last 60 trading days; the medium-term trend line.',
  },
  ema_12: {
    short: 'EMA 12',
    full: '12-day exponential moving average — like a simple average, but recent days count more.',
  },
  ema_26: {
    short: 'EMA 26',
    full: '26-day exponential moving average — a slower-moving weighted average used together with EMA 12.',
  },
  rsi_14: {
    short: '14d RSI',
    full: 'Relative Strength Index (14 days) — a 0-to-100 speedometer for how fast the price has been rising or falling.\nRange: 0–100. Above 70 = rose unusually fast; below 30 = fell unusually fast; around 50 = calm.\nCaution: in strong trends it can stay above 70 for weeks — high alone is not a sell signal.',
  },
  macd: {
    short: 'MACD',
    full: 'Moving Average Convergence Divergence — a trend-momentum indicator built by comparing a fast and a slow moving average.',
  },
  signal: {
    short: 'Signal',
    full: 'The signal line — an average of the MACD line.\nThe MACD line crossing above or below it is a common buy/sell trigger.',
  },
  histogram: {
    short: 'Histogram',
    full: 'MACD line minus signal line.\nPositive and growing = upward momentum building; negative = fading.',
  },
  atr_14: {
    short: '14d ATR',
    full: "Average True Range (14 days) — the typical size of one day's price move.\nUnit: the stock's currency; e.g. an ATR of $19 means a normal day moves the price about $19.",
    interp: 'The ruler stops and position sizes are measured with — distances in ATRs compare fairly across stocks.',
  },
  volatility_pct: {
    short: 'Volatility %',
    full: 'The typical daily swing (ATR 14) as a percent of the price.\nAbove ~4% counts as a high-volatility stock — the plan review may trim size or widen the stop.',
  },
  swing_low_20: {
    short: 'Swing low 20',
    full: 'The lowest price actually traded during the last 20 trading days — a floor the market has already defended once.\nUsed as a support anchor for the entry levels.',
  },
  bias_20: {
    short: 'Bias 20',
    full: 'How far the price sits above or below its own 20-day average, in %.\nStretched values tend to snap back.',
  },
  swing_high_20: {
    short: 'Swing high 20',
    full: 'The highest price actually traded during the last 20 trading days — a ceiling the market has already rejected once.\nUsed as a resistance anchor for the target.',
  },
  swing_low_60: {
    short: 'Swing low 60',
    full: 'The lowest price traded during the last 60 trading days — a deeper, older floor than the 20-day low.\nJoins the support candidates for the entry.',
  },
  swing_high_60: {
    short: 'Swing high 60',
    full: 'The highest price traded during the last 60 trading days — a wider resistance ceiling than the 20-day high.',
  },
  high_52w: {
    short: '52w high',
    full: 'The highest price of the loaded history (about a year) — the strongest resistance reference.',
  },
  low_52w: {
    short: '52w low',
    full: 'The lowest price of the loaded history (about a year).',
  },
  avg_volume_20: {
    short: 'Avg volume 20',
    full: 'Average daily trading volume over the last 20 trading days.\nUsed to judge whether a position could be exited in one day without moving the price.',
  },
  worst_day_pct_1y: {
    short: 'Worst price drop: 1y',
    full: 'The single worst day of the past year, close to close.\nUnit: percent, negative — e.g. -14.5 means that day lost 14.5%.',
    interp: 'Shows how far an overnight surprise (bad earnings, bad news) can jump straight past a stop-loss.',
  },
  worst_day_1y: {
    short: 'Worst day 1y',
    full: 'Retired field old runs still carry: the same statistic written as a fraction (-0.17 meaning -17%), and scanned over all loaded history rather than one year. New runs publish worst_day_pct_1y instead.',
  },
  worst_day_5pct: {
    short: 'Worst 5% day',
    full: 'Retired statistic old runs still carry: the daily drop only the worst 5% of days exceeded.',
  },
  score: {
    short: 'Tech score',
    full: 'Retired field old runs still carry: a code-computed 0-100 technical score. New runs omit it — handing the AI a finished verdict made it anchor on the number instead of reading the fields.',
  },

  // ---- technicals v2 groups + fields (2026-07-27; regrouped 2026-07-28) ----
  market: {
    short: 'Overall market',
    full: 'What the market as a whole is doing, and whether this stock is leading or lagging it.',
  },
  regime: {
    short: 'Benchmark: market',
    full: "Whether the overall market — not this stock — is healthy, judged on the benchmark index (S&P 500 for US stocks): is it above its 200-day average, and in the upper or lower half of its one-year range?\nValues: bullish / bearish / mixed (blank when this market has no benchmark wired).",
    interp: "Most stocks follow the market, so buying in a bearish market usually fails even when the stock's own chart looks good — demand stronger setups and smaller size.",
  },
  relative_strength: {
    short: 'Relative strength',
    full: 'Is this stock doing better or worse than the market itself?',
  },
  price: {
    short: 'Stock price',
    full: 'The current price and where it sits in its own recent history.',
  },
  weekly: {
    short: 'Weekly timeframe',
    full: 'The zoomed-out view (one bar = one week). It sets the direction — trades should only go this way.',
  },
  daily: {
    short: 'Daily timeframe',
    full: 'The zoomed-in view (one bar = one day) — used to time the entry and write the trade plan.',
  },
  volatility: {
    short: 'Volatility',
    full: 'How jumpy this stock is — the ruler stops and position sizes are measured with.',
  },
  volume: {
    short: 'Volume',
    full: 'How much is actually traded — can an order get in and out easily, and is a move backed by real buying?',
  },
  levels: {
    short: 'Levels',
    full: "Actual price levels from the stock's past turning points — where the entry, stop and target anchor.",
  },
  risk: {
    short: 'Risk',
    full: "How bad this stock's bad days actually get.",
  },
  bars_daily: {
    short: 'Daily bars',
    full: "How many days of price history were loaded (one 'bar' = one trading day).\nUnit: a count; the target is 300.",
    interp: 'Below about 253 (one trading year), the one-year fields only cover the history that exists.',
  },
  bars_weekly: {
    short: 'Weekly bars',
    full: 'How many weeks of history, built by combining the daily data.\nUnit: a count; the target is 60.',
    interp: 'With fewer than 60, the weekly trend read is shaky.',
  },
  rs_1m: {
    short: '1m return diff: stock vs market',
    full: "The stock's 1-month return minus the market's 1-month return: +5 means it beat the market by 5 points over the month.\nUnit: percentage points; usually between -20 and +20, with no hard limit.",
    interp: 'Positive = leading the market; negative = lagging it.',
  },
  rs_3m: {
    short: '3m return diff: stock vs market',
    full: "The stock's 3-month return minus the market's 3-month return: +5 means it beat the market by 5 points, -20 means it lost to it by 20.\nUnit: percentage points; usually between -30 and +30, with no hard limit.",
    interp: 'Positive = leading the market; negative = lagging it.',
  },
  rs_label: {
    short: 'Relative strength: stock',
    full: 'One-word verdict computed from the 1-month and 3-month return differences above: leader = beat the market over both; laggard = lost to it over both; neutral = mixed.',
    interp: 'Prefer longs in leaders — a laggard long needs an explicit catalyst from the other reports.',
  },
  chg_5d_pct: {
    short: '5d price change',
    full: 'How much the price moved over the last 5 trading days.\nUnit: percent; usually -15 to +15.',
    interp: 'A big jump means the cheap entry may already be gone.',
  },
  range_pct_1y: {
    short: 'Current price ranking: 1y range',
    full: "Where today's price sits inside its past-year range, shown as a position out of 100.\n0/100 = at the year's low, 100/100 = at the year's high.",
    interp: 'Above ~80/100 = strong but risky to chase; below ~20/100 = falling knife unless it is clearly bottoming.',
  },
  high_1y: {
    short: '1y highest price',
    full: "The highest price touched in the last year.\nUnit: the stock's currency.",
    interp: 'Prices often stall just below it — people who bought there are waiting to get out even. A target above it needs breakout logic, not pullback logic.',
  },
  low_1y: {
    short: '1y lowest price',
    full: "The lowest price touched in the last year — the floor of the one-year range.\nUnit: the stock's currency.",
    interp: 'How far the market has actually let this stock fall in a year.',
  },
  trend: {
    short: 'Trend: SMA + pivots',
    full: "Overall direction, from two independent checks that must agree: (1) is the price above or below its own moving averages (SMA), and (2) are the chart's recent peaks and dips (pivots) stepping higher or lower?\nValues: bullish / bearish / neutral (neutral = the two checks disagree).",
    interp: 'The direction filter for entries — trades should only go the way the weekly trend points, and daily pullback buys work best when both timeframes agree.',
  },
  sma_10w: {
    short: '10w SMA',
    full: "The average price of the last 10 weeks.\nUnit: the stock's currency.",
    interp: 'The medium-term trend line the weekly stretch is measured from; holding above it keeps a swing uptrend intact.',
  },
  stretch_10w_atr: {
    short: 'Diff: closing price vs 10w SMA',
    full: 'How far the price is above (+) or below (-) its 10-week average, measured in normal weekly moves (ATR units).\nRange: usually -4 to +4.',
    interp: 'Above ~+1.5 = stretched too far, wait; -0.5 to +1 in an uptrend = good dip-buy zone.',
  },
  sma_50: {
    short: '50d SMA',
    full: "The average price of the last 50 trading days.\nUnit: the stock's currency.",
    interp: 'Rising stocks often dip back to this line before continuing — the classic buy-the-dip level.',
  },
  stretch_50d_atr: {
    short: 'Diff: closing price vs 50d SMA',
    full: 'How far the price is above (+) or below (-) its 50-day average, in normal daily moves (ATR units).\nRange: usually -5 to +5.',
    interp: '-1 to +1 in an uptrend = good entry zone; above +3 = chasing.',
  },
  sma_200: {
    short: '200d SMA',
    full: "The average price of the last 200 trading days — the most-watched line in finance.\nUnit: the stock's currency.",
    interp: 'Price above it = long-term healthy; the line itself often acts as support or resistance, and below it longs are counter-trend.',
  },
  momentum: {
    short: 'Momentum',
    full: 'One-word verdict combining the RSI and MACD momentum gauges:\nstrong = pushing up hard; weak = pushing down; fading = price still high but the push is dying; basing = price still low but the push is building; neutral = neither.',
    interp: 'strong supports entries; fading warns the move is running out of fuel while price still looks fine; basing flags an early turn.',
  },
  atr_pct: {
    short: '14d ATR %',
    full: 'The typical daily move as a percent of the price — lets you compare a $10 stock with a $500 stock.\nUnit: percent; typically 1 to 6.',
    interp: 'Above ~6 = wild stock, consider trading smaller.',
  },
  atr_trend: {
    short: 'ATR trend',
    full: 'Is the daily jumpiness growing or shrinking versus about a month ago?\nValues: expanding / contracting / stable (±10% dead band).',
    interp: 'Expanding = widen stops and buy fewer shares; contracting = the stock is coiling up, a big move often follows.',
  },
  avg_vol_60d: {
    short: '60d avg volume',
    full: 'Average shares traded per day over about 3 months.\nUnit: shares (often millions).',
    interp: 'The liquidity baseline: tells you whether a position can get in and out without moving the price.',
  },
  avg_vol_5d: {
    short: '5d avg volume',
    full: 'Average shares traded per day over the last week.\nUnit: shares.',
    interp: 'The recent-activity read the volume ratio compares against the 3-month normal.',
  },
  vol_ratio_5_60: {
    short: 'Volume ratio: 5d/60d',
    full: "This week's average volume versus the 3-month normal.\nUnit: a ratio; usually 0.5 to 2, where 1.0 = normal.",
    interp: 'Above ~1.5 during a breakout = real interest confirms the move; below ~0.7 = the move is suspect.',
  },
  support_1: {
    short: 'Nearest support',
    full: "The nearest price BELOW today's where buyers stepped in before (a past dip-bottom).\nUnit: the stock's currency.\nBlank when the price sits at its lowest point in ~6 months — there is no past floor beneath it.",
    interp: 'A protective stop-loss belongs just below a level like this, not at a random percent.',
  },
  resistance_1: {
    short: 'Nearest resistance',
    full: "The nearest price ABOVE today's where sellers showed up before (a past peak).\nUnit: the stock's currency.\nBlank when the price sits at its highest point in ~6 months — there is no past ceiling above it.",
    interp: 'The first realistic profit target — expect selling there.',
  },
  typical_pullback_atr: {
    short: 'Typical price drop: 6m',
    full: "How deep this stock's normal dips have been over the last ~6 months (120 trading days) — from each local top down to the next local bottom — in normal daily moves (ATR units).\nRange: usually 1 to 5.",
    interp: 'If a stop is closer than this, ordinary wiggling will hit it even when the trade idea is right.',
  },

  // ---- fundamentals (v2 field list 2026-07-29; legacy keys kept for old stored runs) ----
  profile: {
    short: 'Profile',
    full: 'What kind of company this is — the peer group its numbers should be judged against.',
  },
  sector: {
    short: 'Sector',
    full: 'The company\'s sector classification (e.g. Technology).',
    interp: 'Margins, leverage and valuation only mean anything against industry peers; the sector also says which macro series matter most (oil for energy, the 10y yield for long-duration tech).',
  },
  industry: {
    short: 'Industry',
    full: 'The finer industry classification within the sector.',
    interp: 'The peer group this company\'s ratios should be compared against.',
  },
  earnings: {
    short: 'Earnings events',
    full: 'The report calendar and how this stock has actually behaved around reports — the single-stock event risk block.',
  },
  beats_4q: {
    short: 'Earnings beats (last 4)',
    full: 'How many of the last reported quarters came in at or above the analyst EPS estimate (e.g. 3/4).',
    interp: 'Consistent beaters get the benefit of the doubt into a report; habitual missers lose it.',
  },
  avg_surprise_pct_4q: {
    short: 'Avg earnings surprise (last 4)',
    full: 'Average gap between reported EPS and the analyst estimate over those quarters.\nUnit: percent.',
    interp: 'Says whether the company tends to clear the bar analysts set — not how the stock reacts; read it with the earnings-day move below.',
  },
  reaction_avg_abs_pct: {
    short: 'Typical earnings-day move (last 4)',
    full: 'Average size of the close-to-close move around the last few reports, ignoring direction.\nUnit: percent.',
    interp: 'The realized event risk: a stock that moves ±10% on earnings needs a different plan than one that moves ±2%.',
  },
  reaction_worst_pct: {
    short: 'Worst earnings-day drop (last 4)',
    full: 'The most negative close-to-close move around those reports.\nUnit: percent.',
    interp: 'How badly holding through a report has actually gone recently.',
  },
  eps_rev_90d_pct: {
    short: 'EPS estimate revision (90d)',
    full: 'Change in the analyst consensus EPS estimate for the current quarter versus 90 days ago.\nUnit: percent.',
    interp: 'Rising estimates tend to pull the price up over weeks; cuts are a headwind even on a good chart.',
  },
  ex_dividend_date: {
    short: 'Ex-dividend date',
    full: 'The next date the stock trades without its dividend; the price mechanically opens lower by roughly the dividend amount.',
    interp: 'A small scheduled gap-down that can clip a tight stop on a long.',
  },
  growth: {
    short: 'Growth',
    full: 'Quarterly growth from the latest SEC filings — the freshest read on whether the business is expanding.',
  },
  revenue_yoy_q: {
    short: 'Quarterly revenue growth (YoY)',
    full: 'Latest reported quarter\'s revenue versus the same quarter last year.\nUnit: percent.',
    interp: 'Positive and rising = an expanding business; the direction of change matters more than the level.',
  },
  revenue_growth_trend: {
    short: 'Revenue growth trend',
    full: 'Whether that growth rate sped up or slowed versus the previous quarter (±2 percentage-point dead band).\nValues: accelerating / slowing / steady.',
    interp: 'Acceleration is the classic fuel for multi-week runs; deceleration often ends them while growth is still positive.',
  },
  eps_yoy_q: {
    short: 'Quarterly EPS growth (YoY)',
    full: 'Latest reported quarter\'s earnings per share versus the same quarter last year.\nUnit: percent.',
    interp: 'Diverges from revenue growth when margins or the share count move — buybacks boost it, dilution drags it.',
  },
  eps_growth_trend: {
    short: 'EPS growth trend',
    full: 'Whether EPS growth sped up or slowed versus the previous quarter (±2 percentage-point dead band).\nValues: accelerating / slowing / steady.',
    interp: 'The market pays for the change in trajectory, not the level.',
  },
  profitability: {
    short: 'Profitability',
    full: 'How much of each dollar of revenue the company keeps, and whether the profits turn into real cash.',
  },
  gross_margin_pct: {
    short: 'Gross margin',
    full: '% of revenue left after the direct costs of making the product (latest fiscal year).',
    interp: 'High or rising = pricing power; falling = competition or cost pressure biting.',
  },
  operating_margin_pct: {
    short: 'Operating margin',
    full: '% of revenue left after running costs like salaries and marketing, before interest and taxes (latest fiscal year).',
    interp: 'The efficiency number the market judges at earnings; a trend break here moves the stock.',
  },
  roe_pct: {
    short: 'Return on equity',
    full: 'Yearly profit as a % of shareholders\' money — how efficiently the company uses investor capital.',
    interp: 'Sustained ~15%+ marks a quality business; very low or negative means the business burns capital.',
  },
  fcf: {
    short: 'Free cash flow',
    full: 'Cash actually generated after paying operating costs and equipment spending (trailing twelve months when the filings allow, else the latest fiscal year).\nUnit: USD.',
    interp: 'Positive and close to reported profit = the earnings are real; reported profits with negative cash flow is a red flag.',
  },
  balance_sheet: {
    short: 'Balance sheet',
    full: 'A snapshot of what the company owns vs. what it owes — its financial strength.',
  },
  current_ratio: {
    short: 'Current ratio',
    full: 'Short-term assets ÷ short-term debts (latest fiscal year).',
    interp: 'Above ~1.5 is comfortable; below 1 hints at a cash crunch, where bad news hits twice as hard.',
  },
  debt_to_equity: {
    short: 'Debt/Equity',
    full: 'Total debts ÷ shareholders\' money — how leveraged the company is.',
    interp: 'High leverage amplifies moves both ways and hurts most when rates are high; compare within the same industry.',
  },
  meta: {
    short: 'Report info',
    full: 'Which financial reports these numbers come from, and how fresh they are.',
  },
  entity_name: {
    short: 'Company',
    full: 'The registrant name on the SEC filings.',
    interp: 'Confirms the filings belong to the ticker being analyzed.',
  },
  period_end: {
    short: 'Annual period end',
    full: 'The fiscal year end the margins, ROE and balance-sheet ratios come from.',
    interp: 'Nearly a year old = treat those numbers as stale background.',
  },
  period_end_q: {
    short: 'Quarterly period end',
    full: 'The quarter end the quarterly growth fields come from.',
    interp: 'Right after an annual report the latest 10-Q can lag a full quarter — check this date before treating growth as fresh.',
  },
  basis: {
    short: 'Basis',
    full: 'The report types the numbers come from (10-K = the audited yearly filing, 10-Q = the quarterly filing).',
  },
  valuation: {
    short: 'Valuation',
    full: 'How expensive the stock is relative to its earnings and sales.',
  },
  pe_ttm: {
    short: 'Trailing P/E',
    full: 'Price-to-Earnings — share price ÷ the last 12 months\' earnings (Trailing Twelve Months). How many years of current profit you pay for the stock.',
    interp: 'High = big expectations already priced in, good news is needed just to hold the level; low = cheap, or the market expects decline.',
  },
  pe_forward: {
    short: 'Forward P/E',
    full: 'Share price ÷ the profit analysts expect over the next 12 months.',
    interp: 'Well below the trailing P/E = analysts expect growth; above it = expected shrinkage.',
  },
  ps_ttm: {
    short: 'P/S (trailing)',
    full: 'Price-to-Sales — total market value ÷ the last 12 months\' revenue.',
    interp: 'The valuation gauge for unprofitable names where P/E is meaningless.',
  },
  market_cap: {
    short: 'Market cap',
    full: 'Total market value of all the company\'s shares, in USD.',
    interp: 'Mega caps grind, small caps gap and squeeze; also sets what liquidity to expect.',
  },
  // Legacy fundamentals keys (old stored runs only; retired 2026-07-29).
  revenue_yoy_pct: {
    short: 'Revenue YoY %',
    full: 'Retired field old runs still carry: annual revenue growth vs. the prior fiscal year. New runs publish quarterly growth instead.',
  },
  net_income_yoy_pct: {
    short: 'Net income YoY %',
    full: 'Retired field old runs still carry: annual bottom-line profit growth vs. the prior fiscal year.',
  },
  eps_yoy_pct: {
    short: 'EPS YoY %',
    full: 'Retired field old runs still carry: annual earnings-per-share growth vs. the prior fiscal year.',
  },
  net_margin_pct: {
    short: 'Net margin %',
    full: 'Retired field old runs still carry: % of revenue left as final profit after everything. Mostly duplicated the operating margin plus one-off noise.',
  },
  cash: {
    short: 'Cash',
    full: 'Retired field old runs still carry: cash and cash-like holdings on hand, in USD. A raw dollar figure with no scale context.',
  },
  pb: {
    short: 'P/B',
    full: 'Retired field old runs still carry: share price ÷ accounting net worth per share. Only informative for banks and asset-heavy names.',
  },

  // ---- macro economy ----
  next_earnings_date: {
    short: 'Next earnings',
    full: 'The date of the next scheduled earnings report.',
    interp: 'A report inside the hold window is event risk: one announcement can gap the price past any stop — exit before it or size for it.',
  },
  days_until_earnings: {
    short: 'Days to earnings',
    full: 'Calendar days until the next scheduled earnings report.',
    interp: 'Small = the event risk is live now; the plan\'s earnings warning fires inside a week.',
  },
  region: {
    short: 'Region',
    full: 'Which economy these numbers describe.',
  },
  as_of: {
    short: 'As of',
    full: 'The date this block of data describes — lagged sources (macro series, short-interest reports) carry it so stale numbers are never mistaken for today\'s.',
    interp: 'Data older than a couple of sessions should not anchor a plan.',
  },
  rates: {
    short: 'Rates',
    full: 'Interest rates set by the central bank and the bond market.',
  },
  fed_funds_rate_pct: {
    short: 'Fed funds %',
    full: 'The US central bank’s base interest rate.\nHigher rates cool the economy and usually pressure stock prices.',
  },
  treasury_10y_pct: {
    short: '10Y yield %',
    full: 'Yield on 10-year US government bonds — the benchmark long-term interest rate.',
  },
  treasury_2y_pct: {
    short: '2Y yield %',
    full: 'Yield on 2-year US government bonds — tracks where markets expect rates to go soon.',
  },
  curve_10y_2y_pct: {
    short: '10Y−2Y spread',
    full: '10-year yield minus 2-year yield.\nBelow zero (an “inverted curve”) is a classic recession warning.',
  },
  inflation: {
    short: 'Inflation',
    full: 'How fast consumer prices are rising.',
  },
  cpi_yoy_pct: {
    short: 'CPI YoY %',
    full: 'Consumer Price Index — how much everyday prices rose vs. a year ago.',
  },
  labor: {
    short: 'Labor',
    full: 'Job-market health.',
  },
  unemployment_rate_pct: {
    short: 'Unemployment %',
    full: 'Share of the workforce without a job.',
  },
  markets: {
    short: 'Markets',
    full: 'Broad market stress gauges.',
  },
  vix: {
    short: 'VIX',
    full: 'The “fear index” — expected market turbulence implied by options prices.\nHigher = investors more nervous.',
  },
  wti_oil_usd: {
    short: 'WTI oil $',
    full: 'The US benchmark oil price, in USD per barrel.',
  },
  dollar_index_broad: {
    short: 'Dollar index',
    full: 'Strength of the US dollar against a basket of other currencies.',
  },
  observation_dates: {
    short: 'Data dates',
    full: 'The date of each underlying data point (some series update monthly, others daily).',
  },

  // ---- positioning ----
  short_interest: {
    short: 'Short interest',
    full: 'Shares sold short — bets that the price will fall. FINRA publishes this twice a month with roughly a two-week lag; see "As of" for the report date.',
  },
  short_pct_of_float: {
    short: 'Short % of float',
    full: 'Shorted shares as a percentage of the freely tradable shares (the float).\nAbove 10% is notable; above 20% is a heavily shorted, crowded-short stock.',
  },
  days_to_cover: {
    short: 'Days to cover',
    full: 'Shorted shares divided by average daily volume — how many days of normal trading short sellers would need to buy everything back.\nAbove 5 days makes a short squeeze easier.',
  },
  shares_short: {
    short: 'Shares short',
    full: 'Total number of shares currently sold short.',
  },
  change_vs_prior_month_pct: {
    short: 'Change vs prior %',
    full: 'Change in shares short versus the previous twice-monthly report — whether shorts are adding to their bets or covering.',
  },
  ownership: {
    short: 'Ownership',
    full: 'Who holds the stock — from quarterly 13F institutional filings (up to 45 days late) and the Yahoo summary.',
  },
  institutional_pct: {
    short: 'Institutional %',
    full: 'Percentage of shares held by institutions (funds, banks, insurers), per their quarterly 13F filings.\nVery high means the story is fully discovered; very low can mean undiscovered — or avoided.',
  },
  insider_pct: {
    short: 'Insider %',
    full: 'Percentage held by company insiders (executives, directors) — skin in the game, and shares locked away from daily trading.',
  },
  top10_institutions_pct: {
    short: 'Top-10 holders %',
    full: 'Combined stake of the ten largest institutional holders. A concentrated register moves hard if one big holder heads for the exit.',
  },
  float_shares: {
    short: 'Float',
    full: 'Shares actually available for public trading — total shares minus locked-up insider and strategic stakes.',
  },
  shares_outstanding: {
    short: 'Shares outstanding',
    full: 'Total number of shares the company has issued.',
  },
  insider_activity_6m: {
    short: 'Insider trades (6m)',
    full: 'Open-market buys and sells by executives and directors over the last six months, from SEC Form 4 filings. Awards, option exercises and gifts are excluded — only trades made with their own money count.',
  },
  buy_count: {
    short: 'Insider buys',
    full: 'Number of open-market insider purchases in the window.\nInsiders sell for many reasons but buy for only one — a cluster of buys is a strong signal.',
  },
  sell_count: {
    short: 'Insider sells',
    full: 'Number of open-market insider sales in the window.',
  },
  net_shares: {
    short: 'Net shares',
    full: 'Shares bought minus shares sold by insiders over the window.',
  },
  net_value_usd: {
    short: 'Net value ($)',
    full: 'Dollar value of insider buys minus sells over the window.',
  },
  options: {
    short: 'Options',
    full: 'Positioning in the options market over the nearest expirations — the freshest block here, updated daily.',
  },
  put_call_oi_ratio: {
    short: 'Put/Call OI',
    full: 'Outstanding put contracts divided by call contracts (open interest).\nAbove 1 means more downside bets than upside bets are being held.',
  },
  put_call_volume_ratio: {
    short: 'Put/Call volume',
    full: "Today's traded put volume divided by call volume — a faster-moving read than open interest.",
  },
  total_open_interest: {
    short: 'Total OI',
    full: 'Total outstanding option contracts (puts plus calls) over the covered expirations.',
  },
  expirations_covered: {
    short: 'Expirations',
    full: 'How many of the nearest option expiration dates these totals cover.',
  },
};

const zh: Record<string, MetricEntry> = {
  close: {
    short: '收盘价',
    full: '最近一个交易日的最后成交价。',
    interp: '本报告中所有距离都以它为基准。',
  },
  bars_count: { short: 'K线数', full: '本次计算使用了多少个交易日的历史数据。' },
  sma_20: {
    short: 'SMA 20',
    full: '20日简单移动平均线——最近20个交易日收盘价的平均值，用来过滤日常波动、观察短期趋势。',
  },
  sma_60: {
    short: 'SMA 60',
    full: '60日简单移动平均线——最近60个交易日收盘价的平均值，代表中期趋势。',
  },
  ema_12: { short: 'EMA 12', full: '12日指数移动平均线——与普通均线类似，但更看重近期价格。' },
  ema_26: { short: 'EMA 26', full: '26日指数移动平均线——较慢的加权均线，与 EMA 12 搭配使用。' },
  rsi_14: {
    short: 'RSI 14',
    full: '14日相对强弱指标——0到100的动量计。\n高于70通常代表过热（可能回调），低于30代表超卖（可能反弹）。',
  },
  macd: { short: 'MACD', full: '指数平滑异同均线——通过对比快、慢两条均线衡量趋势动量的指标。' },
  signal: { short: '信号线', full: 'MACD 线的均值。\nMACD 线上穿或下穿信号线是常见的买卖触发信号。' },
  histogram: { short: '柱状值', full: 'MACD 线减信号线。\n为正且扩大 = 上涨动量增强；为负 = 动量减弱。' },
  atr_14: {
    short: 'ATR 14',
    full: '14日平均真实波幅——日常价格波动的典型幅度（以货币计）。',
    interp: '止损距离和仓位大小的度量单位；以 ATR 计的距离在不同股票之间可以公平比较。',
  },
  volatility_pct: {
    short: '波动率 %',
    full: '典型单日波幅（ATR 14）占价格的百分比。\n超过约 4% 视为高波动——计划审查可能因此减仓或放宽止损。',
  },
  swing_low_20: {
    short: '20日低点',
    full: '最近20个交易日的最低成交价——市场已经防守过一次的价格底部，用作买入价位的支撑锚点。',
  },
  bias_20: { short: '乖离率 20', full: '价格偏离自身20日均线的百分比。\n偏离过大往往会回归。' },
  swing_high_20: {
    short: '20日高点',
    full: '最近20个交易日的最高成交价——市场已经拒绝过一次的价格顶部，用作目标价的阻力锚点。',
  },
  swing_low_60: {
    short: '60日低点',
    full: '最近60个交易日的最低成交价——比20日低点更深、更早的底部，参与买入价的支撑候选。',
  },
  swing_high_60: {
    short: '60日高点',
    full: '最近60个交易日的最高成交价——比20日高点更宽的阻力位。',
  },
  high_52w: { short: '52周高点', full: '已加载历史（约一年）中的最高价——最强的阻力参考。' },
  low_52w: { short: '52周低点', full: '已加载历史（约一年）中的最低价。' },
  avg_volume_20: {
    short: '20日均量',
    full: '最近20个交易日的平均成交量。\n用于判断仓位能否在一天内退出而不砸盘。',
  },
  worst_day_pct_1y: {
    short: '年内最差单日',
    full: '最近一个交易年度中最差的单日跌幅，以百分数表示。',
    interp: '跳空风险：隔夜坏消息实际能把价格越过止损打到多远。',
  },
  worst_day_1y: {
    short: '年内最差单日',
    full: '旧运行保留的已退役字段：同一统计量，但以小数表示（-0.17 表示 -17%），且扫描了全部已加载历史而非仅一年。新运行改用 worst_day_pct_1y。',
  },
  worst_day_5pct: {
    short: '最差5%单日',
    full: '旧运行保留的已退役统计：仅最差 5% 的交易日才会超过的单日跌幅。',
  },
  score: {
    short: '技术评分',
    full: '旧运行保留的已退役字段：由代码算出的 0-100 技术面总分。新运行不再输出——把现成结论交给 AI 会让它锚定这个数字，而不是自己读取各项指标。',
  },

  // ---- technicals v2 分组与字段（2026-07-27；2026-07-28 重新分组）----
  market: { short: '大盘环境', full: '整体市场的状态，以及个股相对大盘是领先还是落后。' },
  rs_1m: {
    short: '对比指数（1月）',
    full: '约1个月（21个交易日）内个股收益减基准指数收益，单位为百分点。',
    interp: '为正 = 跑赢大盘；为负 = 跑输大盘。',
  },
  low_1y: {
    short: '一年最低价',
    full: '过去一年的最低成交价——一年区间的下边界。',
    interp: '市场在一年里实际让这只股票跌到过的位置。',
  },
  avg_vol_5d: {
    short: '平均成交量（5日）',
    full: '最近5个交易日的日均成交股数。',
    interp: '量比中的近期活跃度读数，与60日基线对比。',
  },
  sma_10w: {
    short: '10周均线',
    full: '最近10周收盘价的平均值。',
    interp: '周线偏离度所参照的中期趋势线；守在其上方，波段上升趋势就仍然成立。',
  },
  regime: {
    short: '市场环境',
    full: '用基准指数（美股为标普500）判断大盘状态：是否高于其200日均线、处于一年区间的什么位置。\n取值：bullish / bearish / mixed。',
    interp: '多数个股跟随大盘：大盘下行时，无论个股图形多好，都应要求更强的形态、更小的仓位。',
  },
  relative_strength: { short: '相对强度', full: '同一窗口内个股收益减指数收益——个股是领先还是落后于大盘。' },
  price: { short: '价格', full: '当前价格及其在近期历史中的位置。' },
  weekly: { short: '周线时间框架', full: '拉远视角（每根K线一周）——决定方向判断；日线信号只应顺着它的方向开仓。' },
  daily: { short: '日线时间框架', full: '交易计划所用的时间框架（每根K线一天）——趋势、动量以及计划挂靠的价位。' },
  volatility: { short: '波动', full: '股票通常的波动幅度——止损与仓位大小的度量单位。' },
  volume: { short: '成交量', full: '交易活跃度——行情是否有真实参与支撑、订单能否顺利退出。' },
  levels: { short: '价位', full: '来自股票自身转折点的价位——买入、止损、目标价的锚点。' },
  risk: { short: '风险', full: '尾部特征——这只股票糟糕的日子究竟有多糟。' },
  bars_daily: {
    short: '日线数量',
    full: '已载入的交易日数量。',
    interp: '少于253（一个交易年）时，一年期字段只覆盖已有历史。',
  },
  bars_weekly: {
    short: '周线数量',
    full: '由日线合成的周线数量。',
    interp: '少于60时，周线结构判断不可靠。',
  },
  rs_3m: {
    short: '对比指数（3月）',
    full: '约3个月（63个交易日）内个股收益减基准指数收益，单位为百分点。',
    interp: '为正 = 跑赢大盘；为负 = 跑输大盘。',
  },
  rs_label: {
    short: '强弱标签',
    full: 'leader = 1个月和3个月都跑赢基准；laggard = 都跑输；否则 neutral。',
    interp: '做多优先选 leader；做多 laggard 需要其他报告给出明确催化剂。',
  },
  chg_5d_pct: {
    short: '涨跌幅（5日）',
    full: '最近5个交易日收盘价变化（%）。',
    interp: '涨幅过大意味着好的买点可能已经错过。',
  },
  range_pct_1y: {
    short: '一年区间位置',
    full: '收盘价在一年区间中的排位，以 X/100 表示：0/100 = 最低点，100/100 = 最高点。',
    interp: '约80/100以上 = 接近高点的强势（突破区，追高有风险）；约20/100以下 = 接近低点的弱势（接飞刀区，除非明确筑底）。',
  },
  high_1y: {
    short: '一年最高价',
    full: '过去一年的最高成交价。',
    interp: '最受关注的阻力位——目标价高于它需要按突破逻辑而非回调逻辑。',
  },
  trend: {
    short: '趋势',
    full: '由均线检查与转折点结构共同判定；两者一致才给出多/空方向，否则为中性。',
    interp: '入场的方向过滤器——交易只应顺着周线趋势的方向，日线回调买入在两个时间框架一致时效果最好。',
  },
  stretch_10w_atr: {
    short: '偏离10周线（ATR）',
    full: '收盘价距10周均线的距离，以周ATR为单位。',
    interp: '约+1.5以上 = 过度伸展，等回调；上升趋势中-0.5到+1 = 回调买入区。',
  },
  sma_50: {
    short: 'SMA 50',
    full: '50日简单移动平均线。',
    interp: '波段交易经典的回调支撑位——上涨中的股票常回踩这条线后再继续。',
  },
  stretch_50d_atr: {
    short: '偏离50日线（ATR）',
    full: '收盘价距50日均线的距离，以ATR为单位。',
    interp: '上升趋势中-1到+1 = 回调买入区；+3以上 = 过度伸展，属于追高。',
  },
  sma_200: {
    short: 'SMA 200',
    full: '200日简单移动平均线——金融市场最受关注的长期均线。',
    interp: '无论持仓周期长短都会成为支撑或阻力；价格在其下方时做多属于逆势。',
  },
  momentum: {
    short: '动量',
    full: '综合 RSI 与 MACD 的单一标签：strong / weak / fading（价格强但动量衰减）/ basing（价格弱但动量积聚）/ neutral。',
    interp: 'strong 支持入场；fading 提示价格看着还好但动力正在耗尽；basing 提示早期转势。',
  },
  atr_pct: {
    short: 'ATR %',
    full: '典型单日波幅占价格的百分比，可跨股票比较。',
    interp: '超过约6%属于高波动股——考虑缩小仓位。',
  },
  atr_trend: {
    short: 'ATR 趋势',
    full: '当前ATR对比20根K线之前（±10%缓冲带）：expanding / contracting / stable。',
    interp: 'expanding = 放宽止损、缩小仓位；contracting = 收敛，往往预示行情。',
  },
  avg_vol_60d: {
    short: '平均成交量（60日）',
    full: '最近60根K线的日均成交股数。',
    interp: '衡量订单规模的流动性基线——判断仓位能否顺利进出而不砸盘。',
  },
  vol_ratio_5_60: {
    short: '量比（5÷60）',
    full: '最近5根K线的均量除以60日均量。',
    interp: '突破时高于约1.5 = 有效；低于约0.7 = 存疑。',
  },
  support_1: {
    short: '支撑位 1',
    full: '收盘价下方最近的转折点低点。',
    interp: '止损应放在这类价位下方，而不是任意百分比处。',
  },
  resistance_1: {
    short: '阻力位 1',
    full: '收盘价上方最近的转折点高点。',
    interp: '第一目标价候选——预期那里会出现卖压。',
  },
  typical_pullback_atr: {
    short: '典型回调（ATR）',
    full: '最近几次完整回调（转折高点到随后的转折低点）深度的中位数，以ATR为单位。',
    interp: '止损距离小于它就落在正常波动之内——想法对了也会被震出去。',
  },

  // ---- fundamentals（v2 字段清单 2026-07-29；旧运行的字段保留在末尾）----
  profile: { short: '公司概况', full: '这是家什么样的公司——它的各项数据应该和哪个同行群体比较。' },
  sector: {
    short: '行业板块',
    full: '公司所属的板块分类（如科技）。',
    interp: '利润率、杠杆和估值只有和同行比较才有意义；板块也决定哪些宏观数据对它最重要（能源看油价、成长科技看10年期利率）。',
  },
  industry: {
    short: '细分行业',
    full: '板块内更细的行业分类。',
    interp: '这家公司的各项比率应该对照的同行群体。',
  },
  earnings: {
    short: '财报事件',
    full: '财报日程，以及这只股票在财报前后的实际表现——个股层面的事件风险。',
  },
  beats_4q: {
    short: '财报超预期次数（近4次）',
    full: '最近几个已公布季度中，实际每股收益达到或超过分析师预期的次数（如 3/4）。',
    interp: '持续超预期的公司在财报前更容易被市场善待；习惯性不及预期的则相反。',
  },
  avg_surprise_pct_4q: {
    short: '平均财报意外幅度（近4次）',
    full: '这些季度中实际每股收益与分析师预期的平均差距。\n单位：百分比。',
    interp: '只说明公司是否常越过分析师定的门槛——不代表股价如何反应；请结合下方的财报日波动一起看。',
  },
  reaction_avg_abs_pct: {
    short: '财报日典型波动（近4次）',
    full: '最近几次财报前后收盘价到收盘价的平均波动幅度（不分方向）。\n单位：百分比。',
    interp: '真实的事件风险：财报日常动±10%的股票和只动±2%的股票需要完全不同的计划。',
  },
  reaction_worst_pct: {
    short: '财报日最差跌幅（近4次）',
    full: '这些财报前后最糟的一次收盘到收盘跌幅。\n单位：百分比。',
    interp: '最近抱着仓位过财报实际最惨的结果。',
  },
  eps_rev_90d_pct: {
    short: 'EPS 预期调整（90天）',
    full: '分析师对当前季度每股收益的一致预期相比90天前的变化。\n单位：百分比。',
    interp: '预期上调往往在数周内推高股价；下调则是逆风，图形再好也一样。',
  },
  ex_dividend_date: {
    short: '除息日',
    full: '股票开始不含下一期股息交易的日期；股价会机械性低开约等于股息的幅度。',
    interp: '一个已排期的小幅跳空低开，可能击中做多的紧止损。',
  },
  growth: { short: '成长性', full: '取自最新 SEC 季报的季度增长——业务是否在扩张的最新读数。' },
  revenue_yoy_q: {
    short: '季度营收同比',
    full: '最新已公布季度的营业收入与去年同季相比的增长率。\n单位：百分比。',
    interp: '为正且上升 = 业务在扩张；变化的方向比水平更重要。',
  },
  revenue_growth_trend: {
    short: '营收增速趋势',
    full: '该增长率相比上一季度是加速还是减速（±2个百分点缓冲带）。\n取值：accelerating / slowing / steady。',
    interp: '增速加快是数周级行情的经典燃料；增速放缓即使仍在增长也常终结行情。',
  },
  eps_yoy_q: {
    short: '季度 EPS 同比',
    full: '最新已公布季度的每股收益与去年同季相比的增长率。\n单位：百分比。',
    interp: '当利润率或股本变化时会与营收增速背离——回购推高它，增发稀释它。',
  },
  eps_growth_trend: {
    short: 'EPS 增速趋势',
    full: 'EPS 增速相比上一季度是加速还是减速（±2个百分点缓冲带）。\n取值：accelerating / slowing / steady。',
    interp: '市场付钱买的是轨迹的变化，不是水平。',
  },
  profitability: { short: '盈利能力', full: '每一元收入能留下多少，以及账面利润是否变成了真金白银。' },
  gross_margin_pct: {
    short: '毛利率',
    full: '扣除直接生产成本后剩余的收入占比（最新财年）。',
    interp: '高或上升 = 定价权；下降 = 竞争或成本压力显现。',
  },
  operating_margin_pct: {
    short: '营业利润率',
    full: '再扣除工资、营销等运营成本后剩余的占比（最新财年，未计利息和税）。',
    interp: '市场在财报时最看重的效率指标；这里的趋势拐点会直接影响股价。',
  },
  roe_pct: {
    short: '净资产收益率',
    full: '年度利润占股东投入资金的百分比——衡量公司使用股东资本的效率。',
    interp: '长期保持约15%以上是优质企业的标志；极低或为负说明生意在烧钱。',
  },
  fcf: {
    short: '自由现金流',
    full: '扣除运营成本和设备开支后实际产生的现金（财报允许时为最近十二个月，否则为最新财年）。\n单位：美元。',
    interp: '为正且接近账面利润 = 盈利是真的；账面盈利但现金流为负是危险信号。',
  },
  balance_sheet: { short: '资产负债', full: '公司拥有什么、欠什么的快照——财务稳健度。' },
  current_ratio: {
    short: '流动比率',
    full: '短期资产÷短期负债（最新财年）。',
    interp: '约1.5以上比较从容；低于1提示现金紧张——坏消息来时伤害加倍。',
  },
  debt_to_equity: {
    short: '产权比率',
    full: '总负债÷股东权益——公司的杠杆程度。',
    interp: '高杠杆双向放大波动，利率高时伤害最大；应与同行业比较。',
  },
  meta: { short: '报表信息', full: '这些数字来自哪些财务报告，以及数据有多新。' },
  entity_name: {
    short: '公司名称',
    full: 'SEC 备案中的注册公司名称。',
    interp: '用来确认财报数据确实属于所分析的这只股票。',
  },
  period_end: {
    short: '年报报告期',
    full: '利润率、ROE 和资产负债比率所来自的财年截止日期。',
    interp: '接近一年前的数据只能当作陈旧的背景信息。',
  },
  period_end_q: {
    short: '季报报告期',
    full: '季度增长字段所来自的季度截止日期。',
    interp: '年报刚发布后，最新季报可能滞后整整一个季度——把增长当作新鲜数据前先看这个日期。',
  },
  basis: {
    short: '报表类型',
    full: '数据来源的报表类型（10-K = 经审计的年报，10-Q = 季报）。',
  },
  valuation: { short: '估值', full: '股价相对盈利和销售额贵不贵。' },
  pe_ttm: {
    short: '市盈率（TTM）',
    full: '股价÷过去12个月的每股盈利（TTM = 最近十二个月）——买下当前利润需要付几年的价钱。',
    interp: '高 = 大量预期已计入价格，好消息只够维持现状；低 = 便宜，或市场预期业绩下滑。',
  },
  pe_forward: {
    short: '预期市盈率',
    full: '股价÷分析师预期的未来12个月盈利。',
    interp: '明显低于静态市盈率 = 分析师预期增长；高于它 = 预期萎缩。',
  },
  ps_ttm: {
    short: '市销率（TTM）',
    full: '总市值÷过去12个月的营业收入。',
    interp: '市盈率失效的亏损公司用它来衡量估值。',
  },
  market_cap: {
    short: '总市值',
    full: '公司全部股份的市场总价值（美元）。',
    interp: '巨头走势平缓，小盘股容易跳空和轧空；也决定了流动性的量级。',
  },
  // 旧运行保留的已退役字段（2026-07-29 退役）。
  revenue_yoy_pct: { short: '营收同比 %', full: '旧运行保留的已退役字段：年报营收同比增速。新运行改用季度增长。' },
  net_income_yoy_pct: { short: '净利同比 %', full: '旧运行保留的已退役字段：年报净利润同比增速。' },
  eps_yoy_pct: { short: 'EPS 同比 %', full: '旧运行保留的已退役字段：年报每股收益同比增速。' },
  net_margin_pct: { short: '净利率 %', full: '旧运行保留的已退役字段：最终利润占收入的比例。与营业利润率高度重复，另含一次性损益噪音。' },
  cash: { short: '现金', full: '旧运行保留的已退役字段：持有的现金及等价物（美元）。缺乏规模参照的原始数字。' },
  pb: { short: '市净率', full: '旧运行保留的已退役字段：股价÷每股账面净资产。只对银行等重资产行业有参考意义。' },

  next_earnings_date: {
    short: '下次财报',
    full: '下一次财报的预定日期。',
    interp: '持仓窗口内的财报属于事件风险：一次公告就可能让价格跳空越过任何止损——要么提前离场，要么按它调整仓位。',
  },
  days_until_earnings: {
    short: '距财报天数',
    full: '距下一次财报的日历天数。',
    interp: '数字小 = 事件风险已经临近；一周以内会触发交易计划的财报警告。',
  },
  region: { short: '地区', full: '这些数据描述的是哪个经济体。' },
  as_of: { short: '数据日期', full: '本组数据对应的日期——宏观序列、空头持仓报告等滞后数据都带上它，避免把旧数据当成今天的。' },
  rates: { short: '利率', full: '由央行和债券市场决定的利率水平。' },
  fed_funds_rate_pct: {
    short: '联邦基金利率 %',
    full: '美国央行的基准利率。\n利率越高，经济降温，通常也会压制股价。',
  },
  treasury_10y_pct: { short: '10年期收益率 %', full: '10年期美国国债收益率——长期利率的基准。' },
  treasury_2y_pct: { short: '2年期收益率 %', full: '2年期美国国债收益率——反映市场对短期利率走向的预期。' },
  curve_10y_2y_pct: {
    short: '10Y−2Y 利差',
    full: '10年期减2年期收益率。\n低于零（“倒挂”）是经典的衰退预警信号。',
  },
  inflation: { short: '通胀', full: '消费者物价上涨的速度。' },
  cpi_yoy_pct: { short: 'CPI 同比 %', full: '消费者物价指数——日常物价相比一年前上涨了多少。' },
  labor: { short: '就业', full: '就业市场的健康状况。' },
  unemployment_rate_pct: { short: '失业率 %', full: '劳动人口中没有工作的比例。' },
  markets: { short: '市场情绪', full: '衡量市场整体紧张程度的指标。' },
  vix: {
    short: 'VIX',
    full: '“恐慌指数”——期权价格隐含的预期市场波动。\n越高说明投资者越紧张。',
  },
  wti_oil_usd: { short: 'WTI 油价 $', full: '美国基准原油价格（美元/桶）。' },
  dollar_index_broad: { short: '美元指数', full: '美元相对一篮子其他货币的强弱。' },
  observation_dates: {
    short: '数据日期',
    full: '每个数据点各自的日期（有的按月更新，有的按日更新）。',
  },

  // ---- positioning ----
  short_interest: {
    short: '空头持仓',
    full: '被卖空的股份——押注股价下跌的仓位。FINRA 每月发布两次，约有两周滞后；报告日期见「数据日期」。',
  },
  short_pct_of_float: {
    short: '做空占流通比 %',
    full: '空头股数占可自由交易股份（流通盘）的百分比。\n超过 10% 值得注意；超过 20% 属于重度做空、空头拥挤。',
  },
  days_to_cover: {
    short: '回补天数',
    full: '空头股数除以日均成交量——空头按正常成交量全部买回需要多少天。\n超过 5 天更容易发生轧空（逼空）。',
  },
  shares_short: { short: '空头股数', full: '当前被卖空的股份总数。' },
  change_vs_prior_month_pct: {
    short: '环比变化 %',
    full: '相对上一期（半月一次）报告的空头股数变化——空头是在加仓还是回补。',
  },
  ownership: {
    short: '持股结构',
    full: '谁持有这只股票——来自季度 13F 机构申报（最多滞后 45 天）和 Yahoo 摘要。',
  },
  institutional_pct: {
    short: '机构持股 %',
    full: '机构（基金、银行、保险等）按季度 13F 申报的持股比例。\n极高说明故事已被充分发掘；极低可能是尚未被发现——也可能是被回避。',
  },
  insider_pct: {
    short: '内部人持股 %',
    full: '公司内部人（高管、董事）的持股比例——既是利益绑定，也是锁定在日常交易之外的筹码。',
  },
  top10_institutions_pct: {
    short: '前十大机构 %',
    full: '前十大机构股东的合计持股。筹码集中时，任何一家大股东离场都会带来剧烈波动。',
  },
  float_shares: {
    short: '流通股',
    full: '实际可公开交易的股份——总股本减去内部人及战略持股等锁定部分。',
  },
  shares_outstanding: { short: '总股本', full: '公司已发行的股份总数。' },
  insider_activity_6m: {
    short: '内部人交易（6个月）',
    full: '过去六个月高管和董事在公开市场的买卖，来自 SEC Form 4 申报。不含股权授予、期权行权和赠与——只统计用自己的钱做的交易。',
  },
  buy_count: {
    short: '内部人买入笔数',
    full: '窗口期内内部人公开市场买入的笔数。\n内部人卖出的理由很多，买入的理由只有一个——集中买入是强信号。',
  },
  sell_count: { short: '内部人卖出笔数', full: '窗口期内内部人公开市场卖出的笔数。' },
  net_shares: { short: '净买入股数', full: '窗口期内内部人买入股数减去卖出股数。' },
  net_value_usd: { short: '净买入金额（$）', full: '窗口期内内部人买入金额减去卖出金额。' },
  options: {
    short: '期权持仓',
    full: '最近几个到期日的期权市场持仓——本报告里最新鲜的一组数据，每日更新。',
  },
  put_call_oi_ratio: {
    short: 'Put/Call 持仓比',
    full: '未平仓认沽合约除以认购合约（持仓量）。\n大于 1 说明持有的看跌押注多于看涨押注。',
  },
  put_call_volume_ratio: {
    short: 'Put/Call 成交比',
    full: '当日认沽成交量除以认购成交量——比持仓量变化更快的读数。',
  },
  total_open_interest: {
    short: '总未平仓量',
    full: '覆盖到期日内的期权未平仓合约总数（认沽加认购）。',
  },
  expirations_covered: {
    short: '覆盖到期日数',
    full: '以上合计覆盖了最近多少个期权到期日。',
  },
};

export function metricEntry(key: string, language: UiLanguage): MetricEntry | null {
  const table = language === 'en' ? en : zh;
  return table[key] ?? null;
}
