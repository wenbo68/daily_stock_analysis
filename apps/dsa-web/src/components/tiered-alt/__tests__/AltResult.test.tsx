import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import type { TieredLevelsDetail, TieredResult, TieredTierSection } from '../../../api/tiered';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { AltResult } from '../AltResult';

const LEVELS = { entry: 96, secondary_entry: 94, stop_loss: 90, take_profit: 108 };

// Consistent with LEVELS: entry and target were adjusted by the AI, the
// backup entry and the stop kept their computed bases.
const LEVELS_DETAIL: TieredLevelsDetail = {
  levels: {
    entry: {
      base: 95,
      formula: 'min(close, max(sma_20, swing_low_20))',
      inputs: { close: 100, sma_20: 95, swing_low_20: 92 },
      adjusted: 96,
      reason: 'Momentum supports paying up a little.',
      evidence: ['technicals.sma_20'],
      rejection: null,
      final: 96,
    },
    secondary_entry: {
      base: 94,
      formula: 'max(support strictly below ideal entry: sma_60, swing_low_20)',
      inputs: { ideal_entry: 95, sma_60: 94, swing_low_20: 92 },
      adjusted: null,
      reason: null,
      evidence: [],
      rejection: null,
      final: 94,
    },
    stop_loss: {
      base: 90,
      formula: 'ideal_entry − 2 × atr_14',
      inputs: { ideal_entry: 95, atr_14: 2.5, multiplier: 2 },
      adjusted: null,
      reason: null,
      evidence: [],
      rejection: null,
      final: 90,
    },
    take_profit: {
      base: 105,
      formula: 'ideal_entry + 2 × (ideal_entry − stop_loss)',
      inputs: { ideal_entry: 95, stop_loss: 90, reward_risk_multiple: 2 },
      adjusted: 108,
      reason: 'Growth supports a higher target.',
      evidence: [],
      rejection: null,
      final: 108,
    },
  },
  warnings: [],
};

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
    levels_detail: LEVELS_DETAIL,
    depth: 3,
    final: { tier: 3, direction: 'hold', coverage: 'full', confidence: null, levels: LEVELS },
    tier2: { ...makeSection(2, 'hold'), debate_detail: { turns: [], verdict: null, warnings: [] } },
    tier3: {
      ...makeSection(3, 'hold'),
      risk_detail: {
        takes: [],
        verdict: {
          stance: 'hold',
          size_multiplier: 0.5,
          confidence: 0.7,
          stop_advice: 'keep',
          tightened_stop: null,
          summary: 'Risk summary.',
          key_risks: [],
        },
        warnings: [],
      },
    },
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
    <MemoryRouter>
      <UiLanguageProvider>
        <AltResult result={result} taskId="task-9" />
      </UiLanguageProvider>
    </MemoryRouter>,
  );
}

describe('AltResult', () => {
  it('renders a depth-1 (old) run: dimensions and tier 1 only, no shares block', () => {
    renderResult(makeV1Result());
    expect(screen.getAllByTestId(/alt-dimension-/)).toHaveLength(4);
    expect(screen.getByTestId('alt-tier1')).toBeInTheDocument();
    expect(screen.queryByTestId('alt-tier2')).not.toBeInTheDocument();
    expect(screen.queryByTestId('alt-tier3')).not.toBeInTheDocument();
    // no sizing block recorded → no shares-computation block at all
    expect(screen.queryByTestId('alt-shares-computation')).not.toBeInTheDocument();
    // the obsolete symbol/verdict hero is gone — the row already says both
    expect(screen.queryByText('AAPL')).not.toBeInTheDocument();
    // no audit trail on old runs → the table falls back to the stored values
    expect(screen.getByTestId('alt-levels-table')).toHaveTextContent('96');
  });

  it('keeps the blocks in the fixed order with their titles above the cards', () => {
    renderResult(makeDeepResult());
    const ids = Array.from(document.querySelectorAll('[data-testid]'))
      .map((el) => el.getAttribute('data-testid') ?? '')
      .filter(
        (id) =>
          ['alt-tier1', 'alt-tier2', 'alt-tier3', 'alt-shares-computation'].includes(id) ||
          id === 'alt-dimension-technicals',
      );
    expect(ids).toEqual([
      'alt-dimension-technicals',
      'alt-tier1',
      'alt-tier2',
      'alt-tier3',
      'alt-shares-computation',
    ]);
    expect(screen.getByText(/四维数据报告|Four-dimension reports/)).toBeInTheDocument();
    expect(screen.getByText(/层级 1：初步立场|Tier 1: preliminary stance/)).toBeInTheDocument();
    expect(screen.getByText(/层级 2：立场辩论|Tier 2: position debate/)).toBeInTheDocument();
    expect(screen.getByText(/层级 3：风险辩论|Tier 3: risk debate/)).toBeInTheDocument();
    expect(screen.getByText(/股数计算|Shares computation/)).toBeInTheDocument();
  });

  it('shows the tier-1 levels as a computed/adjusted table', () => {
    renderResult(makeDeepResult());
    // computed row on top, one clickable base per level
    expect(screen.getByTestId('alt-level-computed-entry')).toHaveTextContent('95');
    expect(screen.getByTestId('alt-level-computed-secondary_entry')).toHaveTextContent('94');
    expect(screen.getByTestId('alt-level-computed-stop_loss')).toHaveTextContent('90');
    expect(screen.getByTestId('alt-level-computed-take_profit')).toHaveTextContent('105');
    // adjusted row: moved levels show the new number, untouched ones "keep"
    expect(screen.getByTestId('alt-level-adjusted-entry')).toHaveTextContent('96');
    expect(screen.getByTestId('alt-level-adjusted-take_profit')).toHaveTextContent('108');
    expect(screen.getAllByTestId(/alt-level-keep-/)).toHaveLength(2);
    // the old explainer texts around the levels are gone
    expect(screen.queryByText(/价格参考位|Price levels/)).not.toBeInTheDocument();
    expect(screen.queryByText(/资金管理|money-management/)).not.toBeInTheDocument();
  });

  it('clicking a computed level opens its formula with every number linked to a source', () => {
    renderResult(makeDeepResult());
    fireEvent.click(screen.getByTestId('alt-level-computed-stop_loss'));
    const dialog = screen.getByRole('dialog');
    // title in the `<level>: formula` shape
    expect(within(dialog).getByRole('heading')).toHaveTextContent(/(止损：公式|Stop loss: formula)/);
    // the formula in words (variables without underscores), plugged in, result
    expect(within(dialog).getByTestId('alt-formula-words').textContent).toBe(
      'ideal entry − 2 × atr 14',
    );
    // ideal entry came from the computed entry cell, atr 14 from technicals
    expect(within(dialog).getByRole('button', { name: 'ideal entry' })).toHaveTextContent('95');
    expect(within(dialog).getByRole('button', { name: 'atr 14' })).toHaveTextContent('2.50');
    expect(within(dialog).getByText('= 90')).toBeInTheDocument();
  });

  it('renders the backup entry formula as a max over the supports below the ideal entry', () => {
    renderResult(makeDeepResult());
    fireEvent.click(screen.getByTestId('alt-level-computed-secondary_entry'));
    const dialog = screen.getByRole('dialog');
    // a clean max(...) — never the stored prose string
    expect(within(dialog).getByTestId('alt-formula-words').textContent).toBe(
      'max(sma 60, swing low 20)',
    );
    expect(within(dialog).queryByText(/strictly below/)).not.toBeInTheDocument();
    // the filter condition carries the ideal entry as a link
    expect(within(dialog).getByRole('button', { name: 'ideal entry' })).toHaveTextContent('95');
    // both candidates sit below 95, so both are plugged in
    expect(within(dialog).getByTestId('alt-formula-plugged').textContent).toBe('= max(94, 92)');
    expect(within(dialog).getByText('= 94')).toBeInTheDocument();
  });

  it('clicking an adjusted level opens the AI reason with its references, nothing else', () => {
    renderResult(makeDeepResult());
    fireEvent.click(screen.getByTestId('alt-level-adjusted-entry'));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText('Momentum supports paying up a little.')).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'technicals.sma_20' })).toBeInTheDocument();
    // the inputs table and the reference explainer were removed
    expect(within(dialog).queryByText(/^(输入项|Inputs)$/)).not.toBeInTheDocument();
  });

  it('expands the shares computation to numbers that all exist in the report', () => {
    renderResult(makeDeepResult());
    const formula = screen.getByTestId('alt-shares-formula');
    expect(formula.textContent).toBe('= 100000 × 1% × 0.5 / (96 − 90)');
    // each number links back to where it appears within this run entry
    expect(within(formula).getByRole('button', { name: '100000' })).toBeInTheDocument();
    expect(within(formula).getByRole('button', { name: '1%' })).toBeInTheDocument();
    expect(within(formula).getByRole('button', { name: '0.5' })).toBeInTheDocument();
    expect(within(formula).getByRole('button', { name: '96' })).toBeInTheDocument();
    expect(within(formula).getByRole('button', { name: '90' })).toBeInTheDocument();
    expect(screen.getByText(/= 83/)).toBeInTheDocument();
  });

  it('shows the refusal reason instead of a formula when nothing was computed', () => {
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
    expect(screen.queryByTestId('alt-shares-formula')).not.toBeInTheDocument();
    expect(screen.getByTestId('alt-shares-computation').textContent).not.toBe('');
  });

  it('renders citation evidence as sentiment.citation:N in link colors', () => {
    const deep = makeDeepResult();
    const sentiment = deep.dimensions.find((d) => d.dimension === 'sentiment')!;
    sentiment.citations = [
      { source_name: 'news', title: 'Some article', url: 'https://example.com/a', snippet: null },
    ];
    deep.tier2!.debate_detail!.verdict = {
      direction: 'hold',
      confidence: 0.6,
      summary: 'Summary.',
      reasons_for: [{ claim: 'Bull claim', evidence: ['citation:1'] }],
      reasons_against: [],
      would_change_mind: null,
    };
    renderResult(deep);
    const ref = screen.getByText('sentiment.citation:1');
    expect(ref.tagName).toBe('A');
    expect(ref).toHaveAttribute('href', 'https://example.com/a');
    expect(ref.className).toContain('text-blue-400');
  });

  it('lists non-link sources above link sources under one Sources title', () => {
    const result = makeV1Result();
    result.dimensions[1].citations = [
      { source_name: 'SEC EDGAR', title: 'SEC EDGAR companyfacts', url: 'https://sec.gov/x', snippet: null },
      { source_name: 'Yahoo Finance summary (yfinance)', title: null, url: null, snippet: null },
    ];
    renderResult(result);
    const card = screen.getByTestId('alt-dimension-fundamentals');
    expect(within(card).getByText(/^(来源|Sources)$/)).toBeInTheDocument();
    const items = within(card).getAllByRole('listitem');
    expect(items[0]).toHaveTextContent('Yahoo Finance summary (yfinance)');
    // link sources are listed as their URL, not their headline
    expect(items[1]).toHaveTextContent('https://sec.gov/x');
    expect(items[1]).not.toHaveTextContent('SEC EDGAR companyfacts');
  });

  it('shows verdict, size, stop loss and score as plain Label: value facts', () => {
    renderResult(makeDeepResult());
    const tier3 = screen.getByTestId('alt-tier3');
    // no pill anymore — the verdict is text like every other fact
    expect(tier3).toHaveTextContent(/(结论|Verdict): (持有|Hold)/);
    expect(tier3).toHaveTextContent(/(仓位|Size): 0.5x/);
    expect(tier3).toHaveTextContent(/(止损|Stop loss): (维持|keep)/);
    // judge confidence 0.7 → a whole number out of 10
    expect(tier3).toHaveTextContent(/(评分|Score): 7\/10/);
    const tier1 = screen.getByTestId('alt-tier1');
    expect(tier1).toHaveTextContent(/(结论|Verdict): (买入|Buy)/);
    // tier 1's stored score is a bullishness composite, not a judge
    // confidence — it is not shown as "Score"
    expect(tier1).not.toHaveTextContent(/评分|Score/);
  });

  it('links the recorded signal number straight to that signal', () => {
    const deep = {
      ...makeDeepResult(),
      signal: { logged: true, signal_id: 32, created: true, reason: null },
    };
    renderResult(deep);
    const link = screen.getByRole('link', { name: /#32/ });
    expect(link).toHaveAttribute('href', '/decision-signals?signal=32');
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
