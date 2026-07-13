import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { TieredResult, TieredTierSection } from '../../../api/tiered';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { AltResult } from '../AltResult';

const LEVELS = { entry: 96, secondary_entry: 94, stop_loss: 90, take_profit: 108 };

function makeDimension(name: string): TieredResult['dimensions'][number] {
  return {
    dimension: name,
    kind: 'numeric',
    coverage: 'full',
    is_actionable: true,
    payload: { close: 100 },
    narrative: null,
    warnings: [],
    citations: [],
  };
}

function makeSection(tier: number, direction: TieredTierSection['direction']): TieredTierSection {
  return {
    tier,
    coverage: 'full',
    direction,
    confidence: null,
    score: null,
    levels: LEVELS,
    narrative: null,
    warnings: [],
  };
}

// Shaped like an old stored depth-1 run: none of the v2 optional blocks.
function makeV1Result(): TieredResult {
  return {
    symbol: 'AAPL',
    direction: 'buy',
    coverage: 'full',
    score: 72,
    confidence: null,
    levels: LEVELS,
    levels_detail: null,
    narrative: 'Tier-1 narrative.',
    warnings: [],
    dimensions: ['technicals', 'fundamentals', 'macro_econ', 'sentiment'].map(makeDimension),
    signal: null,
  } as unknown as TieredResult;
}

function makeDeepResult(): TieredResult {
  return {
    ...makeV1Result(),
    depth: 3,
    final: { tier: 3, direction: 'hold', coverage: 'full', confidence: null, levels: LEVELS },
    tier2: { ...makeSection(2, 'hold'), debate_detail: { turns: [], verdict: null, warnings: [] } },
    tier3: { ...makeSection(3, 'hold'), risk_detail: { takes: [], verdict: null, warnings: [] } },
    sizing: {
      enabled: true,
      shares: 83,
      shares_before_multiplier: 166,
      risk_multiplier: 0.5,
      position_value: 7968,
      risk_amount: 498,
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
    },
  };
}

function renderResult(result: TieredResult) {
  render(
    <UiLanguageProvider>
      <AltResult result={result} />
    </UiLanguageProvider>,
  );
}

describe('AltResult', () => {
  it('renders the same skeleton for a depth-1 (old) run: final verdict, order size, tier 1, dimensions', () => {
    renderResult(makeV1Result());
    expect(screen.getByTestId('alt-final-verdict')).toBeInTheDocument();
    expect(screen.getByTestId('alt-order-size')).toBeInTheDocument();
    expect(screen.getByTestId('alt-tier1')).toBeInTheDocument();
    expect(screen.queryByTestId('alt-tier2')).not.toBeInTheDocument();
    expect(screen.queryByTestId('alt-tier3')).not.toBeInTheDocument();
    expect(screen.getAllByTestId(/alt-dimension-/)).toHaveLength(4);
    // no sizing block recorded → dash plus the explanation, never a missing card
    expect(screen.getByTestId('alt-order-size-shares').textContent).toContain('—');
  });

  it('adds tier 2 and tier 3 cards on a deep run without changing the rest', () => {
    renderResult(makeDeepResult());
    expect(screen.getByTestId('alt-final-verdict')).toBeInTheDocument();
    expect(screen.getByTestId('alt-order-size')).toBeInTheDocument();
    expect(screen.getByTestId('alt-tier1')).toBeInTheDocument();
    expect(screen.getByTestId('alt-tier2')).toBeInTheDocument();
    expect(screen.getByTestId('alt-tier3')).toBeInTheDocument();
    expect(screen.getAllByTestId(/alt-dimension-/)).toHaveLength(4);
    expect(screen.getByTestId('alt-order-size-shares').textContent).toContain('83');
  });

  it('keeps the cards in the fixed order: verdict, size, dimensions, tier 1, tier 2, tier 3', () => {
    renderResult(makeDeepResult());
    const ids = Array.from(document.querySelectorAll('[data-testid]'))
      .map((el) => el.getAttribute('data-testid') ?? '')
      .filter(
        (id) =>
          ['alt-final-verdict', 'alt-order-size', 'alt-tier1', 'alt-tier2', 'alt-tier3'].includes(
            id,
          ) || id === 'alt-dimension-technicals',
      );
    expect(ids).toEqual([
      'alt-final-verdict',
      'alt-order-size',
      'alt-dimension-technicals',
      'alt-tier1',
      'alt-tier2',
      'alt-tier3',
    ]);
  });

  it('shows 0 shares (not a dash) when the run decided not to buy', () => {
    const deep = makeDeepResult();
    renderResult({
      ...deep,
      sizing: {
        ...deep.sizing!,
        shares: null,
        shares_before_multiplier: null,
        risk_multiplier: null,
        reason_code: 'not_a_buy',
        refusal_reason: "Sizing only applies when opening a position (direction is 'hold', not 'buy').",
      },
    });
    const hero = screen.getByTestId('alt-order-size-shares').textContent ?? '';
    expect(hero).toContain('0');
    expect(hero).not.toContain('—');
  });

  it('tucks data notes behind an exclamation mark that opens a plain-English modal', () => {
    const result = {
      ...makeV1Result(),
      warnings: [
        "unparseable sniper level ideal_buy='Ideal buy point: N/A (waiting for clarity)'",
        'some brand-new warning shape the frontend has never seen',
      ],
    };
    renderResult(result);
    // Nothing inline — the notes only exist behind the mark.
    expect(screen.queryByText(/left blank|留空/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('alt-notes-button'));
    // Known shape → the friendly sentence (raw text shown beneath it).
    expect(screen.getByText(/left blank|留空/)).toBeInTheDocument();
    // Unknown shape → raw text unchanged (never an invented gloss).
    expect(
      screen.getByText('some brand-new warning shape the frontend has never seen'),
    ).toBeInTheDocument();
  });
});
