import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { TieredDimension } from '../../../api/tiered';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { AltDimensions } from '../AltDimensions';

// Technicals v2 dimension slice: nested envelope groups + the parallel
// formulas map (2026-07-28). rsi_14 has a plugged receipt, sma_50 a
// words-only receipt, and momentum (a label) none.
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
      price: { close: env('closing price', 157.79) },
      daily: {
        sma_50: env('50-day average', 156.36),
        stretch_50d_atr: env('stretch vs 50-day average (ATR)', 0.45),
        momentum: env('momentum', 'neutral'),
        rsi_14: env('RSI (14d)', 38.89),
      },
      volatility: { atr_14: env('ATR (14d)', 3.17) },
    },
    formulas: {
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
    expect(screen.getByText('neutral')).toBeInTheDocument();
    expect(screen.queryByTestId('alt-metric-formula-momentum')).toBeNull();
  });
});
