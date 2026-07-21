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
    short: 'Close',
    full: 'Latest closing price — the last traded price of the most recent trading day.',
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
    short: 'RSI 14',
    full: 'Relative Strength Index over 14 days — a momentum gauge from 0 to 100.\nAbove 70 usually means overheated (price may pull back); below 30 means oversold (price may bounce).',
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
    short: 'ATR 14',
    full: 'Average True Range over 14 days — the typical daily price swing in dollars.\nA volatility measure often used to place stop-loss levels.',
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
  worst_day_1y: {
    short: 'Worst day 1y',
    full: 'The worst single-day price drop in the loaded history (about a year), as a fraction.\nThe gap-risk check stresses the plan with this drop landing overnight.',
  },
  worst_day_5pct: {
    short: 'Worst 5% day',
    full: 'Retired statistic old runs still carry: the daily drop only the worst 5% of days exceeded.',
  },
  score: {
    short: 'Tech score',
    full: 'Overall technical score computed from the indicators above.',
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
    full: 'The date this macro data was gathered.',
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
  worst_day_1y: {
    short: '年内最差单日',
    full: '已加载历史（约一年）中最差的单日跌幅（比例）。\n跳空风险检查用它模拟隔夜落地的情形。',
  },
  worst_day_5pct: {
    short: '最差5%单日',
    full: '旧运行保留的已退役统计：仅最差 5% 的交易日才会超过的单日跌幅。',
  },
  score: { short: '技术评分', full: '由上述指标综合计算出的技术面总分。' },

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
  as_of: { short: '采集日期', full: '本组宏观数据的采集日期。' },
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
};

export function metricEntry(key: string, language: UiLanguage): MetricEntry | null {
  const table = language === 'en' ? en : zh;
  return table[key] ?? null;
}
