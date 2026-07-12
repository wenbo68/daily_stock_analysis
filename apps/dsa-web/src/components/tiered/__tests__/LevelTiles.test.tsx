import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { TieredLevels, TieredLevelsDetail } from '../../../api/tiered';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { LevelTiles } from '../LevelTiles';

const LEVELS: TieredLevels = {
  entry: 96,
  secondary_entry: 94,
  stop_loss: 90,
  take_profit: 108,
};

const DETAIL: TieredLevelsDetail = {
  levels: {
    entry: {
      base: 96,
      formula: 'min(close, max(sma_20, swing_low_20))',
      inputs: { close: 100, sma_20: 96, swing_low_20: 94 },
      adjusted: 94.5,
      reason: 'Pullback support looks stronger at the swing low.',
      evidence: ['technicals.sma_20'],
      rejection: null,
      final: 94.5,
    },
    secondary_entry: {
      base: 94,
      formula: 'max(support strictly below ideal entry: sma_60, swing_low_20)',
      inputs: { ideal_entry: 96, sma_60: 90, swing_low_20: 94 },
      adjusted: null,
      reason: null,
      evidence: [],
      rejection: null,
      final: 94,
    },
    stop_loss: {
      base: 90,
      formula: 'ideal_entry − 2 × atr_14',
      inputs: { ideal_entry: 96, atr_14: 3, multiplier: 2 },
      adjusted: null,
      reason: 'Tighten under the round number.',
      evidence: ['technicals.atr_14'],
      rejection: 'adjustment for stop_loss moves 4.00 from base — outside the ±1 ATR band',
      final: 90,
    },
    take_profit: {
      base: 108,
      formula: 'ideal_entry + 2 × (ideal_entry − stop_loss)',
      inputs: { ideal_entry: 96, stop_loss: 90, reward_risk_multiple: 2 },
      adjusted: null,
      reason: null,
      evidence: [],
      rejection: null,
      final: 108,
    },
  },
  warnings: [],
};

function renderTiles(levelsDetail: TieredLevelsDetail | null) {
  render(
    <UiLanguageProvider>
      <LevelTiles levels={LEVELS} levelsDetail={levelsDetail} citations={[]} />
    </UiLanguageProvider>,
  );
}

describe('LevelTiles', () => {
  it('old stored runs without an audit trail render plain numbers', () => {
    renderTiles(null);
    expect(screen.getByText('96')).toBeInTheDocument();
    expect(screen.getByText('108')).toBeInTheDocument();
    expect(screen.queryByTestId('level-base-entry')).not.toBeInTheDocument();
  });

  it('base number opens the formula modal with plugged-in values', () => {
    renderTiles(DETAIL);
    fireEvent.click(screen.getByTestId('level-base-entry'));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    // the abstract formula appears...
    expect(
      screen.getAllByText('min(close, max(sma_20, swing_low_20))').length,
    ).toBeGreaterThan(0);
    // ...and the version with this run's numbers ("= 96")
    expect(screen.getByText(/= 96/)).toBeInTheDocument();
  });

  it('adjusted number opens the reasoning modal with evidence references', () => {
    renderTiles(DETAIL);
    fireEvent.click(screen.getByTestId('level-adjusted-entry'));
    const dialog = screen.getByRole('dialog');
    expect(dialog).toBeInTheDocument();
    expect(
      screen.getByText('Pullback support looks stronger at the swing low.'),
    ).toBeInTheDocument();
    expect(screen.getByText('technicals.sma_20')).toBeInTheDocument();
  });

  it('a rejected adjustment is visible and explains itself', () => {
    renderTiles(DETAIL);
    fireEvent.click(screen.getByTestId('level-adjusted-stop_loss'));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText(/±1 ATR/)).toBeInTheDocument();
  });

  it('modals close via Escape', () => {
    renderTiles(DETAIL);
    fireEvent.click(screen.getByTestId('level-base-entry'));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
