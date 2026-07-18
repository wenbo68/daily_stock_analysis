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
    ownership: null,
    submitting: false,
    error: null,
    onTicker: vi.fn(),
    onTier: vi.fn(),
    onCapital: vi.fn(),
    onRiskPct: vi.fn(),
    onOwnership: vi.fn(),
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
    expect(screen.getByText(/四项都需要填写|All four fields are required/)).toBeInTheDocument();
  });

  it('shows selections as Label: value pills; clicking a pill removes it', () => {
    const props = renderForm({ ticker: 'AAPL', tier: 1, capital: '100000', riskPct: '1' });

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

  it('treats ownership as optional and shows a removable pill when set', () => {
    const props = renderForm({
      ticker: 'AAPL', tier: 1, capital: '100000', riskPct: '1', ownership: '300',
    });

    // Start works with or without ownership — it is the optional field.
    fireEvent.click(screen.getByRole('button', { name: /开始|Start/ }));
    expect(props.onStart).toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: /(Ownership|持仓): 300/ }));
    expect(props.onOwnership).toHaveBeenCalledWith(null);
  });

  it('rejects a fractional ownership entry', () => {
    const props = renderForm({ ticker: 'AAPL' });
    const box = screen.getByPlaceholderText(/已持有股数|Shares held/);

    fireEvent.change(box, { target: { value: '10.5' } });
    fireEvent.keyDown(box, { key: 'Enter' });

    expect(props.onOwnership).not.toHaveBeenCalled();
  });

  it('clears a selection when its dropdown option is picked again', () => {
    const props = renderForm({ tier: 2 });

    fireEvent.focus(screen.getByPlaceholderText(/选择层级|Select tier/));
    fireEvent.click(screen.getByRole('button', { name: '2' }));

    expect(props.onTier).toHaveBeenCalledWith(null);
  });
});
