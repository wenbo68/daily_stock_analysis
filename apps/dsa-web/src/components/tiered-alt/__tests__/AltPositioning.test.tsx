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

// Positioning v2 dimension slice (TODO.md truth 2026-08-01): the five
// groups — meta / ownership structure / short interest / insider
// trades / options. institutional_diff_q_pp and implied_vol_rank_1y are
// blank BY DESIGN (no reliable free source) to exercise their "n/a"
// reason modals.
function makePositioning(): TieredDimension {
  return {
    dimension: 'positioning',
    kind: 'numeric',
    coverage: 'full',
    is_actionable: true,
    narrative: null,
    warnings: [],
    citations: [],
    payload: {
      meta: {
        ownership_as_of: env('ownership structure up to', '2026-03-31'),
        short_interest_as_of: env('short interest up to', '2026-07-01'),
        options_bets_through: env('options betting up to', '2026-09-18'),
      },
      ownership: {
        institutional_pct: env('institutional ownership', 61.55),
        institutional_diff_q_pp: env(
          'institutional ownership diff (current vs prev quarter)',
          null,
        ),
        top10_institutions_pct: env('top-10 institutional ownership', 12),
        insider_pct: env('insider ownership', 2.1),
        float_shares: env('float', 1.6e9),
      },
      short_interest: {
        short_pct_of_float: env('shorted shares to float', 3.13),
        days_to_cover: env('shorted shares to avg daily volume', 1.8),
        change_vs_prior_month_pct: env(
          'shorted shares diff (current vs prev report)',
          25,
        ),
      },
      insider_activity_6m: {
        buy_count: env('6m total insider buys', 1),
        sell_count: env('6m total insider sells', 1),
        net_value_usd: env('6m money diff (insider buys vs sells)', 56000),
      },
      options: {
        put_call_oi_ratio: env('puts to calls (held)', 0.92),
        put_call_volume_ratio: env('puts to calls (traded today)', 1.2),
        total_open_interest: env('total held options', 2880),
        implied_vol_pct: env('implied stock volatility', 26.08),
        implied_vol_rank_1y: env(
          'implied stock volatility ranking (1y range)',
          null,
        ),
        implied_report_move_pct: env(
          'implied quarterly report day price change magnitude',
          8.4,
        ),
      },
    },
    formulas: {
      'short_interest.short_pct_of_float': {
        formula: 'shorted_shares / float_shares × 100',
        inputs: { shorted_shares: 50e6, float_shares: 1.6e9 },
      },
      'insider_activity_6m.net_value_usd': {
        formula: 'insider_buy_money − insider_sell_money',
        inputs: { insider_buy_money: 100000, insider_sell_money: 44000 },
      },
      'options.put_call_oi_ratio': {
        formula: 'held_puts / held_calls',
        inputs: { held_puts: 1380, held_calls: 1500 },
      },
      'options.total_open_interest': {
        formula: 'held_puts + held_calls',
        inputs: { held_puts: 1380, held_calls: 1500 },
      },
      'options.implied_report_move_pct': {
        formula: '(atm_call_price + atm_put_price) / stock_price × 100',
        inputs: { atm_call_price: 4.3, atm_put_price: 4.1, stock_price: 100 },
      },
    },
  };
}

function renderPositioning(dimension: TieredDimension = makePositioning()) {
  return render(
    <UiLanguageProvider>
      <AltDimensions dimensions={[dimension]} />
    </UiLanguageProvider>,
  );
}

describe('AltDimensions — positioning v2', () => {
  beforeEach(() => {
    window.localStorage.setItem('dsa.uiLanguage', 'en');
  });

  it('renders the TODO.md groups as titled sections with the truth names', () => {
    renderPositioning();
    const card = screen.getByTestId('alt-dimension-positioning');
    expect(within(card).getByText('Meta info')).toBeInTheDocument();
    expect(within(card).getByText('Ownership structure')).toBeInTheDocument();
    expect(within(card).getByText('Short interest')).toBeInTheDocument();
    expect(within(card).getByText('Insider trades (6m)')).toBeInTheDocument();
    expect(within(card).getByText('Options')).toBeInTheDocument();
    // Field labels come from metricLabels (truth names), not raw keys.
    expect(within(card).getByText('Shorted shares to float')).toBeInTheDocument();
    expect(within(card).getByText('Puts to calls (held)')).toBeInTheDocument();
    expect(within(card).getByText('Options betting up to')).toBeInTheDocument();
    // The envelope prose never renders — the UI keeps its own labels.
    expect(within(card).queryByText(/explained/)).toBeNull();
    expect(within(card).queryByText(/interpreted/)).toBeNull();
  });

  it('appends units, renders the report-day move as a ± magnitude', () => {
    renderPositioning();
    expect(screen.getByText('1.80 days')).toBeInTheDocument();
    expect(screen.getByText('61.55 %')).toBeInTheDocument();
    expect(screen.getByText('1.60 billion shares')).toBeInTheDocument();
    expect(
      screen.getByTestId('alt-metric-formula-implied_report_move_pct').textContent,
    ).toMatch(/^±8\.40 %$/);
    expect(
      screen.getByTestId('alt-metric-formula-total_open_interest').textContent,
    ).toMatch(/contracts$/);
    // Ratios stay bare.
    expect(
      screen.getByTestId('alt-metric-formula-put_call_oi_ratio').textContent,
    ).toBe('0.92');
  });

  it('explains the two unsourced truth fields in their n/a modals', () => {
    renderPositioning();
    const diff = screen.getByTestId('alt-metric-blank-institutional_diff_q_pp');
    expect(diff.textContent).toBe('n/a');
    fireEvent.click(diff);
    expect(screen.getByTestId('alt-metric-blank-modal').textContent).toMatch(
      /No reliable free source publishes the prior-quarter aggregate/,
    );
    // No ✕ button by design — Escape closes the modal.
    fireEvent.keyDown(window, { key: 'Escape' });

    fireEvent.click(screen.getByTestId('alt-metric-blank-implied_vol_rank_1y'));
    expect(screen.getByTestId('alt-metric-blank-modal').textContent).toMatch(
      /a year of implied-volatility history/,
    );
  });

  it('opens the money-diff receipt with named ingredients and a unit result', () => {
    renderPositioning();
    fireEvent.click(screen.getByTestId('alt-metric-formula-net_value_usd'));
    const modal = screen.getByTestId('alt-metric-formula-modal');
    expect(within(modal).getAllByText('insider buying ($)').length).toBeGreaterThan(0);
    expect(within(modal).getAllByText('insider selling ($)').length).toBeGreaterThan(0);
    expect(within(modal).getByText('= 56000 USD')).toBeInTheDocument();
  });

  it('links the computed short-percentage receipt back to the float row', () => {
    renderPositioning();
    fireEvent.click(screen.getByTestId('alt-metric-formula-short_pct_of_float'));
    const modal = screen.getByTestId('alt-metric-formula-modal');
    // float_shares is a published row → its plugged number jump-links.
    expect(within(modal).getByRole('button', { name: 'Float' })).toBeInTheDocument();
    // shorted_shares is receipt-only, named by the helper table.
    expect(within(modal).getAllByText('shorted shares').length).toBeGreaterThan(0);
  });

  it('shows Meaning + Interpretation blocks in a positioning tooltip', () => {
    renderPositioning();
    const label = screen.getAllByText('6m total insider buys')[0];
    fireEvent.mouseEnter(label.closest('span[class*="inline-flex"]') ?? label);
    const tooltip = screen.getByRole('tooltip');
    expect(within(tooltip).getByText('Meaning:')).toBeInTheDocument();
    expect(within(tooltip).getByText('Interpretation:')).toBeInTheDocument();
    expect(
      within(tooltip).getByText(/insiders sell for many reasons but buy for exactly one/i),
    ).toBeInTheDocument();
  });
});
