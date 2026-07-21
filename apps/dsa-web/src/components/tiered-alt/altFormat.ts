// Number-to-text helpers shared across the alt page.
import type { TieredDebateLink } from '../../api/tiered';

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
