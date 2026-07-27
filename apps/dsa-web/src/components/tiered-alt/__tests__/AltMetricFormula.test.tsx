import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { TieredDimension } from '../../../api/tiered';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { AltDimensions } from '../AltDimensions';

// Technicals v2 dimension slice: nested envelope groups + the parallel
// formulas map (2026-07-28). rsi_14 has a substituted receipt, sma_50 a
// words-only receipt, the trend and regime labels rule receipts, and
// as_of (a raw fact) none.
function makeTechnicals(): TieredDimension {
  const env = (name: string, value: unknown) => ({
    name,
    explanation: `${name} explained`,
    value,
  });
  return {
    dimension: 'technicals',
    kind: 'numeric',
    coverage: 'full',
    is_actionable: true,
    narrative: null,
    warnings: [],
    citations: [],
    payload: {
      meta: { as_of: env('as of', '2026-07-24') },
      regime: { regime: env('market regime', 'bullish') },
      price: { close: env('closing price', 157.79) },
      daily: {
        trend: env('daily trend', 'neutral'),
        sma_50: env('50-day average', 156.36),
        stretch_50d_atr: env('stretch vs 50-day average (ATR)', 0.45),
        rsi_14: env('RSI (14d)', 38.89),
      },
      volatility: { atr_14: env('ATR (14d)', 3.17) },
    },
    formulas: {
      'regime.regime': {
        branches: [
          { label: 'bullish', condition: 'index_close > index_sma_200 && index_range_pct > 50' },
          { label: 'bearish', condition: 'index_close < index_sma_200 && index_range_pct < 50' },
          { label: 'mixed', condition: null },
        ],
        inputs: { index_close: 6234.5, index_sma_200: 5890.2, index_range_pct: 78 },
      },
      'daily.trend': {
        branches: [
          {
            label: 'bullish',
            condition: 'moving-average check = up && pivot structure = higher highs and lows',
          },
          {
            label: 'bearish',
            condition: 'moving-average check = down && pivot structure = lower highs and lows',
          },
          { label: 'neutral', condition: null },
        ],
        inputs: { ma_stack: 'mixed', pivot_structure: 'sideways' },
      },
      'daily.rsi_14': {
        formula: '100 − 100 / (1 + avg_gain_14 / avg_loss_14)',
        inputs: { avg_gain_14: 0.1017, avg_loss_14: 0.1598 },
      },
      'daily.stretch_50d_atr': {
        formula: '(close − sma_50) / atr_14',
        inputs: { close: 157.79, sma_50: 156.36, atr_14: 3.17 },
      },
      'daily.sma_50': {
        formula: 'the sum of the last 50 daily closes / 50',
        inputs: {},
      },
    },
  };
}

function renderTechnicals() {
  return render(
    <UiLanguageProvider>
      <AltDimensions dimensions={[makeTechnicals()]} />
    </UiLanguageProvider>,
  );
}

describe('AltMetricFormula', () => {
  it('opens the three-line receipt from the metric value', () => {
    renderTechnicals();
    fireEvent.click(screen.getByTestId('alt-metric-formula-rsi_14'));
    const modal = screen.getByTestId('alt-metric-formula-modal');
    // Words line: variable tokens shown as their display labels.
    expect(within(modal).getByText('avg gain (14d)')).toBeInTheDocument();
    expect(within(modal).getByText('avg loss (14d)')).toBeInTheDocument();
    // Plugged line: this run's numbers, small values not flattened.
    expect(within(modal).getByText('0.1017')).toBeInTheDocument();
    expect(within(modal).getByText('0.1598')).toBeInTheDocument();
    // Result line.
    expect(within(modal).getByText('= 38.89')).toBeInTheDocument();
  });

  it('links plugged numbers that are payload rows back to their row', () => {
    renderTechnicals();
    fireEvent.click(screen.getByTestId('alt-metric-formula-stretch_50d_atr'));
    const modal = screen.getByTestId('alt-metric-formula-modal');
    // close / sma 50 / atr 14 all exist as rows on the card → buttons.
    expect(within(modal).getByRole('button', { name: 'Close' })).toBeInTheDocument();
    expect(within(modal).getByRole('button', { name: 'SMA 50' })).toBeInTheDocument();
    expect(within(modal).getByRole('button', { name: 'ATR 14' })).toBeInTheDocument();
  });

  it('renders words-only receipts without a plugged line', () => {
    renderTechnicals();
    fireEvent.click(screen.getByTestId('alt-metric-formula-sma_50'));
    const modal = screen.getByTestId('alt-metric-formula-modal');
    expect(
      within(modal).getByText('the sum of the last 50 daily closes / 50'),
    ).toBeInTheDocument();
    // One "=" line only: the result.
    expect(within(modal).getAllByText(/^=/)).toHaveLength(1);
    expect(within(modal).getByText('= 156.36')).toBeInTheDocument();
  });

  it('leaves metrics without a receipt as plain text', () => {
    renderTechnicals();
    expect(screen.getByText('2026-07-24')).toBeInTheDocument();
    expect(screen.queryByTestId('alt-metric-formula-as_of')).toBeNull();
  });

  it('renders a numeric rule as one line per outcome, twice (regime)', () => {
    renderTechnicals();
    fireEvent.click(screen.getByTestId('alt-metric-formula-regime'));
    const modal = screen.getByTestId('alt-metric-formula-modal');
    // Branch labels appear in the words section AND the plugged section.
    expect(within(modal).getAllByText('bullish')).toHaveLength(2);
    expect(within(modal).getAllByText('bearish')).toHaveLength(2);
    expect(within(modal).getAllByText('mixed')).toHaveLength(2);
    expect(
      within(modal).getAllByText(
        (_, element) => element?.tagName === 'P' && element.textContent === 'mixed: else',
      ),
    ).toHaveLength(2);
    // Plugged lines: the index numbers in place (bullish + bearish rows).
    expect(within(modal).getAllByText('6234.5')).toHaveLength(2);
    expect(within(modal).getAllByText('5890.2')).toHaveLength(2);
    expect(within(modal).getByText('= bullish')).toBeInTheDocument();
  });

  it('lists word ingredients for rule labels (trend)', () => {
    renderTechnicals();
    fireEvent.click(screen.getByTestId('alt-metric-formula-trend'));
    const modal = screen.getByTestId('alt-metric-formula-modal');
    // One line per outcome in words, then "ingredient = value" pairs.
    expect(
      within(modal).getByText(/moving-average check = up/),
    ).toBeInTheDocument();
    expect(
      within(modal).getByText(/moving-average check = down/),
    ).toBeInTheDocument();
    expect(
      within(modal).getByText(
        (_, element) => element?.tagName === 'P' && element.textContent === 'neutral: else',
      ),
    ).toBeInTheDocument();
    expect(within(modal).getByText('moving-average check')).toBeInTheDocument();
    expect(within(modal).getByText('mixed')).toBeInTheDocument();
    expect(within(modal).getByText('sideways')).toBeInTheDocument();
    expect(within(modal).getByText('= neutral')).toBeInTheDocument();
  });
});
