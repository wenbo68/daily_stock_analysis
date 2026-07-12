import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { TieredSizing } from '../../../api/tiered';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { SizingCard } from '../SizingCard';

function makeSizing(overrides: Partial<TieredSizing> = {}): TieredSizing {
  return {
    enabled: true,
    shares: 166,
    shares_before_multiplier: null,
    risk_multiplier: null,
    position_value: 15936,
    risk_amount: 996,
    loss_per_share: 6,
    lot_size: 1,
    cap_applied: false,
    reason_code: null,
    refusal_reason: null,
    notes: [],
    inputs: {
      capital: 100000,
      risk_fraction: 0.01,
      max_position_fraction: 0.25,
      fee_fraction: 0,
      entry: 96,
      stop_loss: 90,
    },
    ...overrides,
  };
}

function renderCard(sizing: TieredSizing) {
  render(
    <UiLanguageProvider>
      <SizingCard sizing={sizing} />
    </UiLanguageProvider>,
  );
}

describe('SizingCard', () => {
  it('shows the computed share count when sized', () => {
    renderCard(makeSizing());
    expect(screen.getByTestId('sizing-result')).toBeInTheDocument();
    expect(screen.getByText('166')).toBeInTheDocument();
    expect(screen.queryByTestId('sizing-off')).not.toBeInTheDocument();
    expect(screen.queryByTestId('sizing-refused')).not.toBeInTheDocument();
  });

  it('shows the explicit off state when settings are absent', () => {
    renderCard(
      makeSizing({
        enabled: false,
        shares: null,
        position_value: null,
        risk_amount: null,
        loss_per_share: null,
        reason_code: 'sizing_off',
        refusal_reason: 'Sizing is off.',
        inputs: {
          capital: null,
          risk_fraction: null,
          max_position_fraction: 0.25,
          fee_fraction: 0,
          entry: 96,
          stop_loss: 90,
        },
      }),
    );
    expect(screen.getByTestId('sizing-off')).toBeInTheDocument();
    expect(screen.queryByTestId('sizing-result')).not.toBeInTheDocument();
  });

  it('shows a plain-words refusal for non-buy verdicts', () => {
    renderCard(
      makeSizing({
        shares: null,
        position_value: null,
        risk_amount: null,
        reason_code: 'not_a_buy',
        refusal_reason: "direction is 'hold', not 'buy'",
      }),
    );
    const refused = screen.getByTestId('sizing-refused');
    expect(refused).toBeInTheDocument();
    // the raw backend sentence stays visible as secondary detail
    expect(refused.textContent).toContain("direction is 'hold', not 'buy'");
  });

  it('explains an applied risk multiplier including the zero case', () => {
    renderCard(
      makeSizing({
        shares: 0,
        shares_before_multiplier: 166,
        risk_multiplier: 0,
        position_value: 0,
        risk_amount: 0,
      }),
    );
    expect(screen.getByTestId('sizing-result')).toBeInTheDocument();
    // the multiplier line and the explicit zero-shares statement both render
    expect(screen.getByText(/166/)).toBeInTheDocument();
  });

  it('renders sizing notes verbatim', () => {
    renderCard(makeSizing({ notes: ['HK board lots vary per stock'] }));
    expect(screen.getByText('HK board lots vary per stock')).toBeInTheDocument();
  });
});
