import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { TieredRunSummary } from '../../../api/tiered';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { AltRunHistory, type AltRunHistoryProps } from '../AltRunHistory';

function makeRun(id: string, overrides: Partial<TieredRunSummary> = {}): TieredRunSummary {
  return {
    task_id: id,
    stock_code: 'AAPL',
    status: 'done',
    error: null,
    created_at: '2026-07-10T04:00:00',
    updated_at: null,
    direction: 'buy',
    shares: 41,
    tier: 1,
    ...overrides,
  };
}

function renderHistory(overrides: Partial<AltRunHistoryProps> = {}) {
  const props: AltRunHistoryProps = {
    runs: [],
    expandedTaskId: null,
    expandedResult: null,
    expandedError: null,
    onToggle: vi.fn(),
    ...overrides,
  };
  render(
    <UiLanguageProvider>
      <AltRunHistory {...props} />
    </UiLanguageProvider>,
  );
  return props;
}

// The date pair renders before the shares pair, and both use Min/Max
// placeholders — index 0 is the date box, index 1 the shares box.
const minBoxes = () => screen.getAllByPlaceholderText(/^下限$|^Min$/);

describe('AltRunHistory', () => {
  it('shows ticker, date, tier, verdict and shares per row', () => {
    renderHistory({
      runs: [
        makeRun('t1', { stock_code: 'MSFT', tier: 3 }),
        makeRun('t2', { stock_code: 'NVDA', status: 'running', direction: null, shares: null, tier: null }),
      ],
    });

    expect(screen.getByText('MSFT')).toBeInTheDocument();
    expect(screen.getAllByText(/^\d{4}\/\d{2}\/\d{2}, \d{2}:\d{2}$/)).toHaveLength(2);
    expect(screen.getByText(/层级 3|Tier 3/)).toBeInTheDocument();
    expect(screen.getByText(/买入|Buy/)).toBeInTheDocument();
    expect(screen.getByText(/41/)).toBeInTheDocument();
    expect(screen.getByText('NVDA')).toBeInTheDocument();
    expect(screen.getByText(/分析中|Running/)).toBeInTheDocument();
    // the running row has neither tier nor shares yet — two dashes
    expect(screen.getAllByText('—')).toHaveLength(2);
  });

  it('offers the tickers seen in history as a multi-pick dropdown filter', () => {
    renderHistory({
      runs: [makeRun('t1', { stock_code: 'MSFT' }), makeRun('t2', { stock_code: 'NVDA' })],
    });

    const tickerBox = screen.getByPlaceholderText(/筛选代码|Filter ticker/);
    fireEvent.focus(tickerBox);
    fireEvent.click(screen.getByRole('button', { name: 'NVDA' }));
    // close the still-open multi-pick dropdown so only rows remain
    fireEvent.mouseDown(document.body);
    expect(screen.queryByText('MSFT')).not.toBeInTheDocument();

    // multi-pick: adding the second ticker brings the other row back
    fireEvent.focus(tickerBox);
    fireEvent.click(screen.getByRole('button', { name: 'MSFT' }));
    fireEvent.mouseDown(document.body);
    expect(screen.getByText('MSFT')).toBeInTheDocument();

    // pills read Label: value and remove on click
    fireEvent.click(screen.getByRole('button', { name: /(Ticker|代码): NVDA/ }));
    fireEvent.click(screen.getByRole('button', { name: /(Ticker|代码): MSFT/ }));
    expect(screen.getByText('NVDA')).toBeInTheDocument();
  });

  it('clears a verdict filter by picking the same option again', () => {
    renderHistory({
      runs: [
        makeRun('t1', { stock_code: 'MSFT', direction: 'buy' }),
        makeRun('t2', { stock_code: 'NVDA', direction: 'hold' }),
      ],
    });

    fireEvent.focus(screen.getByPlaceholderText(/筛选结论|Filter verdict/));
    fireEvent.click(screen.getAllByText(/持有|Hold/)[0]);
    expect(screen.queryByText('MSFT')).not.toBeInTheDocument();

    // the dropdown stays open for multi-pick filters — same option clears
    fireEvent.click(screen.getAllByText(/持有|Hold/)[0]);
    expect(screen.getByText('MSFT')).toBeInTheDocument();
  });

  it('filters by tier from the dropdown', () => {
    renderHistory({
      runs: [
        makeRun('t1', { stock_code: 'MSFT', tier: 1 }),
        makeRun('t2', { stock_code: 'NVDA', tier: 3 }),
      ],
    });

    fireEvent.focus(screen.getByPlaceholderText(/筛选层级|Filter tier/));
    fireEvent.click(screen.getByRole('button', { name: '3' }));

    expect(screen.queryByText('MSFT')).not.toBeInTheDocument();
    expect(screen.getByText('NVDA')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /(Tier|层级): 3/ })).toBeInTheDocument();
  });

  it('filters by a date range (wide bounds keep the row, a future start drops it)', () => {
    renderHistory({ runs: [makeRun('t1', { stock_code: 'MSFT' })] });
    const [dateMin] = minBoxes();
    const [dateMax] = screen.getAllByPlaceholderText(/^上限$|^Max$/);

    fireEvent.change(dateMin, { target: { value: '2026/07/01' } });
    fireEvent.keyDown(dateMin, { key: 'Enter' });
    fireEvent.change(dateMax, { target: { value: '2026/07/31' } });
    fireEvent.keyDown(dateMax, { key: 'Enter' });
    expect(screen.getByText('MSFT')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /2026\/07\/01/ }));
    fireEvent.change(dateMin, { target: { value: '2027/01/01' } });
    fireEvent.keyDown(dateMin, { key: 'Enter' });
    expect(screen.queryByText('MSFT')).not.toBeInTheDocument();
  });

  it('rejects an invalid date instead of committing it', () => {
    renderHistory({ runs: [makeRun('t1', { stock_code: 'MSFT' })] });
    const [dateMin] = minBoxes();

    fireEvent.change(dateMin, { target: { value: 'yesterday' } });
    fireEvent.keyDown(dateMin, { key: 'Enter' });

    expect(dateMin).toHaveValue('yesterday');
    expect(screen.getByText('MSFT')).toBeInTheDocument();
  });

  it('filters by minimum shares', () => {
    renderHistory({
      runs: [
        makeRun('t1', { stock_code: 'MSFT', shares: 5 }),
        makeRun('t2', { stock_code: 'NVDA', shares: 80 }),
      ],
    });
    const sharesMin = minBoxes()[1];

    fireEvent.change(sharesMin, { target: { value: '10' } });
    fireEvent.keyDown(sharesMin, { key: 'Enter' });

    expect(screen.queryByText('MSFT')).not.toBeInTheDocument();
    expect(screen.getByText('NVDA')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /(Shares Min|股数下限): 10/ })).toBeInTheDocument();
  });

  it('pages the list 10 rows at a time with numbered page buttons', () => {
    renderHistory({
      runs: Array.from({ length: 12 }, (_, index) => makeRun(`t${index}`)),
    });

    expect(screen.getAllByText('AAPL')).toHaveLength(10);
    fireEvent.click(screen.getByRole('button', { name: '2' }));
    expect(screen.getAllByText('AAPL')).toHaveLength(2);
    fireEvent.click(screen.getByRole('button', { name: /第一页|First page/ }));
    expect(screen.getAllByText('AAPL')).toHaveLength(10);
  });

  it('clicking a row asks to expand it; a failed expanded row shows its error', () => {
    const props = renderHistory({
      runs: [
        makeRun('t1', { stock_code: 'MSFT' }),
        makeRun('t2', {
          stock_code: 'NVDA',
          status: 'failed',
          direction: null,
          shares: null,
          tier: null,
          error: 'LLM quota exhausted',
        }),
      ],
      expandedTaskId: 't2',
    });

    fireEvent.click(screen.getByRole('button', { name: /MSFT/ }));
    expect(props.onToggle).toHaveBeenCalledWith('t1');
    expect(screen.getByText('LLM quota exhausted')).toBeInTheDocument();
  });
});
