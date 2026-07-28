import type { UiLanguage } from './uiText';

// Vocabulary for tiered-analysis dimension payloads (backend keys stay
// snake_case on purpose — see api/tiered.ts). Each entry has the compact
// label shown in the table (`short`) and the plain-language definition
// shown in the hover/click popup (`full`). Unknown keys fall back to the
// raw key with no popup.
export interface MetricEntry {
  short: string;
  full: string;
}

const en: Record<string, MetricEntry> = {
  // ---- technicals ----
  close: {
    short: 'Closing price',
    full: "The last traded price of the most recent trading day — every distance in this report is measured from here.\nUnit: the stock's own currency (USD for US stocks).",
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
    full: "Average True Range (14 days) — the typical size of one day's price move.\nUnit: the stock's currency; e.g. an ATR of $19 means a normal day moves the price about $19.\nThis is the ruler stops and position sizes are measured with.",
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
    full: 'The single worst day of the past year, close to close.\nUnit: percent, negative — e.g. -14.5 means that day lost 14.5%.\nShows how far an overnight surprise (bad earnings, bad news) can jump straight past a stop-loss.',
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
    full: "Whether the overall market — not this stock — is healthy, judged on the benchmark index (S&P 500 for US stocks): is it above its 200-day average, and in the upper or lower half of its one-year range?\nValues: bullish / bearish / mixed (blank when this market has no benchmark wired).\nMost stocks follow the market, so buying in a bearish market usually fails even when the stock's own chart looks good.",
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
    full: "How many days of price history were loaded (one 'bar' = one trading day).\nUnit: a count; the target is 300. Below about 253 (one trading year), the one-year fields only cover the history that exists.",
  },
  bars_weekly: {
    short: 'Weekly bars',
    full: 'How many weeks of history, built by combining the daily data.\nUnit: a count; the target is 60. With fewer, the weekly trend read is shaky.',
  },
  rs_1m: {
    short: '1m return diff: stock vs market',
    full: "The stock's 1-month return minus the market's 1-month return: +5 means it beat the market by 5 points over the month.\nUnit: percentage points; usually between -20 and +20, with no hard limit.",
  },
  rs_3m: {
    short: '3m return diff: stock vs market',
    full: "The stock's 3-month return minus the market's 3-month return: +5 means it beat the market by 5 points, -20 means it lost to it by 20.\nUnit: percentage points; usually between -30 and +30, with no hard limit.",
  },
  rs_label: {
    short: 'Relative strength: stock',
    full: 'One-word verdict: leader = beat the market over both 1 and 3 months (good); laggard = lost to it over both (avoid); neutral = mixed.\nComputed from the 1-month and 3-month return differences above.',
  },
  chg_5d_pct: {
    short: '5d price change',
    full: 'How much the price moved over the last 5 trading days.\nUnit: percent; usually -15 to +15.\nA big jump means the cheap entry may already be gone.',
  },
  range_pct_1y: {
    short: 'Current price ranking: 1y range',
    full: "Where today's price sits inside its past-year range, shown as a position out of 100.\n0/100 = at the year's low, 100/100 = at the year's high.\nAbove ~80/100 = strong but risky to chase; below ~20/100 = falling knife unless it is clearly bottoming.",
  },
  high_1y: {
    short: '1y highest price',
    full: "The highest price touched in the last year.\nUnit: the stock's currency.\nPrices often stall just below it — people who bought there are waiting to get out even.",
  },
  low_1y: {
    short: '1y lowest price',
    full: "The lowest price touched in the last year — the floor of the one-year range.\nUnit: the stock's currency.",
  },
  trend: {
    short: 'Trend: SMA + pivots',
    full: "Overall direction, from two independent checks that must agree: (1) is the price above or below its own moving averages (SMA), and (2) are the chart's recent peaks and dips (pivots) stepping higher or lower?\nValues: bullish / bearish / neutral (neutral = the two checks disagree).",
  },
  sma_10w: {
    short: '10w SMA',
    full: "The average price of the last 10 weeks.\nUnit: the stock's currency.\nThe medium-term trend line the weekly stretch below is measured from.",
  },
  stretch_10w_atr: {
    short: 'Diff: closing price vs 10w SMA',
    full: "How far the price is above (+) or below (-) its 10-week average, measured in normal weekly moves (ATR units).\nRange: usually -4 to +4.\nAbove ~+1.5 = stretched too far, wait; -0.5 to +1 in an uptrend = good dip-buy zone.",
  },
  sma_50: {
    short: '50d SMA',
    full: "The average price of the last 50 trading days.\nUnit: the stock's currency.\nRising stocks often dip back to this line before continuing — the classic buy-the-dip level.",
  },
  stretch_50d_atr: {
    short: 'Diff: closing price vs 50d SMA',
    full: 'How far the price is above (+) or below (-) its 50-day average, in normal daily moves (ATR units).\nRange: usually -5 to +5.\n-1 to +1 in an uptrend = good entry zone; above +3 = chasing.',
  },
  sma_200: {
    short: '200d SMA',
    full: "The average price of the last 200 trading days — the most-watched line in finance.\nUnit: the stock's currency.\nPrice above it = long-term healthy; the line itself often acts as support or resistance.",
  },
  momentum: {
    short: 'Momentum',
    full: 'One-word verdict combining the RSI and MACD momentum gauges:\nstrong = pushing up hard; weak = pushing down; fading = price still high but the push is dying; basing = price still low but the push is building; neutral = neither.',
  },
  atr_pct: {
    short: '14d ATR %',
    full: 'The typical daily move as a percent of the price — lets you compare a $10 stock with a $500 stock.\nUnit: percent; typically 1 to 6.\nAbove ~6 = wild stock, consider trading smaller.',
  },
  atr_trend: {
    short: 'ATR trend',
    full: 'Is the daily jumpiness growing or shrinking versus about a month ago?\nValues: expanding = widen stops and buy fewer shares; contracting = the stock is coiling up, a big move often follows; stable = no real change.',
  },
  avg_vol_60d: {
    short: '60d avg volume',
    full: 'Average shares traded per day over about 3 months.\nUnit: shares (often millions).\nTells you whether a position can get in and out without moving the price.',
  },
  avg_vol_5d: {
    short: '5d avg volume',
    full: 'Average shares traded per day over the last week.\nUnit: shares.\nThe recent-activity read the volume ratio compares against the 3-month normal.',
  },
  vol_ratio_5_60: {
    short: 'Volume ratio: 5d/60d',
    full: "This week's average volume versus the 3-month normal.\nUnit: a ratio; usually 0.5 to 2, where 1.0 = normal.\nAbove ~1.5 during a breakout = real interest confirms the move; below ~0.7 = the move is suspect.",
  },
  support_1: {
    short: 'Nearest support',
    full: "The nearest price BELOW today's where buyers stepped in before (a past dip-bottom).\nUnit: the stock's currency.\nA protective stop-loss belongs just below a level like this, not at a random percent.\nBlank when the price sits at its lowest point in ~6 months — there is no past floor beneath it.",
  },
  resistance_1: {
    short: 'Nearest resistance',
    full: "The nearest price ABOVE today's where sellers showed up before (a past peak).\nUnit: the stock's currency.\nThe first realistic profit target.\nBlank when the price sits at its highest point in ~6 months — there is no past ceiling above it.",
  },
  typical_pullback_atr: {
    short: 'Typical price drop: 6m',
    full: "How deep this stock's normal dips have been over the last ~6 months (120 trading days) — from each local top down to the next local bottom — in normal daily moves (ATR units).\nRange: usually 1 to 5.\nIf a stop is closer than this, ordinary wiggling will hit it even when the trade idea is right.",
  },

  // ---- fundamentals ----
  growth: {
    short: 'Growth',
    full: 'Year-over-year growth taken from the latest annual report.',
  },
  revenue_yoy_pct: {
    short: 'Revenue YoY %',
    full: 'Revenue growth vs. the same period a year earlier (Year-over-Year).',
  },
  net_income_yoy_pct: {
    short: 'Net income YoY %',
    full: 'Bottom-line profit growth vs. a year earlier.',
  },
  eps_yoy_pct: {
    short: 'EPS YoY %',
    full: 'Earnings-per-share growth vs. a year earlier — profit divided by the number of shares.',
  },
  profitability: {
    short: 'Margins',
    full: 'How much of each dollar of revenue the company keeps at each stage of the business.',
  },
  gross_margin_pct: {
    short: 'Gross margin %',
    full: '% of revenue left after the direct costs of making the product.',
  },
  operating_margin_pct: {
    short: 'Operating margin %',
    full: '% of revenue left after running costs like salaries and marketing.',
  },
  net_margin_pct: {
    short: 'Net margin %',
    full: '% of revenue left as final profit after everything, including tax and interest.',
  },
  roe_pct: {
    short: 'ROE %',
    full: 'Return on Equity — profit as a % of shareholders’ money.\nMeasures how efficiently the company uses investor capital.',
  },
  balance_sheet: {
    short: 'Balance sheet',
    full: 'A snapshot of what the company owns vs. what it owes — its financial strength.',
  },
  current_ratio: {
    short: 'Current ratio',
    full: 'Short-term assets ÷ short-term debts.\nAbove 1 means the company can cover its near-term bills.',
  },
  debt_to_equity: {
    short: 'Debt/Equity',
    full: 'Total debts ÷ shareholders’ money.\nLower generally means safer.',
  },
  cash: {
    short: 'Cash',
    full: 'Cash and cash-like holdings on hand, in USD.',
  },
  meta: {
    short: 'Report info',
    full: 'Which financial report these numbers come from.',
  },
  entity_name: {
    short: 'Entity',
    full: 'The company’s registered legal name.',
  },
  period_end: {
    short: 'Period end',
    full: 'The date the financial report covers up to.',
  },
  basis: {
    short: 'Basis',
    full: 'The type of report the numbers come from (e.g. annual 10-K, the audited yearly filing).',
  },
  valuation: {
    short: 'Valuation',
    full: 'How expensive the stock is relative to its earnings, sales, and assets.',
  },
  pe_ttm: {
    short: 'P/E (TTM)',
    full: 'Price-to-Earnings — share price ÷ the last 12 months’ earnings (Trailing Twelve Months).\nHigher = the market pays more per dollar of profit.',
  },
  pe_forward: {
    short: 'Forward P/E',
    full: 'Share price ÷ analysts’ expected earnings for next year.',
  },
  ps_ttm: {
    short: 'P/S (TTM)',
    full: 'Price-to-Sales — total market value ÷ the last 12 months’ revenue.',
  },
  pb: {
    short: 'P/B',
    full: 'Price-to-Book — share price ÷ the company’s accounting net worth per share.',
  },
  market_cap: {
    short: 'Market cap',
    full: 'Total market value of all the company’s shares, in USD.',
  },

  // ---- macro economy ----
  next_earnings_date: {
    short: 'Next earnings',
    full: 'The date of the next scheduled earnings report.\nA report inside a week is event risk: one announcement can gap the price past any stop.',
  },
  days_until_earnings: {
    short: 'Days to earnings',
    full: 'Calendar days until the next scheduled earnings report.',
  },
  region: {
    short: 'Region',
    full: 'Which economy these numbers describe.',
  },
  as_of: {
    short: 'As of',
    full: 'The date this block of data describes — lagged sources (macro series, short-interest reports) carry it so stale numbers are never mistaken for today\'s.',
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
  close: { short: '收盘价', full: '最近一个交易日的最后成交价。' },
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
    full: '14日平均真实波幅——日常价格波动的典型幅度（以货币计），常用来设置止损距离。',
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
    full: '最近一个交易年度中最差的单日跌幅，以百分数表示。\n跳空风险检查用它模拟隔夜落地的情形。',
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
  rs_1m: { short: '对比指数（1月）', full: '约1个月（21个交易日）内个股收益减基准指数收益，单位为百分点。\n为正 = 跑赢大盘。' },
  low_1y: { short: '一年最低价', full: '过去一年的最低成交价——一年区间的下边界。' },
  avg_vol_5d: { short: '平均成交量（5日）', full: '最近5个交易日的日均成交股数——量比中的近期活跃度读数。' },
  sma_10w: { short: '10周均线', full: '最近10周收盘价的平均值——周线偏离度所参照的中期趋势线。' },
  regime: {
    short: '市场环境',
    full: '用基准指数（美股为标普500）判断大盘状态：是否高于其200日均线、处于一年区间的什么位置。\n大盘下行时，多数做多机会无论个股图形多好都容易失败。',
  },
  relative_strength: { short: '相对强度', full: '同一窗口内个股收益减指数收益——个股是领先还是落后于大盘。' },
  price: { short: '价格', full: '当前价格及其在近期历史中的位置。' },
  weekly: { short: '周线时间框架', full: '拉远视角（每根K线一周）——决定方向判断；日线信号只应顺着它的方向开仓。' },
  daily: { short: '日线时间框架', full: '交易计划所用的时间框架（每根K线一天）——趋势、动量以及计划挂靠的价位。' },
  volatility: { short: '波动', full: '股票通常的波动幅度——止损与仓位大小的度量单位。' },
  volume: { short: '成交量', full: '交易活跃度——行情是否有真实参与支撑、订单能否顺利退出。' },
  levels: { short: '价位', full: '来自股票自身转折点的价位——买入、止损、目标价的锚点。' },
  risk: { short: '风险', full: '尾部特征——这只股票糟糕的日子究竟有多糟。' },
  bars_daily: { short: '日线数量', full: '已载入的交易日数量。少于253（一个交易年）时，一年期字段只覆盖已有历史。' },
  bars_weekly: { short: '周线数量', full: '由日线合成的周线数量。少于60时，周线结构判断不可靠。' },
  rs_3m: { short: '对比指数（3月）', full: '约3个月（63个交易日）内个股收益减基准指数收益，单位为百分点。\n为正 = 跑赢大盘。' },
  rs_label: { short: '强弱标签', full: 'leader = 1个月和3个月都跑赢基准；laggard = 都跑输；否则 neutral。\n做多优先选 leader。' },
  chg_5d_pct: { short: '涨跌幅（5日）', full: '最近5个交易日收盘价变化（%）。\n涨幅过大意味着好的买点可能已经错过。' },
  range_pct_1y: { short: '一年区间位置', full: '收盘价在一年区间中的排位，以 X/100 表示：0/100 = 最低点，100/100 = 最高点。' },
  high_1y: { short: '一年最高价', full: '过去一年的最高成交价——最受关注的阻力位。\n目标价高于它需要按突破逻辑而非回调逻辑。' },
  trend: { short: '趋势', full: '由均线检查与转折点结构共同判定；两者一致才给出多/空方向，否则为中性。' },
  stretch_10w_atr: { short: '偏离10周线（ATR）', full: '收盘价距10周均线的距离，以周ATR为单位。\n约+1.5以上 = 过度伸展，等回调；上升趋势中-0.5到+1 = 回调买入区。' },
  sma_50: { short: 'SMA 50', full: '50日简单移动平均线——波段交易经典的回调支撑位。' },
  stretch_50d_atr: { short: '偏离50日线（ATR）', full: '收盘价距50日均线的距离，以ATR为单位。\n上升趋势中-1到+1 = 回调买入区；+3以上 = 过度伸展，属于追高。' },
  sma_200: { short: 'SMA 200', full: '200日简单移动平均线——金融市场最受关注的长期均线，无论持仓周期长短都会成为支撑或阻力。' },
  momentum: { short: '动量', full: '综合 RSI 与 MACD 的单一标签：strong / weak / fading（价格强但动量衰减）/ basing（价格弱但动量积聚）/ neutral。' },
  atr_pct: { short: 'ATR %', full: '典型单日波幅占价格的百分比，可跨股票比较。\n超过约6%属于高波动股——考虑缩小仓位。' },
  atr_trend: { short: 'ATR 趋势', full: '当前ATR对比20根K线之前（±10%缓冲带）：expanding = 放宽止损、缩小仓位；contracting = 收敛，往往预示行情；否则 stable。' },
  avg_vol_60d: { short: '平均成交量（60日）', full: '最近60根K线的日均成交股数——衡量订单规模的流动性基线。' },
  vol_ratio_5_60: { short: '量比（5÷60）', full: '最近5根K线的均量除以60日均量。\n突破时高于约1.5 = 有效；低于约0.7 = 存疑。' },
  support_1: { short: '支撑位 1', full: '收盘价下方最近的转折点低点——止损应放在这类价位下方，而不是任意百分比处。' },
  resistance_1: { short: '阻力位 1', full: '收盘价上方最近的转折点高点——第一目标价候选。' },
  typical_pullback_atr: { short: '典型回调（ATR）', full: '最近几次完整回调（转折高点到随后的转折低点）深度的中位数，以ATR为单位。\n止损距离小于它就落在正常波动之内。' },

  growth: { short: '成长性', full: '取自最新年报的同比增长数据。' },
  revenue_yoy_pct: { short: '营收同比 %', full: '营业收入与去年同期相比的增长率。' },
  net_income_yoy_pct: { short: '净利同比 %', full: '净利润与去年同期相比的增长率。' },
  eps_yoy_pct: { short: 'EPS 同比 %', full: '每股收益（利润÷股本）与去年同期相比的增长率。' },
  profitability: { short: '利润率', full: '每一元收入在各个环节能留下多少。' },
  gross_margin_pct: { short: '毛利率 %', full: '扣除直接生产成本后剩余的收入占比。' },
  operating_margin_pct: { short: '营业利润率 %', full: '再扣除工资、营销等运营成本后剩余的占比。' },
  net_margin_pct: { short: '净利率 %', full: '扣除税费、利息等全部成本后，最终利润占收入的比例。' },
  roe_pct: {
    short: 'ROE %',
    full: '净资产收益率——利润占股东投入资金的百分比，衡量公司使用股东资本的效率。',
  },
  balance_sheet: { short: '资产负债', full: '公司拥有什么、欠什么的快照——财务稳健度。' },
  current_ratio: { short: '流动比率', full: '短期资产÷短期负债。\n大于1说明能覆盖近期账单。' },
  debt_to_equity: { short: '产权比率', full: '总负债÷股东权益。\n数值越低通常越安全。' },
  cash: { short: '现金', full: '持有的现金及现金等价物（美元）。' },
  meta: { short: '报表信息', full: '这些数字来自哪份财务报告。' },
  entity_name: { short: '公司名称', full: '公司的注册法定名称。' },
  period_end: { short: '报告期', full: '财报覆盖到的截止日期。' },
  basis: { short: '报表类型', full: '数据来源的报表类型（如年报 10-K，即经审计的年度文件）。' },
  valuation: { short: '估值', full: '股价相对盈利、销售额和资产贵不贵。' },
  pe_ttm: {
    short: '市盈率 TTM',
    full: '股价÷过去12个月的每股盈利（TTM = 最近十二个月）。\n数值越高，市场为每一元利润付的价格越贵。',
  },
  pe_forward: { short: '预期市盈率', full: '股价÷分析师预期的下一年度盈利。' },
  ps_ttm: { short: '市销率 TTM', full: '总市值÷过去12个月的营业收入。' },
  pb: { short: '市净率', full: '股价÷每股账面净资产。' },
  market_cap: { short: '总市值', full: '公司全部股份的市场总价值（美元）。' },

  next_earnings_date: {
    short: '下次财报',
    full: '下一次财报的预定日期。\n一周内的财报属于事件风险：一次公告就可能让价格跳空越过任何止损。',
  },
  days_until_earnings: { short: '距财报天数', full: '距下一次财报的日历天数。' },
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
