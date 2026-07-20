// Number-to-text helpers shared across the alt page.

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
