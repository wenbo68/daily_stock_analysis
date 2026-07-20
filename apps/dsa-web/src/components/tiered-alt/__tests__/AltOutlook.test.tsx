import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import type {
  TieredDebateDetail,
  TieredResult,
  TieredRiskCardEntry,
} from '../../../api/tiered';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { AltResult } from '../AltResult';

// Outlook-redesign rendering: the conclusion block, the conditional plan
// display, the earnings/staleness notes, the 13-entry risk card, and the
// v10 weighted vote tree. Old stored runs (no outlook field) keep their
// legacy layout — covered by AltResult.test.tsx.

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

// A full 13-entry card: one flagged, one n/a, the rest ok.
function makeRiskCard(): TieredRiskCardEntry[] {
  const ok = (id: string, values: Record<string, unknown>): TieredRiskCardEntry => ({
    id,
    status: 'ok',
    values,
  });
  return [
    ok('concentration', { fraction: 0.15936, cap_fraction: 0.25 }),
    ok('cash', { cash_left: 84064, capital: 100000 }),
    ok('max_loss', { risk_amount: 996, fraction: 0.00996 }),
    { id: 'liquidity', status: 'flag', values: { fraction_of_adv: 0.083, flag_fraction: 0.05 } },
    ok('var', { var_amount: 478, risk_amount: 996 }),
    ok('gap_stress', { gap_price: 87, loss_if_gap: 1494 }),
    ok('volatility', { atr_fraction: 0.03, flag_fraction: 0.04 }),
    ok('reward_risk', { ratio: 2 }),
    ok('stop_atr', { atr_multiple: 2 }),
    ok('stop_vs_swing_low', { stop_loss: 90, swing_low_20: 94 }),
    ok('staleness', { close: 100, entry: 96 }),
    ok('both_entries', { combined_risk: 1660, risk_budget: 1000 }),
    { id: 'ownership_context', status: 'na', values: { ownership: 0 } },
  ];
}

function makeOutlookResult(overrides: Partial<TieredResult> = {}): TieredResult {
  return {
    symbol: 'AAPL',
    market: 'us',
    tier: 1,
    direction: 'buy',
    score: 72,
    confidence: null,
    coverage: 'full',
    levels: LEVELS,
    levels_detail: null,
    narrative: null,
    warnings: [],
    dimensions: ['technicals', 'fundamentals', 'macro_econ', 'sentiment'].map(makeDimension),
    signal: null,
    depth: 1,
    outlook: 'bullish',
    action: 'enter',
    earnings: null,
    risk_card: makeRiskCard(),
    ...overrides,
  };
}

// A v10 weighted vote tree: T1 rated 3 by both authors (weight 3), S1
// single-author weight 2.5 (author 3 + checker 2). Final pool: bullish
// weight 3 of 5.5 total → 10 × 3 / 5.5 = 5.45.
function makeWeightedDebate(): TieredDebateDetail {
  return {
    format: 10,
    turns: [],
    items: [
      {
        id: 'T1',
        dimension: 'technicals',
        direction: 'bullish',
        claim: 'The 14-day RSI (71.20) is above 70.',
        links: [{ ref: 'technicals.rsi_14', value: '71.20' }],
        struck: false,
        problems: [],
        authors: 2,
        author_weights: [3, 3],
        weight: 3,
        votes: [],
        response: null,
        judge: null,
        final_status: 'counted',
        exclusion_reason: null,
      },
      {
        id: 'S1',
        dimension: 'sentiment',
        direction: 'bearish',
        claim: 'The deal is not closed yet.',
        links: [{ ref: 'citation:2', value: null }],
        struck: false,
        problems: [],
        authors: 1,
        author_weights: [3],
        weight: 2.5,
        votes: [
          {
            role: 'checker',
            verdict: 'valid',
            reason: 'Supported by the source.',
            links: [{ ref: 'citation:2', value: null }],
            weight: 2,
          },
        ],
        response: null,
        judge: null,
        final_status: 'counted',
        exclusion_reason: null,
      },
    ],
    verdict: {
      direction: 'hold',
      summary: 'Weighted to hold.',
      final_score: 5.45,
      final_score_rounded: 5,
      initial_score: 5.45,
      adjusted_score: null,
      pools: {
        initial: {
          dimensions: {
            technicals: {
              bullish: 1, bearish: 0, total: 1,
              bullish_weight: 3, bearish_weight: 0, total_weight: 3,
            },
            sentiment: {
              bullish: 0, bearish: 1, total: 1,
              bullish_weight: 0, bearish_weight: 3, total_weight: 3,
            },
          },
          bullish: 1, bearish: 1, total: 2,
          bullish_weight: 3, bearish_weight: 3, total_weight: 6,
          score: 5.0,
        },
        final: {
          dimensions: {
            technicals: {
              bullish: 1, bearish: 0, total: 1,
              bullish_weight: 3, bearish_weight: 0, total_weight: 3,
            },
            sentiment: {
              bullish: 0, bearish: 1, total: 1,
              bullish_weight: 0, bearish_weight: 2.5, total_weight: 2.5,
            },
          },
          bullish: 1, bearish: 1, total: 2,
          bullish_weight: 3, bearish_weight: 2.5, total_weight: 5.5,
          score: 5.45,
        },
      },
      confidence: null,
      reasons_for: [],
      reasons_against: [],
      would_change_mind: null,
      bull_summary: null,
      bear_summary: null,
      scoring: null,
    },
    warnings: [],
  };
}

// A tier-2 section wrapping the given stored detail.
function makeTier2(detail: TieredDebateDetail): NonNullable<TieredResult['tier2']> {
  return {
    tier: 2,
    coverage: 'full',
    direction: 'hold',
    confidence: null,
    score: null,
    levels: LEVELS,
    narrative: 'Weighted to hold.',
    warnings: [],
    debate_detail: detail,
  };
}

// A v11 tree: T1 both-listed (lister ratings 4 and 5 → median 4.5); S1
// single-author (lister 2 rated 3) checked invalid (2) and ruled valid
// by the decider (2) → median 2. Every rating carries its reason.
function makeRichDebate(): TieredDebateDetail {
  const detail = makeWeightedDebate();
  return {
    ...detail,
    format: 11,
    items: [
      {
        ...detail.items![0],
        author_weights: [4, 5],
        author_votes: [
          { lister: 1, weight: 4, weight_reason: 'Strong but not decisive.' },
          { lister: 2, weight: 5, weight_reason: 'Momentum drives the thesis.' },
        ],
        weight: 4.5,
      },
      {
        ...detail.items![1],
        author_weights: [3],
        author_votes: [
          { lister: 2, weight: 3, weight_reason: 'Sentiment is soft evidence.' },
        ],
        weight: 2,
        votes: [
          {
            role: 'checker',
            verdict: 'invalid',
            reason: 'The deal risk is already priced in.',
            links: [],
            weight: 2,
            weight_reason: 'A minor point either way.',
          },
          {
            role: 'decider',
            verdict: 'valid',
            reason: 'The objection is speculation.',
            links: [],
            weight: 2,
            weight_reason: 'Still a side note.',
          },
        ],
      },
    ],
  };
}

function renderResult(result: TieredResult, runDate?: Date | null) {
  render(
    <MemoryRouter>
      <UiLanguageProvider>
        <AltResult result={result} taskId="task-9" runDate={runDate} />
      </UiLanguageProvider>
    </MemoryRouter>,
  );
}

describe('AltResult outlook conclusion', () => {
  it('leads with outlook and action; enter keeps the full levels table', () => {
    renderResult(makeOutlookResult());
    const conclusion = screen.getByTestId('alt-conclusion');
    expect(conclusion).toHaveTextContent(/(展望|Outlook): (看多|Bullish)/);
    expect(conclusion).toHaveTextContent(/(操作|Action): (可建仓|Enter)/);
    expect(screen.getByTestId('alt-levels-table')).toBeInTheDocument();
  });

  it('keep_holding shows only the labeled structural stop', () => {
    renderResult(makeOutlookResult({ outlook: 'bullish', action: 'keep_holding' }));
    expect(screen.queryByTestId('alt-levels-table')).not.toBeInTheDocument();
    const stop = screen.getByTestId('alt-structural-stop');
    expect(stop).toHaveTextContent(/(结构性止损位|Structural stop)/);
    expect(stop).toHaveTextContent('90');
  });

  it('no_trade shows no plan levels at all', () => {
    renderResult(makeOutlookResult({ outlook: 'neutral', action: 'no_trade' }));
    expect(screen.queryByTestId('alt-levels-table')).not.toBeInTheDocument();
    expect(screen.queryByTestId('alt-structural-stop')).not.toBeInTheDocument();
    expect(screen.getByTestId('alt-no-plan')).toBeInTheDocument();
  });

  it('sell_all hides the plan and prints the exit size from the sizing block', () => {
    renderResult(
      makeOutlookResult({
        outlook: 'bearish',
        action: 'sell_all',
        sizing: {
          enabled: true,
          shares: null,
          ownership: 300,
          sell_shares: 300,
          position_value: null,
          risk_amount: null,
          loss_per_share: null,
          lot_size: 1,
          cap_applied: false,
          reason_code: 'not_a_buy',
          refusal_reason: null,
          notes: [],
          inputs: {
            capital: 100000,
            risk_fraction: 0.01,
            max_position_fraction: 0.25,
            fee_fraction: 0,
            entry: null,
            stop_loss: null,
          },
        },
      }),
    );
    expect(screen.getByTestId('alt-no-plan')).toBeInTheDocument();
    // The sell formula prints the full holding with no multiplier term.
    const formula = screen.getByTestId('alt-sell-formula');
    expect(formula).toHaveTextContent('= 300');
    expect(formula).not.toHaveTextContent('×');
    expect(screen.getByText(/(卖出|Sell) 300|300 (股|shares)/)).toBeInTheDocument();
  });

  it('shows the earnings warning only when the date is near', () => {
    renderResult(
      makeOutlookResult({
        earnings: {
          next_date: '2026-07-24',
          days_until: 4,
          warning_days: 7,
          is_near: true,
          note: null,
        },
      }),
    );
    const warning = screen.getByTestId('alt-earnings-warning');
    expect(warning).toHaveTextContent('4');
    expect(warning).toHaveTextContent('2026-07-24');
  });

  it('hides the earnings warning when earnings are far or unknown', () => {
    renderResult(
      makeOutlookResult({
        earnings: {
          next_date: '2026-09-20',
          days_until: 62,
          warning_days: 7,
          is_near: false,
          note: null,
        },
      }),
    );
    expect(screen.queryByTestId('alt-earnings-warning')).not.toBeInTheDocument();
  });

  it('notes a report from a previous trading day; a same-day run has no note', () => {
    const yesterday = new Date();
    yesterday.setDate(yesterday.getDate() - 1);
    renderResult(makeOutlookResult(), yesterday);
    expect(screen.getByTestId('alt-stale-note')).toHaveTextContent(/重跑|re-run/);
  });

  it('a same-day run has no staleness note', () => {
    renderResult(makeOutlookResult(), new Date());
    expect(screen.queryByTestId('alt-stale-note')).not.toBeInTheDocument();
  });

  it('an old stored run (no outlook) has no conclusion block', () => {
    renderResult(makeOutlookResult({ outlook: undefined, action: undefined, risk_card: null }));
    expect(screen.queryByTestId('alt-conclusion')).not.toBeInTheDocument();
  });
});

describe('AltResult risk card', () => {
  it('renders all 13 numbered entries in order', () => {
    renderResult(makeOutlookResult());
    const card = screen.getByTestId('alt-risk-card');
    expect(within(card).getAllByRole('listitem')).toHaveLength(13);
    expect(within(card).getByTestId('alt-risk-card-concentration')).toHaveTextContent(/^1\./);
    expect(within(card).getByTestId('alt-risk-card-ownership_context')).toHaveTextContent(/^13\./);
  });

  it('an ok entry shows value, action and reason; percentages are readable', () => {
    renderResult(makeOutlookResult());
    const entry = screen.getByTestId('alt-risk-card-concentration');
    expect(entry).toHaveTextContent('15.9');
    expect(entry).toHaveTextContent('25');
    expect(entry).toHaveTextContent(/(建议：|Action:)/);
    expect(entry).toHaveTextContent(/(原因：|Why:)/);
  });

  it('a flagged entry is tagged check-this', () => {
    renderResult(makeOutlookResult());
    expect(screen.getByTestId('alt-risk-card-liquidity')).toHaveTextContent(/注意|check this/);
  });

  it('an n/a entry explains why and drops the action/reason lines', () => {
    renderResult(makeOutlookResult());
    const entry = screen.getByTestId('alt-risk-card-ownership_context');
    expect(entry).toHaveTextContent(/未持有|hold no shares/);
    expect(entry).not.toHaveTextContent(/(建议：|Action:)/);
  });
});

describe('AltResult v10 weighted vote tree', () => {
  function renderWeighted() {
    const result = makeOutlookResult({
      depth: 2,
      tier2: {
        tier: 2,
        coverage: 'full',
        direction: 'hold',
        confidence: null,
        score: null,
        levels: LEVELS,
        narrative: 'Weighted to hold.',
        warnings: [],
        debate_detail: makeWeightedDebate(),
      },
    });
    renderResult(result);
  }

  it('shows a clickable weight badge whose modal explains the median', () => {
    renderWeighted();
    const badge = screen.getByTestId('alt-tree-weight-S1');
    expect(badge).toHaveTextContent('2.5');
    fireEvent.click(badge);
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveTextContent(/中位数|median/);
    expect(dialog).toHaveTextContent('3');
  });

  it('a vote modal carries the voter’s own importance rating', () => {
    renderWeighted();
    fireEvent.click(
      within(screen.getByTestId('alt-tree-item-S1')).getByRole('button', { name: '✓' }),
    );
    expect(screen.getByRole('dialog')).toHaveTextContent(/重要性评分：2|importance rating: 2/);
  });

  it('the scores block uses the weighted formula with the weight sums', () => {
    renderWeighted();
    const scores = screen.getByTestId('alt-tree-scores');
    expect(scores).toHaveTextContent(/看多权重和|bullish weight/);
    expect(screen.getByTestId('alt-tree-final-formula')).toHaveTextContent('= 10 × 3 / 5.5');
    expect(scores).toHaveTextContent('= 5.45');
  });
});

describe('AltResult deep-analysis layout', () => {
  it('hides the tier-1 card on a new deep run and shows the trade plan instead', () => {
    renderResult(
      makeOutlookResult({ depth: 2, tier2: makeTier2(makeWeightedDebate()) }),
    );
    expect(screen.queryByTestId('alt-tier1')).not.toBeInTheDocument();
    expect(
      screen.queryByText(/层级 1：初步分析|Tier 1: preliminary analysis/),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/交易计划|Trade plan/)).toBeInTheDocument();
    // action = enter → the plan block carries the full levels table.
    expect(
      within(screen.getByTestId('alt-plan')).getByTestId('alt-levels-table'),
    ).toBeInTheDocument();
    expect(screen.getByTestId('alt-tier2')).toBeInTheDocument();
  });
});

describe('AltResult v11 detail tree', () => {
  function renderRich() {
    renderResult(makeOutlookResult({ depth: 2, tier2: makeTier2(makeRichDebate()) }));
  }

  it('shows the median as a bare number whose modal lists every score', () => {
    renderRich();
    const badge = screen.getByTestId('alt-tree-weight-T1');
    expect(badge).toHaveTextContent(/^4\.5$/);
    fireEvent.click(badge);
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveTextContent(/各方评分：4, 5|Scores: 4, 5/);
    expect(dialog).toHaveTextContent(/中位数：4\.5|Median: 4\.5/);
  });

  it('shows one check per lister; its modal carries validity, score and reason', () => {
    renderRich();
    const marks = within(screen.getByTestId('alt-tree-item-T1')).getAllByRole('button', {
      name: '✓',
    });
    expect(marks).toHaveLength(2); // both listers, no longer hidden
    fireEvent.click(marks[0]);
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveTextContent(/列出者 1|Lister 1/);
    expect(dialog).toHaveTextContent(/有效|valid/i);
    expect(dialog).toHaveTextContent('The 14-day RSI (71.20) is above 70.');
    expect(dialog).toHaveTextContent(/评分：4|Score: 4/);
    expect(dialog).toHaveTextContent('Strong but not decisive.');
  });

  it('a checker ✗ modal shows the objection, then the score and its reason', () => {
    renderRich();
    fireEvent.click(
      within(screen.getByTestId('alt-tree-item-S1')).getByRole('button', { name: '✗' }),
    );
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveTextContent(/核查员|Checker/);
    expect(dialog).toHaveTextContent('The deal risk is already priced in.');
    expect(dialog).toHaveTextContent(/评分：2|Score: 2/);
    expect(dialog).toHaveTextContent('A minor point either way.');
  });

  it('the how-it-works list explains the 1-5 scale', () => {
    renderRich();
    expect(screen.getByTestId('alt-tree-explain')).toHaveTextContent(/1-5/);
  });
});
