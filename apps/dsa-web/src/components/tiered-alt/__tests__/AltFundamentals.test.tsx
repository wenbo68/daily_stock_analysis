import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import type { TieredDimension } from '../../../api/tiered';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { AltDimensions } from '../AltDimensions';

// Fundamentals v2 dimension slice (2026-07-29): nested envelope groups —
// with the new `interpretation` key — plus the parallel formulas map.
function makeFundamentals(): TieredDimension {
  const env = (name: string, value: unknown) => ({
    name,
    explanation: `${name} explained`,
    interpretation: `${name} interpreted`,
    value,
  });
  return {
    dimension: 'fundamentals',
    kind: 'numeric',
    coverage: 'full',
    is_actionable: true,
    narrative: null,
    warnings: [],
    citations: [],
    payload: {
      profile: {
        sector: env('sector', 'Technology'),
        industry: env('industry', 'Consumer Electronics'),
      },
      earnings: {
        next_earnings_date: env('next earnings date', '2025-07-20'),
        days_until_earnings: env('days until earnings', 19),
        beats_4q: env('earnings beats (last 4)', '3/4'),
        avg_surprise_pct_4q: env('avg earnings surprise (last 4)', 2.5),
      },
      growth: {
        revenue_yoy_q: env('quarterly revenue YoY', 20),
        revenue_growth_trend: env('revenue growth trend', 'accelerating'),
      },
      profitability: {
        gross_margin_pct: env('gross margin', 40),
        fcf: env('free cash flow', 99e9),
      },
      valuation: {
        pe_ttm: env('trailing P/E', 28.5),
      },
    },
    formulas: {
      'earnings.days_until_earnings': {
        formula: 'next_earnings_date − today',
        inputs: { next_earnings_date: '2025-07-20', today: '2025-07-01' },
      },
      'growth.revenue_yoy_q': {
        formula: '(revenue_q − revenue_q_year_ago) / |revenue_q_year_ago| × 100',
        inputs: { revenue_q: 30e9, revenue_q_year_ago: 25e9 },
      },
      'growth.revenue_growth_trend': {
        branches: [
          { label: 'accelerating', condition: 'yoy_now − yoy_prior > 2' },
          { label: 'slowing', condition: 'yoy_now − yoy_prior < -2' },
          { label: 'steady', condition: null },
        ],
        inputs: { yoy_now: 20, yoy_prior: 12 },
      },
    },
  };
}

function renderFundamentals() {
  return render(
    <UiLanguageProvider>
      <AltDimensions dimensions={[makeFundamentals()]} />
    </UiLanguageProvider>,
  );
}

describe('AltDimensions — fundamentals v2', () => {
  beforeEach(() => {
    window.localStorage.setItem('dsa.uiLanguage', 'en');
  });

  it('renders the payload groups as titled sections with envelope values', () => {
    renderFundamentals();
    const card = screen.getByTestId('alt-dimension-fundamentals');
    // Group titles come from metricLabels, not the raw keys.
    expect(within(card).getByText('Profile')).toBeInTheDocument();
    expect(within(card).getByText('Earnings events')).toBeInTheDocument();
    expect(within(card).getByText('Growth')).toBeInTheDocument();
    // Envelopes (4-key, with interpretation) unwrap to one value row.
    expect(within(card).getByText('Technology')).toBeInTheDocument();
    expect(within(card).getByText('3/4')).toBeInTheDocument();
    // The envelope prose never renders — the UI keeps its own labels.
    expect(within(card).queryByText(/explained/)).toBeNull();
    expect(within(card).queryByText(/interpreted/)).toBeNull();
  });

  it('appends units to fundamentals values', () => {
    renderFundamentals();
    expect(screen.getByTestId('alt-metric-formula-revenue_yoy_q').textContent).toBe('20 %');
    expect(screen.getByText('19 days')).toBeInTheDocument();
    expect(screen.getByText('99.00 billion USD')).toBeInTheDocument();
    // Dimensionless ratios stay bare.
    expect(screen.getByText('28.50')).toBeInTheDocument();
  });

  it('opens the quarterly-growth receipt with named statement ingredients', () => {
    renderFundamentals();
    fireEvent.click(screen.getByTestId('alt-metric-formula-revenue_yoy_q'));
    const modal = screen.getByTestId('alt-metric-formula-modal');
    expect(within(modal).getAllByText('quarterly revenue').length).toBeGreaterThan(0);
    expect(
      within(modal).getAllByText('revenue same quarter last year').length,
    ).toBeGreaterThan(0);
    expect(within(modal).getByText('30.00 billion')).toBeInTheDocument();
    expect(within(modal).getByText('= 20 %')).toBeInTheDocument();
  });

  it('renders the growth-trend rule as one line per outcome', () => {
    renderFundamentals();
    fireEvent.click(screen.getByTestId('alt-metric-formula-revenue_growth_trend'));
    const modal = screen.getByTestId('alt-metric-formula-modal');
    expect(within(modal).getAllByText(/accelerating/).length).toBeGreaterThan(0);
    expect(within(modal).getAllByText(/slowing/).length).toBeGreaterThan(0);
  });

  it('links the days-until receipt back to the earnings-date row', () => {
    renderFundamentals();
    fireEvent.click(screen.getByTestId('alt-metric-formula-days_until_earnings'));
    const modal = screen.getByTestId('alt-metric-formula-modal');
    expect(
      within(modal).getByRole('button', { name: 'Next earnings' }),
    ).toBeInTheDocument();
  });

  it('shows Meaning + Interpretation blocks in the label tooltip', () => {
    renderFundamentals();
    const label = screen.getAllByText('Quarterly revenue YoY')[0];
    fireEvent.mouseEnter(label.closest('span[class*="inline-flex"]') ?? label);
    const tooltip = screen.getByRole('tooltip');
    expect(within(tooltip).getByText('Meaning:')).toBeInTheDocument();
    expect(within(tooltip).getByText('Interpretation:')).toBeInTheDocument();
    expect(
      within(tooltip).getByText(/direction of change matters more than the level/),
    ).toBeInTheDocument();
  });
});
