import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { DepthSelector } from '../DepthSelector';

function renderSelector(value: 1 | 2 | 3 = 1, disabled = false) {
  const onChange = vi.fn();
  render(
    <UiLanguageProvider>
      <DepthSelector value={value} onChange={onChange} disabled={disabled} />
    </UiLanguageProvider>,
  );
  return { onChange };
}

describe('DepthSelector', () => {
  it('renders the three depth options as a radio group', () => {
    renderSelector();
    const options = screen.getAllByRole('radio');
    expect(options).toHaveLength(3);
    expect(options[0]).toHaveAttribute('aria-checked', 'true');
    expect(options[1]).toHaveAttribute('aria-checked', 'false');
    expect(options[2]).toHaveAttribute('aria-checked', 'false');
  });

  it('marks the current depth as selected', () => {
    renderSelector(3);
    const options = screen.getAllByRole('radio');
    expect(options[2]).toHaveAttribute('aria-checked', 'true');
    expect(options[0]).toHaveAttribute('aria-checked', 'false');
  });

  it('reports the clicked depth', () => {
    const { onChange } = renderSelector(1);
    fireEvent.click(screen.getAllByRole('radio')[1]);
    expect(onChange).toHaveBeenCalledWith(2);
    fireEvent.click(screen.getAllByRole('radio')[2]);
    expect(onChange).toHaveBeenCalledWith(3);
  });

  it('ignores clicks while disabled', () => {
    const { onChange } = renderSelector(1, true);
    fireEvent.click(screen.getAllByRole('radio')[2]);
    expect(onChange).not.toHaveBeenCalled();
  });
});
