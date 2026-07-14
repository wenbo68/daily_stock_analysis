// Number-to-text helpers shared across the alt page.

// 0.01 -> '1', 0.005 -> '0.5' — a stored risk fraction as the percent the
// user typed, without float noise (0.01 * 100 === 1.0000000000000002).
export const riskPctText = (fraction: number): string =>
  String(Number((fraction * 100).toPrecision(12)));

// 100000.0 -> '100000' — a capital amount as the plain number it was entered as.
export const plainNumber = (value: number): string => String(Number(value));
