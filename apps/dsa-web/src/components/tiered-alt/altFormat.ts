// Number-to-text helpers shared across the alt page.
import type { TieredDebateLink } from '../../api/tiered';
import { formatValue } from '../tiered/termHelpers';

// Display units per payload key (owner request 2026-07-28): numbers
// render as "2.88 ATR", "-6.82 %". Dimensionless numbers (RSI, P/E, a
// ranking, ratios, counts) and labels stay bare.
const METRIC_UNIT: Record<string, string> = {
  chg_5d_pct: '%',
  atr_pct: '%',
  worst_day_pct_1y: '%',
  rs_1m: '%',
  rs_3m: '%',
  stretch_10w_atr: 'ATR',
  stretch_50d_atr: 'ATR',
  typical_pullback_atr: 'ATR',
  avg_vol_60d: 'shares',
  avg_vol_5d: 'shares',
  vol_ratio_5_60: '×',
  // Stored-run keys that carry the same units.
  volatility_pct: '%',
  bias_20: '%',
  avg_volume_20: 'shares',
  // Fundamentals v2 (2026-07-29; regrouped 2026-07-31).
  days_until_earnings: 'days',
  avg_surprise_pct_4q: '%',
  reaction_avg_abs_pct: '%',
  reaction_worst_pct: '%',
  eps_rev_90d_pct: '%',
  revenue_yoy_q: '%',
  eps_yoy_q: '%',
  gross_margin_pct: '%',
  operating_margin_pct: '%',
  roe_pct: '%',
  fcf: 'USD',
  fcf_to_earnings_pct: '%',
  market_cap: 'USD',
  days_until_dividend: 'days',
  dividend_amount_est: 'USD',
  // Legacy fundamentals keys old stored runs still render.
  revenue_yoy_pct: '%',
  net_income_yoy_pct: '%',
  eps_yoy_pct: '%',
  net_margin_pct: '%',
  cash: 'USD',
};

// A metric value with its unit appended when it has one.
export const formatMetricValue = (key: string, value: unknown): string => {
  // The 1y price ranking reads as a position on a 0-100 scale: "30/100"
  // (owner format 2026-07-28).
  if (key === 'range_pct_1y' && typeof value === 'number') {
    return `${Math.round(value)}/100`;
  }
  const text = formatValue(value);
  const unit = typeof value === 'number' ? METRIC_UNIT[key] : undefined;
  return unit ? `${text} ${unit}` : text;
};

// 0.01 -> '1', 0.005 -> '0.5' — a stored risk fraction as the percent the
// user typed, without float noise (0.01 * 100 === 1.0000000000000002).
export const riskPctText = (fraction: number): string =>
  String(Number((fraction * 100).toPrecision(12)));

// 100000.0 -> '100000' — a capital amount as the plain number it was entered as.
export const plainNumber = (value: number): string => String(Number(value));

// Anchor ids of the levels table's cells ('entry', 'secondary_entry',
// 'stop_loss', 'take_profit'), so formulas elsewhere in the report can
// scroll-flash the cell a number came from.
export const computedCellId = (key: string): string => `alt-level-computed-${key}`;
export const adjustedCellId = (key: string): string => `alt-level-adjusted-${key}`;

// The outlook word for a tier verdict — the outlook redesign renamed
// buy/hold/sell to bullish/neutral/bearish everywhere the UI speaks.
export const directionOutlook = (direction: string | null | undefined): string => {
  switch (direction) {
    case 'buy':
      return 'bullish';
    case 'hold':
      return 'neutral';
    case 'sell':
      return 'bearish';
    default:
      return 'unknown';
  }
};

// The citation markup the backend prompts describe — the model is told
// to put links in a separate array, but sometimes writes the markup
// inline in the sentence instead: {{ref: "technicals.close", "value":
// "340.75"}}. Quoting varies, so keys and values are matched loosely.
const INLINE_REF_RE =
  /\{\{\s*"?ref"?\s*:\s*"?([^",}]+?)"?\s*(?:,\s*"?value"?\s*:\s*(?:"([^"]*)"|([^,}]+?))\s*)?\}\}/g;

// Renders inline markup as just its cited value, merging the ref into
// the links list (deduped) so the value still underlines and jumps.
export const stripInlineRefs = (
  text: string,
  links: TieredDebateLink[],
): { text: string; links: TieredDebateLink[] } => {
  if (!text.includes('{{')) {
    return { text, links };
  }
  const merged = [...links];
  const known = new Set(links.map((link) => `${link.ref}|${link.value ?? ''}`));
  const clean = text
    .replace(INLINE_REF_RE, (_all, ref: string, quoted?: string, bare?: string) => {
      const value = quoted ?? bare ?? null;
      const key = `${ref}|${value ?? ''}`;
      if (!known.has(key)) {
        known.add(key);
        merged.push({ ref, value });
      }
      return value ?? '';
    })
    .replace(/ {2,}/g, ' ');
  return { text: clean, links: merged };
};
