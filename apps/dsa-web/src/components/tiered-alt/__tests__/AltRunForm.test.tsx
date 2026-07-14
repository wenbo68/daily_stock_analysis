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
    submitting: false,
    error: null,
    onTicker: vi.fn(),
    onTier: vi.fn(),
    onCapital: vi.fn(),
    onRiskPct: vi.fn(),
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

  it('keeps Start disabled until a ticker pill exists, then starts on click', () => {
    renderForm();
    expect(screen.getByRole('button', { name: /开始|Start/ })).toBeDisabled();
  });

  it('shows selections as Label: value pills; clicking a pill removes it', () => {
    const props = renderForm({ ticker: 'AAPL', tier: 1, capital: '100000' });

    const start = screen.getByRole('button', { name: /开始|Start/ });
    expect(start).toBeEnabled();
    fireEvent.click(start);
    expect(props.onStart).toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: /(Ticker|代码): AAPL/ }));
    expect(props.onTicker).toHaveBeenCalledWith(null);

    fireEvent.click(screen.getByRole('button', { name: /(Tier|层级): 1/ }));
    expect(props.onTier).toHaveBeenCalledWith(null);

    fireEvent.click(screen.getByRole('button', { name: /(Capital|本金): 100000/ }));
    expect(props.onCapital).toHaveBeenCalledWith(null);
  });

  it('clears a selection when its dropdown option is picked again', () => {
    const props = renderForm({ tier: 2 });

    fireEvent.focus(screen.getByPlaceholderText(/选择层级|Select tier/));
    fireEvent.click(screen.getByRole('button', { name: '2' }));

    expect(props.onTier).toHaveBeenCalledWith(null);
  });
});
