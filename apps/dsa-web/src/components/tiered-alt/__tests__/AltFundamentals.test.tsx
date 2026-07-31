import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import type { TieredDimension } from '../../../api/tiered';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { AltDimensions } from '../AltDimensions';

const env = (name: string, value: unknown) => ({
  name,
  explanation: `${name} explained`,
  interpretation: `${name} interpreted`,
  value,
});

// Fundamentals v3 dimension slice (regrouped 2026-07-31): the TODO.md
// groups — meta / balance / profitability / growth / valuation /
// quarterly report / dividend — with receipt variable names following
// the sales/earnings word canon. eps_rev_90d_pct is blank on purpose to
// exercise the "n/a" reason modal.
function makeFundamentals(): TieredDimension {
  return {
    dimension: 'fundamentals',
    kind: 'numeric',
    coverage: 'full',
    is_actionable: true,
    narrative: null,
    warnings: [],
    citations: [],
    payload: {
      meta: {
        sector: env('sector', 'Technology'),
        industry: env('industry', 'Consumer Electronics'),
      },
      balance: {
        current_ratio: env('assets to liabilities: short term', 2),
      },
      profitability: {
        gross_margin_pct: env('gross earnings to sales', 40),
        fcf: env('free cash flow', 99e9),
        fcf_to_earnings_pct: env('free cash flow to earnings', 123.75),
      },
      growth: {
        revenue_yoy_q: env('quarterly sales: year over year', 20),
        revenue_growth_trend: env('growth trend: sales', 'accelerating'),
      },
      valuation: {
        pe_ttm: env('trailing price to earnings', 28.5),
      },
      quarterly_report: {
        next_earnings_date: env('next report date', '2025-07-20'),
        eps_rev_90d_pct: env('90d EPS estimate change', null),
        beats_4q: env('4q EPS beat estimate history', '3/4'),
        avg_surprise_pct_4q: env('4q avg diff: EPS vs estimate', 2.5),
      },
      dividend: {
        days_until_dividend: env('days until next dividend payment', 40),
        dividend_amount_est: env('estimated dividend amount', 0.25),
      },
    },
    formulas: {
      'growth.revenue_yoy_q': {
        formula: '(sales_q − sales_q_year_ago) / |sales_q_year_ago| × 100',
        inputs: { sales_q: 30e9, sales_q_year_ago: 25e9 },
      },
      'growth.revenue_growth_trend': {
        branches: [
          { label: 'accelerating', condition: 'yoy_now − yoy_prior > 2' },
          { label: 'slowing', condition: 'yoy_now − yoy_prior < -2' },
          { label: 'steady', condition: null },
        ],
        inputs: { yoy_now: 20, yoy_prior: 12 },
      },
      'profitability.fcf_to_earnings_pct': {
        formula: 'fcf / earnings × 100',
        inputs: { fcf: 99e9, earnings: 80e9 },
      },
      'dividend.days_until_dividend': {
        formula: 'next_dividend_payment_date − today',
        inputs: { next_dividend_payment_date: '2025-08-10', today: '2025-07-01' },
      },
    },
  };
}

// An old stored run (v2 shape): the earnings group with the stored
// days-until receipt — must keep rendering and jumping.
function makeLegacyFundamentals(): TieredDimension {
  return {
    dimension: 'fundamentals',
    kind: 'numeric',
    coverage: 'full',
    is_actionable: true,
    narrative: null,
    warnings: [],
    citations: [],
    payload: {
      earnings: {
        next_earnings_date: env('next earnings date', '2025-07-20'),
        days_until_earnings: env('days until earnings', 19),
      },
    },
    formulas: {
      'earnings.days_until_earnings': {
        formula: 'next_earnings_date − today',
        inputs: { next_earnings_date: '2025-07-20', today: '2025-07-01' },
      },
    },
  };
}

function renderFundamentals(dimension: TieredDimension = makeFundamentals()) {
  return render(
    <UiLanguageProvider>
      <AltDimensions dimensions={[dimension]} />
    </UiLanguageProvider>,
  );
}

describe('AltDimensions — fundamentals v3', () => {
  beforeEach(() => {
    window.localStorage.setItem('dsa.uiLanguage', 'en');
  });

  it('renders the TODO.md payload groups as titled sections with envelope values', () => {
    renderFundamentals();
    const card = screen.getByTestId('alt-dimension-fundamentals');
    // Group titles come from metricLabels, not the raw keys.
    expect(within(card).getByText('Meta info')).toBeInTheDocument();
    expect(within(card).getByText('Balance')).toBeInTheDocument();
    expect(within(card).getByText('Quarterly report')).toBeInTheDocument();
    expect(within(card).getByText('Dividend')).toBeInTheDocument();
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
    expect(screen.getByTestId('alt-metric-formula-days_until_dividend').textContent).toBe(
      '40 days',
    );
    expect(screen.getByText('99.00 billion USD')).toBeInTheDocument();
    expect(screen.getByTestId('alt-metric-formula-fcf_to_earnings_pct').textContent).toBe(
      '123.75 %',
    );
    // Dimensionless ratios stay bare.
    expect(screen.getByText('28.50')).toBeInTheDocument();
  });

  it('renders a blank field as n/a with a why-blank modal', () => {
    renderFundamentals();
    const blank = screen.getByTestId('alt-metric-blank-eps_rev_90d_pct');
    expect(blank.textContent).toBe('n/a');
    fireEvent.click(blank);
    const modal = screen.getByTestId('alt-metric-blank-modal');
    // The per-field reason from metricLabels, not the generic fallback.
    expect(modal.textContent).toMatch(/No analyst estimates were available/);
    expect(screen.getByText('90d EPS estimate change: why blank')).toBeInTheDocument();
  });

  it('opens the quarterly-growth receipt with named statement ingredients', () => {
    renderFundamentals();
    fireEvent.click(screen.getByTestId('alt-metric-formula-revenue_yoy_q'));
    const modal = screen.getByTestId('alt-metric-formula-modal');
    expect(within(modal).getAllByText('quarterly sales').length).toBeGreaterThan(0);
    expect(
      within(modal).getAllByText('sales same quarter last year').length,
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

  it('links the FCF-to-earnings receipt back to the free-cash-flow row', () => {
    renderFundamentals();
    fireEvent.click(screen.getByTestId('alt-metric-formula-fcf_to_earnings_pct'));
    const modal = screen.getByTestId('alt-metric-formula-modal');
    // fcf is a published row → its plugged number is a jump button.
    expect(within(modal).getByRole('button', { name: 'Free cash flow' })).toBeInTheDocument();
    // earnings is a receipt-only ingredient named by the word canon.
    expect(within(modal).getAllByText('earnings').length).toBeGreaterThan(0);
  });

  it('legacy v2 runs keep the days-until receipt linking to the report-date row', () => {
    renderFundamentals(makeLegacyFundamentals());
    fireEvent.click(screen.getByTestId('alt-metric-formula-days_until_earnings'));
    const modal = screen.getByTestId('alt-metric-formula-modal');
    expect(
      within(modal).getByRole('button', { name: 'Next report date' }),
    ).toBeInTheDocument();
  });

  it('shows Meaning + Interpretation blocks in the label tooltip', () => {
    renderFundamentals();
    const label = screen.getAllByText('Quarterly sales: year over year')[0];
    fireEvent.mouseEnter(label.closest('span[class*="inline-flex"]') ?? label);
    const tooltip = screen.getByRole('tooltip');
    expect(within(tooltip).getByText('Meaning:')).toBeInTheDocument();
    expect(within(tooltip).getByText('Interpretation:')).toBeInTheDocument();
    expect(
      within(tooltip).getByText(/direction of change matters more than the level/),
    ).toBeInTheDocument();
  });
});
