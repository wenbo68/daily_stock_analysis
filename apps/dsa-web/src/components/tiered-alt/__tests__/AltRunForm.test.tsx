import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { AltRunForm, type AltRunFormProps } from '../AltRunForm';

// Assertions use /zh|en/ regexes because the provider picks the runtime
// language, mirroring AltResult.test.tsx.

function renderForm(overrides: Partial<AltRunFormProps> = {}) {
  const props: AltRunFormProps = {
    ticker: null,
    tier: null,
    capital: null,
    riskPct: null,
    reward: null,
    submitting: false,
    error: null,
    onTicker: vi.fn(),
    onTier: vi.fn(),
    onCapital: vi.fn(),
    onRiskPct: vi.fn(),
    onReward: vi.fn(),
    onStart: vi.fn(),
    ...overrides,
  };
  render(
    <UiLanguageProvider>
      <AltRunForm {...props} />
    </UiLanguageProvider>,
  );
  return props;
}

describe('AltRunForm', () => {
  it('commits a typed ticker on Enter and clears the field', () => {
    const props = renderForm();
    const input = screen.getByLabelText(/代码|Ticker/);

    fireEvent.change(input, { target: { value: 'nvda' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    expect(props.onTicker).toHaveBeenCalledWith('nvda');
    expect(input).toHaveValue('');
  });

  it('commits a suggested ticker from the dropdown', () => {
    const props = renderForm();

    fireEvent.focus(screen.getByLabelText(/代码|Ticker/));
    fireEvent.click(screen.getByRole('button', { name: 'AAPL' }));

    expect(props.onTicker).toHaveBeenCalledWith('AAPL');
  });

  it('refuses to start with fields missing and explains in a popup', () => {
    const props = renderForm({ ticker: 'AAPL', tier: 1, capital: null, riskPct: '1' });

    fireEvent.click(screen.getByRole('button', { name: /开始|Start/ }));

    expect(props.onStart).not.toHaveBeenCalled();
    expect(screen.getByText(/五项都需要填写|All five fields are required/)).toBeInTheDocument();
  });

  it('shows selections as Label: value pills; clicking a pill removes it', () => {
    const props = renderForm({
      ticker: 'AAPL', tier: 1, capital: '100000', riskPct: '1', reward: '2',
    });

    fireEvent.click(screen.getByRole('button', { name: /开始|Start/ }));
    expect(props.onStart).toHaveBeenCalled();

    // capital carries the ticker's market currency; risk carries the % sign
    fireEvent.click(screen.getByRole('button', { name: /(Capital|本金): 100000 USD/ }));
    expect(props.onCapital).toHaveBeenCalledWith(null);

    fireEvent.click(screen.getByRole('button', { name: /(Risk|单笔风险): 1%/ }));
    expect(props.onRiskPct).toHaveBeenCalledWith(null);

    fireEvent.click(screen.getByRole('button', { name: /(Ticker|代码): AAPL/ }));
    expect(props.onTicker).toHaveBeenCalledWith(null);

    fireEvent.click(screen.getByRole('button', { name: /(Tier|层级): 1/ }));
    expect(props.onTier).toHaveBeenCalledWith(null);
  });

  it('blocks picking a capital before a ticker and explains in a popup', () => {
    const props = renderForm();
    const capitalBox = screen.getByPlaceholderText(/输入本金|Enter capital/);

    fireEvent.change(capitalBox, { target: { value: '50000' } });
    fireEvent.keyDown(capitalBox, { key: 'Enter' });

    expect(props.onCapital).not.toHaveBeenCalled();
    expect(screen.getByText(/请先选择股票代码|Pick a ticker first/)).toBeInTheDocument();
  });

  it("labels capital with the ticker market's currency", () => {
    renderForm({ ticker: 'hk00700', capital: '50000' });

    expect(screen.getByText(/(Capital|本金): HKD/)).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /(Capital|本金): 50000 HKD/ }),
    ).toBeInTheDocument();
  });

  it('requires the reward ratio like every other field', () => {
    const props = renderForm({
      ticker: 'AAPL', tier: 1, capital: '100000', riskPct: '1', reward: null,
    });

    fireEvent.click(screen.getByRole('button', { name: /开始|Start/ }));

    expect(props.onStart).not.toHaveBeenCalled();
    expect(screen.getByText(/五项都需要填写|All five fields are required/)).toBeInTheDocument();
  });

  it('shows the reward pill and clicking it removes it', () => {
    const props = renderForm({
      ticker: 'AAPL', tier: 1, capital: '100000', riskPct: '1', reward: '3',
    });

    fireEvent.click(screen.getByRole('button', { name: /开始|Start/ }));
    expect(props.onStart).toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: /(Reward|盈亏比): 3×/ }));
    expect(props.onReward).toHaveBeenCalledWith(null);
  });

  it('accepts a fractional ratio above 1 but rejects 1 or less', () => {
    const props = renderForm({ ticker: 'AAPL' });
    const box = screen.getByPlaceholderText(/输入盈亏比|Enter ratio/);

    fireEvent.change(box, { target: { value: '1' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(props.onReward).not.toHaveBeenCalled();

    fireEvent.change(box, { target: { value: '2.5' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(props.onReward).toHaveBeenCalledWith('2.5');
  });

  it('names the tier options after their analyses and clears on re-pick', () => {
    const props = renderForm({ tier: 2 });

    fireEvent.focus(screen.getByPlaceholderText(/输入层级|Enter tier/));
    fireEvent.click(
      screen.getByRole('button', { name: /2: deep analysis|2：深度分析/ }),
    );

    expect(props.onTier).toHaveBeenCalledWith(null);
    expect(
      screen.getByRole('button', { name: /1: preliminary analysis|1：初步分析/ }),
    ).toBeInTheDocument();
  });
});
