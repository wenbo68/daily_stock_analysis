import type { UiLanguage } from './uiText';

// Vocabulary for tiered-analysis dimension payloads (backend keys stay
// snake_case on purpose — see api/tiered.ts). Each entry has the compact
// label shown in the table (`short`) and the plain-language definition
// shown in the hover/click popup (`full`). Entries may also carry
// `interp` — how to read the number as a trader; when present the popup
// renders "Meaning: … / Interpretation: …" as two blocks (owner format
// 2026-07-29). Labels follow the field names in TODO.md; tooltip text is
// written in everyday words per the owner's plain-English rule
// (2026-07-29). Unknown keys fall back to the raw key with no popup.
export interface MetricEntry {
  short: string;
  full: string;
  interp?: string;
}

const en: Record<string, MetricEntry> = {
  // ---- technicals ----
  close: {
    short: 'Closing price',
    full: "The last price the stock traded at on the most recent trading day.\nUnit: the stock's own currency (USD for US stocks).",
    interp: 'The starting point — every distance in this report (to supports, averages, targets) is measured from this price.',
  },
  bars_count: {
    short: 'Bars',
    full: 'How many trading days of price history were used for these calculations.',
  },
  sma_20: {
    short: 'SMA 20',
    full: 'The average closing price of the last 20 trading days ("SMA" = simple moving average).\nAveraging smooths out day-to-day noise so the short-term direction is easier to see.',
  },
  sma_60: {
    short: 'SMA 60',
    full: 'The average closing price of the last 60 trading days — the medium-term trend line.',
  },
  ema_12: {
    short: 'EMA 12',
    full: 'An average of the last 12 days of prices where the newest days count the most ("EMA" = exponential moving average).',
  },
  ema_26: {
    short: 'EMA 26',
    full: 'The same idea over 26 days — a slower-moving average used together with EMA 12.',
  },
  rsi_14: {
    short: '14d RSI',
    full: 'A 0-to-100 gauge of how fast the price has been rising or falling lately ("RSI" = relative strength index, 14 days).\nAbove 70 = rose unusually fast; below 30 = fell unusually fast; near 50 = calm.',
    interp: 'Careful: in strong uptrends it can sit above 70 for weeks — a high reading alone is not a sell signal.',
  },
  macd: {
    short: 'MACD',
    full: 'A momentum gauge built by comparing a fast price average with a slow one ("MACD" = moving average convergence divergence).\nWhen the fast average pulls ahead, upward push is building.',
  },
  signal: {
    short: 'Signal',
    full: 'A smoothed average of the MACD line.\nThe MACD line crossing above or below it is a common buy/sell trigger.',
  },
  histogram: {
    short: 'Histogram',
    full: 'MACD line minus signal line.\nPositive and growing = upward push building; negative = the push is fading.',
  },
  atr_14: {
    short: '14d ATR',
    full: "The size of a normal day's price move for this stock ('ATR' = average true range, 14 days).\nUnit: the stock's currency — an ATR of $19 means a typical day moves the price about $19.",
    interp: 'The ruler for stops and position sizes: distances measured in ATRs compare fairly between calm stocks and jumpy ones.',
  },
  volatility_pct: {
    short: 'Volatility %',
    full: 'The normal daily move (14d ATR) as a percent of the price.\nAbove ~4% counts as a jumpy, high-volatility stock — the plan review may shrink the position or widen the stop.',
  },
  swing_low_20: {
    short: 'Swing low 20',
    full: 'The lowest price actually traded in the last 20 trading days — a floor buyers have already defended once.\nUsed as a support anchor for the entry price.',
  },
  bias_20: {
    short: 'Bias 20',
    full: 'How far the price sits above or below its own 20-day average, in %.\nWhen it stretches far from the average, it tends to snap back toward it.',
  },
  swing_high_20: {
    short: 'Swing high 20',
    full: 'The highest price actually traded in the last 20 trading days — a ceiling sellers have already defended once.\nUsed as a resistance anchor for the target.',
  },
  swing_low_60: {
    short: 'Swing low 60',
    full: 'The lowest price traded in the last 60 trading days — a deeper, older floor than the 20-day low.\nJoins the support candidates for the entry.',
  },
  swing_high_60: {
    short: 'Swing high 60',
    full: 'The highest price traded in the last 60 trading days — a wider ceiling than the 20-day high.',
  },
  high_52w: {
    short: '52w high',
    full: 'The highest price in the loaded history (about a year) — the strongest ceiling reference.',
  },
  low_52w: {
    short: '52w low',
    full: 'The lowest price in the loaded history (about a year).',
  },
  avg_volume_20: {
    short: 'Avg volume 20',
    full: 'The average number of shares traded per day over the last 20 trading days.\nUsed to judge whether a position could be sold in one day without pushing the price down.',
  },
  worst_day_pct_1y: {
    short: 'Worst price drop: 1y',
    full: "The single worst one-day drop of the past year, measured from one day's closing price to the next.\nUnit: percent, negative — e.g. -14.5 means that day lost 14.5%.",
    interp: 'Shows how far one overnight surprise (bad earnings, bad news) can jump the price straight past a stop-loss.',
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
    full: 'What the market as a whole is doing, and whether this stock is leading it or lagging behind it.',
  },
  regime: {
    short: 'Benchmark: market',
    full: 'Is the overall market — not this stock — healthy? Judged on the benchmark index (S&P 500 for US stocks): is the index above its own 200-day average price, and is it in the upper or lower half of its one-year range?\nValues: bullish / bearish / mixed (blank when this market has no benchmark set up).',
    interp: "Most stocks follow the market. Buying in a bearish market usually fails even when this stock's own chart looks good — demand a stronger setup and use a smaller position.",
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
    full: 'How jumpy this stock is — the ruler that stops and position sizes are measured with.',
  },
  volume: {
    short: 'Volume',
    full: 'How much is actually traded — can an order get in and out easily, and is a move backed by real buying?',
  },
  levels: {
    short: 'Levels',
    full: "Actual prices from the stock's past turning points — where the entry, stop and target anchor.",
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
    full: "The stock's return over the last month minus the market's return over the same month: +5 means it beat the market by 5 points.\nUnit: percentage points; usually between -20 and +20.",
    interp: 'Positive = leading the market; negative = lagging it.',
  },
  rs_3m: {
    short: '3m return diff: stock vs market',
    full: "The stock's return over the last 3 months minus the market's return over the same window: +5 means it beat the market by 5 points, -20 means it lost to it by 20.\nUnit: percentage points; usually between -30 and +30.",
    interp: 'Positive = leading the market; negative = lagging it.',
  },
  rs_label: {
    short: 'Relative strength: stock',
    full: 'A one-word verdict from the two numbers above: leader = beat the market over both the 1-month and 3-month windows; laggard = lost to it over both; neutral = mixed.',
    interp: 'Prefer buying leaders — buying a laggard needs a clear reason from the other reports.',
  },
  chg_5d_pct: {
    short: '5d price change',
    full: 'How much the price moved over the last 5 trading days.\nUnit: percent; usually -15 to +15.',
    interp: 'A big jump means the cheap entry may already be gone.',
  },
  range_pct_1y: {
    short: 'Current price ranking: 1y',
    full: "Where today's price sits inside its past-year range, as a position out of 100.\n0/100 = at the year's low, 100/100 = at the year's high.",
    interp: 'Above ~80/100 = strong but risky to chase; below ~20/100 = a falling knife unless it is clearly bottoming out.',
  },
  high_1y: {
    short: '1y highest price',
    full: "The highest price touched in the last year.\nUnit: the stock's currency.",
    interp: 'Prices often stall just below the old high — people who bought there are waiting to sell once they break even. A target above it assumes the stock pushes into new-high ground, which is a harder trade than buying a dip.',
  },
  low_1y: {
    short: '1y lowest price',
    full: "The lowest price touched in the last year — the floor of the one-year range.\nUnit: the stock's currency.",
    interp: 'How far the market has actually let this stock fall in a year.',
  },
  trend: {
    short: 'Trend: SMA + pivots',
    full: "The overall direction, from two independent checks that must agree: (1) is the price above or below its own average lines (SMA), and (2) are the chart's recent peaks and dips ('pivots') stepping higher or lower?\nValues: bullish / bearish / neutral (neutral = the two checks disagree).",
    interp: 'The direction filter: trades should only go the way the weekly trend points, and dip-buying works best when the daily and weekly trends agree.',
  },
  sma_10w: {
    short: '10w SMA',
    full: "The average price of the last 10 weeks.\nUnit: the stock's currency.",
    interp: 'The medium-term trend line; holding above it keeps a swing uptrend intact.',
  },
  stretch_10w_atr: {
    short: 'Diff: closing price vs 10w SMA',
    full: 'How far the price is above (+) or below (-) its 10-week average, measured in normal weekly moves (ATR units).\nRange: usually -4 to +4.',
    interp: 'Above ~+1.5 = stretched too far, wait for a dip; -0.5 to +1 in an uptrend = a good dip-buy zone.',
  },
  sma_50: {
    short: '50d SMA',
    full: "The average price of the last 50 trading days.\nUnit: the stock's currency.",
    interp: 'Rising stocks often dip back to this line before continuing — the classic buy-the-dip level.',
  },
  stretch_50d_atr: {
    short: 'Diff: closing price vs 50d SMA',
    full: 'How far the price is above (+) or below (-) its 50-day average, in normal daily moves (ATR units).\nRange: usually -5 to +5.',
    interp: '-1 to +1 in an uptrend = a good entry zone; above +3 = chasing.',
  },
  sma_200: {
    short: '200d SMA',
    full: "The average price of the last 200 trading days — the most-watched line in finance.\nUnit: the stock's currency.",
    interp: 'Price above it = long-term healthy; the line itself often acts as a floor or ceiling. Below it, buying is fighting the long-term tide.',
  },
  momentum: {
    short: 'Momentum',
    full: 'A one-word verdict combining the RSI and MACD gauges:\nstrong = pushing up hard; weak = pushing down; fading = price still high but the push is dying; basing = price still low but the push is building; neutral = neither.',
    interp: 'strong supports new buys; fading warns the move is running out of fuel while the price still looks fine; basing flags an early turn upward.',
  },
  atr_pct: {
    short: '14d ATR %',
    full: 'The normal daily move as a percent of the price — lets you compare a $10 stock with a $500 stock.\nUnit: percent; typically 1 to 6.',
    interp: 'Above ~6 = a wild stock; consider a smaller position.',
  },
  atr_trend: {
    short: 'ATR trend',
    full: 'Is the daily jumpiness growing or shrinking compared with about a month ago?\nValues: expanding / contracting / stable (changes within ±10% count as stable).',
    interp: 'Expanding = widen the stop and buy fewer shares; contracting = the stock is coiling up, and a big move often follows.',
  },
  avg_vol_60d: {
    short: '60d avg volume',
    full: 'The average number of shares traded per day over about 3 months.\nUnit: shares (often millions).',
    interp: 'The liquidity baseline: whether a position can get in and out without moving the price.',
  },
  avg_vol_5d: {
    short: '5d avg volume',
    full: 'The average number of shares traded per day over the last week.\nUnit: shares.',
    interp: 'The recent-activity read that the volume ratio compares against the 3-month normal.',
  },
  vol_ratio_5_60: {
    short: 'Volume ratio: 5d/60d',
    full: "This week's average volume versus the 3-month normal.\nUnit: a ratio; usually 0.5 to 2, where 1.0 = normal.",
    interp: 'Above ~1.5 while the price pushes through a ceiling = real interest confirms the move; below ~0.7 = the move is suspect.',
  },
  support_1: {
    short: 'Nearest support',
    full: "The nearest price BELOW today's where buyers stepped in before (a past dip-bottom).\nUnit: the stock's currency.\nBlank when the price is at its lowest point in ~6 months — there is no past floor beneath it.",
    interp: 'A protective stop-loss belongs just below a level like this, not at a random percent.',
  },
  resistance_1: {
    short: 'Nearest resistance',
    full: "The nearest price ABOVE today's where sellers showed up before (a past peak).\nUnit: the stock's currency.\nBlank when the price is at its highest point in ~6 months — there is no past ceiling above it.",
    interp: 'The first realistic profit target — expect selling there.',
  },
  typical_pullback_atr: {
    short: 'Typical price drop: 6m',
    full: "How deep this stock's normal dips have been over the last ~6 months — from each local top down to the next local bottom — measured in normal daily moves (ATR units).\nRange: usually 1 to 5.",
    interp: 'If a stop is closer than this, ordinary wiggling will hit it even when the trade idea is right.',
  },

  // ---- fundamentals (v2 field list 2026-07-29; labels follow TODO.md; legacy keys kept for old stored runs) ----
  profile: {
    short: 'Profile',
    full: 'What kind of company this is — which group of similar companies its numbers should be judged against.',
  },
  sector: {
    short: 'Sector',
    full: "The broad group of companies this one belongs to (e.g. Technology, Energy).\nFetched from Yahoo Finance, which picks it from a fixed standard list — it is not made up per company.",
    interp: 'Margins, debt and valuation only mean something compared against similar companies. The sector also says which big-picture numbers matter most: oil prices for energy names, interest rates for growth tech.',
  },
  industry: {
    short: 'Industry',
    full: 'The finer group inside the sector (e.g. Semiconductors inside Technology). Also fetched from a fixed list.',
    interp: "The exact peer group this company's numbers should be compared against.",
  },
  earnings: {
    short: 'Earnings events',
    full: "The company's report calendar and how the stock has actually behaved around past reports — the single-stock event risk.",
  },
  beats_4q: {
    short: 'Earnings beats (last 4)',
    full: 'Out of the last 4 quarterly reports, how many times profit came in at or above what analysts expected (e.g. 3/4).',
    interp: 'Companies that consistently beat expectations get the benefit of the doubt going into a report; habitual missers lose it.',
  },
  avg_surprise_pct_4q: {
    short: 'Avg earnings surprise (last 4)',
    full: 'On average, how far above or below the analyst expectation the reported profit landed, across those reports.\nUnit: percent.',
    interp: 'Says whether the company tends to clear the bar analysts set — not how the stock reacts. Read it together with the earnings-day move below.',
  },
  reaction_avg_abs_pct: {
    short: 'Typical earnings-day move (last 4)',
    full: 'How big the stock\'s move around each of the last few reports actually was, on average, ignoring direction (measured from the closing price before the report to the closing price after).\nUnit: percent.',
    interp: 'The real event risk: a stock that routinely moves ±10% on earnings needs a different plan than one that moves ±2%.',
  },
  reaction_worst_pct: {
    short: 'Worst earnings-day drop (last 4)',
    full: 'The single worst drop around those same reports.\nUnit: percent, negative.',
    interp: 'How badly holding through a report has actually gone recently.',
  },
  eps_rev_90d_pct: {
    short: 'EPS estimate revision (90d)',
    full: "Whether analysts have been raising or cutting their profit forecast for the current quarter — the change in the average forecast versus 90 days ago.\nUnit: percent.",
    interp: 'Rising forecasts tend to pull the price up over weeks; cuts are a headwind even when the chart looks good.',
  },
  ex_dividend_date: {
    short: 'Ex-dividend date',
    full: 'The date the stock starts trading without its next dividend payment. That morning the price mechanically opens lower by roughly the dividend amount.',
    interp: 'A small, scheduled gap down that can clip a tight stop on a long position.',
  },
  growth: {
    short: 'Growth',
    full: 'Quarterly growth from the latest official SEC filings — the freshest read on whether the business is expanding.',
  },
  revenue_yoy_q: {
    short: 'Quarterly revenue YoY',
    full: 'The latest quarter\'s sales compared with the same quarter last year ("YoY" = year over year).\nUnit: percent.',
    interp: 'Positive and rising = an expanding business; the direction of change matters more than the level.',
  },
  revenue_growth_trend: {
    short: 'Revenue growth trend',
    full: 'Whether that sales growth sped up or slowed compared with the quarter before.\nValues: accelerating / slowing / steady (changes smaller than 2 percentage points count as steady).',
    interp: 'Speeding-up growth is the classic fuel for multi-week rallies; slowing growth often ends them even while growth is still positive.',
  },
  eps_yoy_q: {
    short: 'Quarterly EPS YoY',
    full: 'The latest quarter\'s profit per share ("EPS" = earnings per share) compared with the same quarter last year.\nUnit: percent.',
    interp: 'Can differ from sales growth when margins or the share count change — share buybacks boost it, issuing new shares drags it.',
  },
  eps_growth_trend: {
    short: 'EPS growth trend',
    full: 'Whether profit-per-share growth sped up or slowed versus the quarter before.\nValues: accelerating / slowing / steady (same 2-point buffer).',
    interp: 'The market pays for the change in direction, not the level.',
  },
  profitability: {
    short: 'Profitability',
    full: 'How much of each dollar of sales the company keeps, and whether the profit turns into real cash.',
  },
  gross_margin_pct: {
    short: 'Gross margin',
    full: 'The percent of each sales dollar left after the direct cost of making the product (latest fiscal year).',
    interp: 'High or rising = the company can charge premium prices; falling = competition or rising costs are biting.',
  },
  operating_margin_pct: {
    short: 'Operating margin',
    full: 'The percent of sales left after all the costs of running the business — salaries, marketing, rent — but before interest and taxes (latest fiscal year).',
    interp: 'The efficiency number the market judges at earnings; a break in its trend moves the stock.',
  },
  roe_pct: {
    short: 'ROE',
    full: "Return on equity — the year's profit as a percent of the shareholders' money tied up in the business.",
    interp: 'Staying around 15% or higher marks a quality business; very low or negative means the business burns money.',
  },
  fcf: {
    short: 'Free cash flow',
    full: 'The cash the company actually generated after paying its running costs and equipment spending. Covers the last 12 months when the filings allow it, otherwise the latest fiscal year.\nUnit: USD.',
    interp: 'Positive and close to reported profit = the profit is real. Reported profit with negative cash flow is a red flag.',
  },
  balance_sheet: {
    short: 'Balance sheet',
    full: 'What the company owns versus what it owes — its financial strength.',
  },
  current_ratio: {
    short: 'Current ratio',
    full: "Short-term assets divided by short-term bills — can the company pay what's due within a year (latest fiscal year)?",
    interp: 'Above about 1.5 is comfortable; below 1 hints at a cash crunch, where bad news hits twice as hard.',
  },
  debt_to_equity: {
    short: 'Debt to equity',
    full: "Everything the company owes compared with the shareholders' money — how much it runs on borrowed money.",
    interp: 'Heavy borrowing makes moves bigger both ways and hurts most when interest rates are high; compare it against companies in the same industry.',
  },
  meta: {
    short: 'Report info',
    full: 'Which financial reports these numbers come from, and how fresh they are.',
  },
  entity_name: {
    short: 'Company',
    full: 'The company name on the official SEC filings.',
    interp: 'Confirms the filings really belong to the ticker being analyzed.',
  },
  period_end: {
    short: 'Annual period end',
    full: 'The end date of the fiscal year the margins, ROE and balance-sheet numbers come from.',
    interp: 'If this is nearly a year old, treat those numbers as stale background, not fresh news.',
  },
  period_end_q: {
    short: 'Quarterly period end',
    full: 'The end date of the quarter the quarterly growth numbers come from.',
    interp: 'Right after an annual report, the latest quarterly filing can lag a full quarter — check this date before treating the growth numbers as fresh.',
  },
  basis: {
    short: 'Basis',
    full: 'The report types behind the numbers: 10-K = the audited yearly filing, 10-Q = the quarterly filing, both filed with the SEC (the US markets regulator).',
  },
  valuation: {
    short: 'Valuation',
    full: "How expensive the stock is compared with the company's profit and sales.",
  },
  pe_ttm: {
    short: 'Trailing P/E',
    full: 'The share price divided by the last 12 months of profit per share ("P/E" = price to earnings). Roughly: how many years of current profit you pay for the stock.',
    interp: 'High = big expectations already in the price, so good news is needed just to hold the level; low = cheap, or the market expects decline.',
  },
  pe_forward: {
    short: 'Forward P/E',
    full: 'The share price divided by the profit analysts expect over the NEXT 12 months.',
    interp: 'Well below the trailing P/E = analysts expect profit to grow; above it = they expect it to shrink.',
  },
  ps_ttm: {
    short: 'P/S',
    full: 'Price to sales — the company\'s total market value divided by the last 12 months of sales.',
    interp: 'The valuation gauge for unprofitable companies, where P/E means nothing.',
  },
  market_cap: {
    short: 'Market cap',
    full: "The total value of all the company's shares.\nUnit: USD.",
    interp: 'Giant companies grind; small ones jump and squeeze harder. Also sets how much trading liquidity to expect.',
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

  // ---- earnings-event fields shared with the plan warnings ----
  next_earnings_date: {
    short: 'Next earnings',
    full: 'The date the company next reports its quarterly results.',
    interp: 'A report while you hold the stock means the price can jump straight past your stop overnight — exit before it, or size the position for it.',
  },
  days_until_earnings: {
    short: 'Days until earnings',
    full: 'How many days from today until that report (computed from the date).',
    interp: "A small number = the event risk is live now; a big number = a free window to trade in. The plan's earnings warning fires within a week of the report.",
  },

  // ---- macro economy ----
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
    full: '最近一个交易日的最后成交价。\n单位：股票自身的货币（美股为美元）。',
    interp: '一切的起点——本报告中所有距离（到支撑、均线、目标价）都从这个价格量起。',
  },
  bars_count: { short: 'K线数', full: '本次计算使用了多少个交易日的历史数据。' },
  sma_20: {
    short: 'SMA 20',
    full: '最近20个交易日收盘价的平均值（SMA = 简单移动平均线）。\n取平均能滤掉日常噪音，让短期方向更容易看清。',
  },
  sma_60: {
    short: 'SMA 60',
    full: '最近60个交易日收盘价的平均值——中期趋势线。',
  },
  ema_12: { short: 'EMA 12', full: '最近12天价格的加权平均，越新的日子权重越大（EMA = 指数移动平均线）。' },
  ema_26: { short: 'EMA 26', full: '同样的算法放到26天——较慢的均线，与 EMA 12 搭配使用。' },
  rsi_14: {
    short: 'RSI 14',
    full: '衡量近期价格涨跌快慢的0到100仪表（RSI = 相对强弱指标，14天）。\n高于70 = 涨得异常快；低于30 = 跌得异常快；接近50 = 平静。',
    interp: '注意：强势上涨中它可以在70上方停留数周——单看读数高不是卖出信号。',
  },
  macd: {
    short: 'MACD',
    full: '通过对比一条快均线和一条慢均线得到的动量仪表。\n快线甩开慢线时，说明上涨的推力在积累。',
  },
  signal: { short: '信号线', full: 'MACD 线再取一次平均。\nMACD 线上穿或下穿它是常见的买卖触发信号。' },
  histogram: { short: '柱状值', full: 'MACD 线减信号线。\n为正且扩大 = 上涨推力增强；为负 = 推力衰减。' },
  atr_14: {
    short: 'ATR 14',
    full: '这只股票平常一天的波动幅度（ATR = 平均真实波幅，14天）。\n单位：股票的货币——ATR 为 $19 表示正常一天价格大约动 $19。',
    interp: '止损距离和仓位大小的尺子：用 ATR 度量的距离，在温和股票和暴躁股票之间可以公平比较。',
  },
  volatility_pct: {
    short: '波动率 %',
    full: '正常单日波幅（14日ATR）占价格的百分比。\n超过约 4% 算高波动股——计划审查可能因此减仓或放宽止损。',
  },
  swing_low_20: {
    short: '20日低点',
    full: '最近20个交易日实际成交过的最低价——买方已经防守过一次的底部。\n用作买入价的支撑锚点。',
  },
  bias_20: { short: '乖离率 20', full: '价格偏离自身20日均线的百分比。\n偏离过大往往会向均线回归。' },
  swing_high_20: {
    short: '20日高点',
    full: '最近20个交易日实际成交过的最高价——卖方已经防守过一次的顶部。\n用作目标价的阻力锚点。',
  },
  swing_low_60: {
    short: '60日低点',
    full: '最近60个交易日的最低成交价——比20日低点更深、更早的底部，参与买入价的支撑候选。',
  },
  swing_high_60: {
    short: '60日高点',
    full: '最近60个交易日的最高成交价——比20日高点更宽的顶部。',
  },
  high_52w: { short: '52周高点', full: '已加载历史（约一年）中的最高价——最强的顶部参考。' },
  low_52w: { short: '52周低点', full: '已加载历史（约一年）中的最低价。' },
  avg_volume_20: {
    short: '20日均量',
    full: '最近20个交易日平均每天成交的股数。\n用于判断仓位能否在一天内卖出而不把价格砸下去。',
  },
  worst_day_pct_1y: {
    short: '年内最差单日',
    full: '过去一年最糟糕的单日跌幅，按前一天收盘价到当天收盘价计算。\n单位：百分比，负数——如 -14.5 表示那天跌了 14.5%。',
    interp: '说明一次隔夜坏消息（差财报、坏新闻）实际能把价格越过止损打到多远。',
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
  market: { short: '大盘环境', full: '整体市场处于什么状态，这只股票是领先大盘还是落后于大盘。' },
  rs_1m: {
    short: '对比大盘（1月）',
    full: '这只股票最近一个月的收益减去大盘同期收益：+5 表示跑赢大盘5个百分点。\n单位：百分点；通常在 -20 到 +20 之间。',
    interp: '为正 = 领先大盘；为负 = 落后大盘。',
  },
  low_1y: {
    short: '一年最低价',
    full: '过去一年触及的最低价——一年区间的地板。\n单位：股票的货币。',
    interp: '市场在一年里实际让这只股票跌到过的位置。',
  },
  avg_vol_5d: {
    short: '5日均量',
    full: '最近一周平均每天成交的股数。\n单位：股。',
    interp: '量比中的近期活跃度读数，用来和3个月的正常水平对比。',
  },
  sma_10w: {
    short: '10周均线',
    full: '最近10周价格的平均值。\n单位：股票的货币。',
    interp: '中期趋势线；守在它上方，波段上升趋势就还成立。',
  },
  regime: {
    short: '大盘状态',
    full: '整体市场（不是这只股票）健康吗？用基准指数（美股为标普500）判断：指数是否在自己200日均价上方、处于一年区间的上半段还是下半段。\n取值：bullish（多头）/ bearish（空头）/ mixed（混合）；该市场未接入基准时留空。',
    interp: '多数个股跟着大盘走。大盘转空时，就算这只股票自己的图形再好，买入也多半失败——要求更强的形态、用更小的仓位。',
  },
  relative_strength: { short: '相对强度', full: '这只股票的表现比大盘本身好还是差？' },
  price: { short: '股价', full: '当前价格，以及它在自身近期历史中的位置。' },
  weekly: { short: '周线时间框架', full: '拉远的视角（一根K线=一周）。它决定方向——交易只应顺着它的方向做。' },
  daily: { short: '日线时间框架', full: '拉近的视角（一根K线=一天）——用来把握买点、撰写交易计划。' },
  volatility: { short: '波动', full: '这只股票有多蹦跶——止损和仓位大小用它做尺子。' },
  volume: { short: '成交量', full: '实际交易有多活跃——订单能否轻松进出，行情背后有没有真金白银。' },
  levels: { short: '价位', full: '来自股票过去转折点的真实价格——买入、止损、目标价的锚点。' },
  risk: { short: '风险', full: '这只股票糟糕的日子究竟有多糟。' },
  bars_daily: {
    short: '日线数量',
    full: '已载入多少天的价格历史（一根“K线”=一个交易日）。\n单位：个数；目标是300。',
    interp: '少于约253（一个交易年）时，一年期字段只覆盖已有的历史。',
  },
  bars_weekly: {
    short: '周线数量',
    full: '由日线数据合成的周线数量。\n单位：个数；目标是60。',
    interp: '少于60时，周线趋势的判断不太可靠。',
  },
  rs_3m: {
    short: '对比大盘（3月）',
    full: '这只股票最近3个月的收益减去大盘同期收益：+5 表示跑赢5个百分点，-20 表示跑输20个百分点。\n单位：百分点；通常在 -30 到 +30 之间。',
    interp: '为正 = 领先大盘；为负 = 落后大盘。',
  },
  rs_label: {
    short: '个股相对强弱',
    full: '由上面两个数字得出的一词结论：leader（领先者）= 1个月和3个月都跑赢大盘；laggard（落后者）= 都跑输；neutral = 混合。',
    interp: '优先买领先者——买落后者需要其他报告给出明确的理由。',
  },
  chg_5d_pct: {
    short: '5日涨跌幅',
    full: '最近5个交易日价格变动了多少。\n单位：百分比；通常在 -15 到 +15。',
    interp: '涨幅太大意味着便宜的买点可能已经错过。',
  },
  range_pct_1y: {
    short: '当前价格排位：1年',
    full: '今天的价格在过去一年区间里的位置，按满分100表示。\n0/100 = 一年最低点，100/100 = 一年最高点。',
    interp: '约80/100以上 = 强势但追高有风险；约20/100以下 = 除非明确在筑底，否则是接飞刀。',
  },
  high_1y: {
    short: '一年最高价',
    full: '过去一年触及的最高价。\n单位：股票的货币。',
    interp: '价格常在旧高点下方停滞——当年在那里买入的人正等着解套卖出。目标价定在它上方，等于假设股价能闯进新高区，那比逢低买入更难。',
  },
  trend: {
    short: '趋势：均线+转折点',
    full: '整体方向，由两个必须一致的独立检查得出：（1）价格在自己的均线上方还是下方；（2）图上近期的高点和低点在抬高还是降低。\n取值：bullish / bearish / neutral（neutral = 两个检查不一致）。',
    interp: '方向过滤器：交易只应顺着周线趋势的方向做，日线逢低买入在两个时间框架一致时效果最好。',
  },
  stretch_10w_atr: {
    short: '收盘价与10周均线的距离',
    full: '价格在10周均线上方（+）或下方（−）多远，用正常单周波动（ATR）作单位。\n范围：通常 -4 到 +4。',
    interp: '约+1.5以上 = 拉得太远，等回调；上升趋势中 -0.5 到 +1 = 不错的逢低买入区。',
  },
  sma_50: {
    short: '50日均线',
    full: '最近50个交易日价格的平均值。\n单位：股票的货币。',
    interp: '上涨中的股票常回踩这条线后再继续——经典的逢低买入位。',
  },
  stretch_50d_atr: {
    short: '收盘价与50日均线的距离',
    full: '价格在50日均线上方（+）或下方（−）多远，用正常单日波动（ATR）作单位。\n范围：通常 -5 到 +5。',
    interp: '上升趋势中 -1 到 +1 = 不错的买入区；+3 以上 = 追高。',
  },
  sma_200: {
    short: '200日均线',
    full: '最近200个交易日价格的平均值——金融市场最受关注的一条线。\n单位：股票的货币。',
    interp: '价格在它上方 = 长期健康；这条线本身常充当地板或天花板。价格在它下方时买入，是在逆着长期大潮。',
  },
  momentum: {
    short: '动量',
    full: '综合 RSI 与 MACD 的一词结论：\nstrong = 猛力上推；weak = 向下压；fading = 价格还高但推力在消失；basing = 价格还低但推力在积累；neutral = 都不明显。',
    interp: 'strong 支持买入；fading 警告价格看着还行但燃料快耗尽；basing 提示可能正在早期转势向上。',
  },
  atr_pct: {
    short: 'ATR %',
    full: '正常单日波动占价格的百分比——让 $10 的股票能和 $500 的股票比较。\n单位：百分比；通常 1 到 6。',
    interp: '超过约6 = 很暴躁的股票，考虑用更小的仓位。',
  },
  atr_trend: {
    short: 'ATR 趋势',
    full: '和大约一个月前相比，日常波动在变大还是变小？\n取值：expanding（扩大）/ contracting（收缩）/ stable（±10%以内算稳定）。',
    interp: '扩大 = 放宽止损、少买一些；收缩 = 股票在蓄力，之后常有大动作。',
  },
  avg_vol_60d: {
    short: '60日均量',
    full: '约3个月内平均每天成交的股数。\n单位：股（常以百万计）。',
    interp: '流动性基线：判断仓位能否顺利进出而不影响价格。',
  },
  vol_ratio_5_60: {
    short: '量比：5日/60日',
    full: '本周平均成交量和3个月正常水平的比值。\n单位：比率；通常 0.5 到 2，1.0 = 正常。',
    interp: '价格突破天花板时高于约1.5 = 真实买盘确认行情；低于约0.7 = 这波行情存疑。',
  },
  support_1: {
    short: '最近支撑位',
    full: '今天价格下方最近的、买方曾经进场的价位（过去的一个回调底部）。\n单位：股票的货币。\n当价格处于约6个月来的最低点时留空——下方已没有过去的地板。',
    interp: '保护性止损应放在这类价位的下方一点，而不是随便选个百分比。',
  },
  resistance_1: {
    short: '最近阻力位',
    full: '今天价格上方最近的、卖方曾经出现的价位（过去的一个高点）。\n单位：股票的货币。\n当价格处于约6个月来的最高点时留空——上方已没有过去的天花板。',
    interp: '第一个现实的止盈目标——预计那里会出现卖压。',
  },
  typical_pullback_atr: {
    short: '典型回调深度：6个月',
    full: '最近约6个月里，这只股票正常回调的深度——从每个局部顶点跌到随后的局部底部——用正常单日波动（ATR）作单位。\n范围：通常 1 到 5。',
    interp: '止损比它还近的话，正常的来回晃动就会把你震出去，哪怕交易思路是对的。',
  },

  // ---- fundamentals（v2 字段清单 2026-07-29；标签对齐 TODO.md；旧运行的字段保留在末尾）----
  profile: { short: '公司概况', full: '这是家什么样的公司——它的数字应该和哪一群同类公司比较。' },
  sector: {
    short: '行业板块',
    full: '公司所属的大类（如科技、能源）。\n取自 Yahoo Finance，从固定的标准清单里选出——不是随意编写的。',
    interp: '利润率、负债和估值只有跟同类公司比才有意义。板块还决定哪些大环境数字对它最重要：能源公司看油价，成长型科技看利率。',
  },
  industry: {
    short: '细分行业',
    full: '板块内更细的分类（如科技板块里的半导体）。同样取自固定清单。',
    interp: '这家公司的数字应该对照的确切同行群体。',
  },
  earnings: {
    short: '财报事件',
    full: '公司的财报日程，以及股价在过去财报前后的真实表现——个股层面的事件风险。',
  },
  beats_4q: {
    short: '财报超预期次数（近4次）',
    full: '最近4次季报中，利润达到或超过分析师预期的次数（如 3/4）。',
    interp: '持续超预期的公司在财报前会得到市场的信任加分；习惯性不及预期的则相反。',
  },
  avg_surprise_pct_4q: {
    short: '平均财报意外幅度（近4次）',
    full: '这些财报中，实际利润平均比分析师预期高出或低出多少。\n单位：百分比。',
    interp: '只说明公司是否常越过分析师定的门槛——不代表股价怎么反应。请和下面的财报日波动一起看。',
  },
  reaction_avg_abs_pct: {
    short: '财报日典型波动（近4次）',
    full: '最近几次财报前后股价实际动了多大，取平均、不分方向（按财报前的收盘价到财报后的收盘价计算）。\n单位：百分比。',
    interp: '真实的事件风险：财报日常动±10%的股票和只动±2%的股票，需要完全不同的计划。',
  },
  reaction_worst_pct: {
    short: '财报日最差跌幅（近4次）',
    full: '这几次财报前后最糟的一次下跌。\n单位：百分比，负数。',
    interp: '最近抱着仓位过财报，实际最惨的结果是什么样。',
  },
  eps_rev_90d_pct: {
    short: 'EPS 预期调整（90天）',
    full: '分析师最近在上调还是下调本季度的利润预测——平均预测值相比90天前的变化。\n单位：百分比。',
    interp: '预测上调往往在数周内推高股价；下调是逆风，图形再好也一样。',
  },
  ex_dividend_date: {
    short: '除息日',
    full: '股票开始不带下一期股息交易的日期。那天早上，价格会机械性地低开大约股息的金额。',
    interp: '一个已排好日期的小幅跳空低开，可能击中做多的紧止损。',
  },
  growth: { short: '成长性', full: '取自最新 SEC 官方季报的季度增长——业务是否在扩张的最新读数。' },
  revenue_yoy_q: {
    short: '季度营收同比',
    full: '最新季度的销售额与去年同一季度相比的增长率（同比 = 和去年同期比）。\n单位：百分比。',
    interp: '为正且上升 = 业务在扩张；变化的方向比数字本身更重要。',
  },
  revenue_growth_trend: {
    short: '营收增速趋势',
    full: '这个销售增速与上一季度相比是加快了还是放慢了。\n取值：accelerating（加速）/ slowing（放缓）/ steady（变化不到2个百分点算平稳）。',
    interp: '增速加快是数周级行情的经典燃料；增速放缓即使仍在增长，也常终结行情。',
  },
  eps_yoy_q: {
    short: '季度 EPS 同比',
    full: '最新季度的每股利润（EPS = 每股收益）与去年同一季度相比的增长率。\n单位：百分比。',
    interp: '当利润率或股本变化时会和营收增速不同——回购推高它，增发新股拖累它。',
  },
  eps_growth_trend: {
    short: 'EPS 增速趋势',
    full: '每股利润的增速与上一季度相比是加快还是放慢。\n取值：accelerating / slowing / steady（同样的2个百分点缓冲）。',
    interp: '市场付钱买的是方向的变化，不是水平。',
  },
  profitability: { short: '盈利能力', full: '每一元销售额公司能留下多少，以及账面利润有没有变成真金白银。' },
  gross_margin_pct: {
    short: '毛利率',
    full: '每一元销售额中，扣掉直接生产成本后剩下的比例（最新财年）。',
    interp: '高或上升 = 公司能卖出溢价；下降 = 竞争或成本压力在啃食利润。',
  },
  operating_margin_pct: {
    short: '营业利润率',
    full: '再扣掉运营开支——工资、营销、房租——之后剩下的销售额比例，未计利息和税（最新财年）。',
    interp: '市场在财报时最看重的效率指标；它的趋势一旦拐弯，股价会有反应。',
  },
  roe_pct: {
    short: 'ROE',
    full: '净资产收益率——全年利润占股东投入资金的百分比。',
    interp: '长期保持约15%以上是优质企业的标志；极低或为负说明这门生意在烧钱。',
  },
  fcf: {
    short: '自由现金流',
    full: '公司付完运营开销和设备投入后，实际赚到手的现金。财报数据允许时覆盖最近12个月，否则为最新财年。\n单位：美元。',
    interp: '为正且接近账面利润 = 利润是真的。账面盈利但现金流为负，是危险信号。',
  },
  balance_sheet: { short: '资产负债', full: '公司拥有什么、欠什么——它的财务实力。' },
  current_ratio: {
    short: '流动比率',
    full: '短期资产除以短期账单——公司付得起一年内到期的钱吗（最新财年）？',
    interp: '约1.5以上比较从容；低于1提示现金紧张——这种时候坏消息的伤害会加倍。',
  },
  debt_to_equity: {
    short: '产权比率',
    full: '公司欠的所有钱和股东投入资金的比值——公司有多依赖借来的钱运转。',
    interp: '高负债让涨跌都被放大，利率高的时候伤害最大；要和同行业公司比较。',
  },
  meta: { short: '报表信息', full: '这些数字来自哪些财务报告，以及数据有多新。' },
  entity_name: {
    short: '公司名称',
    full: 'SEC 官方备案上的公司名称。',
    interp: '用来确认这些财报数据确实属于正在分析的这只股票。',
  },
  period_end: {
    short: '年报报告期',
    full: '利润率、ROE 和资产负债数字所来自的财年截止日期。',
    interp: '如果已经接近一年前，就把那些数字当作陈旧的背景信息，而不是新消息。',
  },
  period_end_q: {
    short: '季报报告期',
    full: '季度增长数字所来自的季度截止日期。',
    interp: '年报刚发布后，最新季报可能滞后整整一个季度——把增长当作新鲜数据前先看这个日期。',
  },
  basis: {
    short: '报表类型',
    full: '数字背后的报表类型：10-K = 经审计的年报，10-Q = 季报，都是向 SEC（美国证券监管机构）提交的官方文件。',
  },
  valuation: { short: '估值', full: '相对公司的利润和销售额，这只股票贵不贵。' },
  pe_ttm: {
    short: '市盈率（TTM）',
    full: '股价除以过去12个月的每股利润（P/E = 市盈率）。粗略地说：买下当前利润要付几年的价钱。',
    interp: '高 = 大量预期已经在价格里，好消息只够维持现状；低 = 便宜，或市场预期业绩下滑。',
  },
  pe_forward: {
    short: '预期市盈率',
    full: '股价除以分析师预期的未来12个月利润。',
    interp: '明显低于静态市盈率 = 分析师预期利润增长；高于它 = 预期萎缩。',
  },
  ps_ttm: {
    short: '市销率',
    full: '市销率——公司总市值除以过去12个月的销售额。',
    interp: '亏损公司的估值尺子——那种情况下市盈率没有意义。',
  },
  market_cap: {
    short: '总市值',
    full: '公司全部股份的总价值。\n单位：美元。',
    interp: '巨头走势平缓；小公司跳空和轧空更猛。也决定了能指望多少交易流动性。',
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
    full: '公司下一次公布季度业绩的日期。',
    interp: '持仓期间有财报，意味着价格可能一夜之间跳空越过你的止损——要么提前离场，要么按它调整仓位。',
  },
  days_until_earnings: {
    short: '距财报天数',
    full: '从今天到那次财报还有多少天（由日期算出）。',
    interp: '数字小 = 事件风险已经临近；数字大 = 一段可以放心交易的窗口。距财报一周以内会触发交易计划的财报警告。',
  },
  region: { short: '地区', full: '这些数据描述的是哪个经济体。' },
  as_of: {
    short: '数据日期',
    full: '本组数据对应的日期——宏观序列、空头持仓报告等滞后数据都带上它，避免把旧数据当成今天的。',
    interp: '超过两三个交易日的数据不应作为计划的主要依据。',
  },
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
