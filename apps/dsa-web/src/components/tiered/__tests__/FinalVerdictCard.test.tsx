import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { TieredTierSection } from '../../../api/tiered';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { FinalVerdictCard } from '../FinalVerdictCard';

function makeSection(overrides: Partial<TieredTierSection> = {}): TieredTierSection {
  return {
    tier: 2,
    coverage: 'full',
    direction: 'hold',
    confidence: null,
    score: null,
    levels: { entry: null, secondary_entry: null, stop_loss: null, take_profit: null },
    narrative: null,
    warnings: [],
    ...overrides,
  };
}

describe('FinalVerdictCard', () => {
  it('shows the symbol, the final direction, and the deciding tier', () => {
    render(
      <UiLanguageProvider>
        <FinalVerdictCard
          symbol="AAPL"
          final={makeSection({ tier: 3 })}
          tier1Direction="buy"
          tier2={makeSection({ tier: 2, direction: 'hold' })}
          tier3={makeSection({ tier: 3, direction: 'hold' })}
        />
      </UiLanguageProvider>,
    );
    const card = screen.getByTestId('final-verdict-card');
    expect(within(card).getByText('AAPL')).toBeInTheDocument();
    expect(card.textContent).toContain('3');
  });

  it('renders the verdict trail with one step per tier that ran', () => {
    render(
      <UiLanguageProvider>
        <FinalVerdictCard
          symbol="AAPL"
          final={makeSection({ tier: 3 })}
          tier1Direction="buy"
          tier2={makeSection({ tier: 2, direction: 'hold' })}
          tier3={makeSection({ tier: 3, direction: 'hold' })}
        />
      </UiLanguageProvider>,
    );
    const card = screen.getByTestId('final-verdict-card');
    // tier-1 said buy, tiers 2 and 3 said hold, and the big final badge is hold too
    expect(within(card).getAllByText(/buy|买入/i)).toHaveLength(1);
    expect(within(card).getAllByText(/hold|持有/i).length).toBeGreaterThanOrEqual(3);
  });

  it('omits trail steps for tiers that did not run', () => {
    render(
      <UiLanguageProvider>
        <FinalVerdictCard
          symbol="AAPL"
          final={makeSection({ tier: 2, direction: 'sell' })}
          tier1Direction="buy"
          tier2={makeSection({ tier: 2, direction: 'sell' })}
          tier3={null}
        />
      </UiLanguageProvider>,
    );
    const card = screen.getByTestId('final-verdict-card');
    // one arrow only: tier 1 → tier 2
    expect(card.textContent?.match(/→/g)).toHaveLength(1);
  });
});
