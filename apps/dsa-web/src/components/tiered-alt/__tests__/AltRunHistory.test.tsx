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

describe('AltRunHistory', () => {
  it('shows ticker, verdict and shares per row; running rows show a status tag and a dash', () => {
    renderHistory({
      runs: [
        makeRun('t1', { stock_code: 'MSFT' }),
        makeRun('t2', { stock_code: 'NVDA', status: 'running', direction: null, shares: null }),
      ],
    });

    expect(screen.getByText('MSFT')).toBeInTheDocument();
    expect(screen.getByText(/买入|Buy/)).toBeInTheDocument();
    expect(screen.getByText(/41/)).toBeInTheDocument();
    expect(screen.getByText('NVDA')).toBeInTheDocument();
    expect(screen.getByText(/分析中|Running/)).toBeInTheDocument();
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('filters by ticker the moment the text is entered, and the pill removes it', () => {
    renderHistory({
      runs: [makeRun('t1', { stock_code: 'MSFT' }), makeRun('t2', { stock_code: 'NVDA' })],
    });
    const input = screen.getByPlaceholderText(/hk00700/);

    fireEvent.change(input, { target: { value: 'nv' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(screen.queryByText('MSFT')).not.toBeInTheDocument();
    expect(screen.getByText('NVDA')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'nv' }));
    expect(screen.getByText('MSFT')).toBeInTheDocument();
  });

  it('filters by verdict from the dropdown', () => {
    renderHistory({
      runs: [
        makeRun('t1', { stock_code: 'MSFT', direction: 'buy' }),
        makeRun('t2', { stock_code: 'NVDA', direction: 'hold' }),
      ],
    });

    fireEvent.focus(screen.getByLabelText(/结论|Verdict/));
    fireEvent.click(screen.getAllByText(/持有|Hold/)[0]);

    expect(screen.queryByText('MSFT')).not.toBeInTheDocument();
    expect(screen.getByText('NVDA')).toBeInTheDocument();
  });

  it('filters by a date range (wide bounds keep the row, a future start drops it)', () => {
    renderHistory({ runs: [makeRun('t1', { stock_code: 'MSFT' })] });
    const startInput = screen.getByPlaceholderText(/^开始$|^Start$/);
    const endInput = screen.getByPlaceholderText(/^结束$|^End$/);

    fireEvent.change(startInput, { target: { value: '2026/07/01' } });
    fireEvent.keyDown(startInput, { key: 'Enter' });
    fireEvent.change(endInput, { target: { value: '2026/07/31' } });
    fireEvent.keyDown(endInput, { key: 'Enter' });
    expect(screen.getByText('MSFT')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /2026\/07\/01/ }));
    fireEvent.change(startInput, { target: { value: '2027/01/01' } });
    fireEvent.keyDown(startInput, { key: 'Enter' });
    expect(screen.queryByText('MSFT')).not.toBeInTheDocument();
  });

  it('rejects an invalid date instead of committing it', () => {
    renderHistory({ runs: [makeRun('t1', { stock_code: 'MSFT' })] });
    const startInput = screen.getByPlaceholderText(/^开始$|^Start$/);

    fireEvent.change(startInput, { target: { value: 'yesterday' } });
    fireEvent.keyDown(startInput, { key: 'Enter' });

    expect(startInput).toHaveValue('yesterday');
    expect(screen.getByText('MSFT')).toBeInTheDocument();
  });

  it('filters by minimum shares', () => {
    renderHistory({
      runs: [
        makeRun('t1', { stock_code: 'MSFT', shares: 5 }),
        makeRun('t2', { stock_code: 'NVDA', shares: 80 }),
      ],
    });
    const minInput = screen.getByPlaceholderText(/最少|Min/);

    fireEvent.change(minInput, { target: { value: '10' } });
    fireEvent.keyDown(minInput, { key: 'Enter' });

    expect(screen.queryByText('MSFT')).not.toBeInTheDocument();
    expect(screen.getByText('NVDA')).toBeInTheDocument();
  });

  it('pages the list 15 rows at a time', () => {
    renderHistory({
      runs: Array.from({ length: 20 }, (_, index) => makeRun(`t${index}`)),
    });

    expect(screen.getAllByText('AAPL')).toHaveLength(15);
    fireEvent.click(screen.getByRole('button', { name: /下一页|Next page/ }));
    expect(screen.getAllByText('AAPL')).toHaveLength(5);
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
