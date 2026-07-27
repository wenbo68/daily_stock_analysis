import { useMemo, useState } from 'react';
import type { TieredMetricFormula } from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiLanguage } from '../../i18n/uiText';
import { metricEntry } from '../../i18n/metricLabels';
import { cn } from '../../utils/cn';
import { formatValue, jumpToMetric } from '../tiered/termHelpers';
import { ALT_LINK, FORMULA_LINE, FORMULA_RESULT } from './altStyles';
import { AltModal, FVar } from './AltUi';

// A technicals metric value with its computation receipt: clicking the
// number opens the three-line receipt the trade-plan levels use — the
// formula in words, the formula with this run's numbers plugged in
// (numbers that are payload rows link back to their row), and the result.

// Inputs that ARE payload rows on the same card — their plugged numbers
// jump to that row, so every number in a receipt points at a place it
// already appears (the levels-table rule).
const INPUT_ROW_PATH: Record<string, string> = {
  close: 'technicals.price.close',
  high_1y: 'technicals.price.high_1y',
  sma_50: 'technicals.daily.sma_50',
  atr_14: 'technicals.volatility.atr_14',
  avg_vol_60d: 'technicals.volume.avg_vol_60d',
};

// On-screen names for receipt-only ingredients (values the formula needs
// that are not published as rows) — never raw underscore tokens.
const HELPER_VAR_LABEL: Record<string, string> = {
  close_5d_ago: 'close 5 days ago',
  low_1y: 'lowest (1y)',
  sma_10w: '10-week average',
  avg_gain_14: 'avg gain (14d)',
  avg_loss_14: 'avg loss (14d)',
  avg_vol_5: 'avg volume (5d)',
  stock_return_3m: 'stock return (3m)',
  index_return_3m: 'index return (3m)',
  worst_close: 'worst-day close',
  prev_close: 'previous close',
};

const varLabel = (key: string, language: UiLanguage): string =>
  metricEntry(key, language)?.short ?? HELPER_VAR_LABEL[key] ?? key.replace(/_/g, ' ');

// Split the formula on its input tokens (longest first, so `close` never
// eats into `close_5d_ago`) — the AltLevels splitter, minus its prose
// expansion, which technicals receipts don't need.
const splitOnInputs = (formula: string, inputs: Record<string, number>): string[] => {
  const keys = Object.keys(inputs).sort((a, b) => b.length - a.length);
  if (keys.length === 0) {
    return [formula];
  }
  return formula.split(new RegExp(`(${keys.join('|')})`, 'g'));
};

// Plugged numbers: big volumes as "48.10 million", everything else with
// its meaningful decimals kept (an RSI average gain is 0.1017, which
// formatValue's toFixed(2) would flatten to 0.10).
const formatInput = (value: number): string => {
  if (Math.abs(value) >= 1e6) {
    return formatValue(value);
  }
  return String(Number(value.toFixed(4)));
};

interface AltMetricValueProps {
  /** The payload key of the metric ("rsi_14") — names the modal. */
  term: string;
  value: unknown;
  formula: TieredMetricFormula;
}

export const AltMetricValue = ({ term, value, formula }: AltMetricValueProps) => {
  const { t, language } = useUiLanguage();
  const [isOpen, setIsOpen] = useState(false);
  const close = () => setIsOpen(false);
  const parts = useMemo(
    () => splitOnInputs(formula.formula, formula.inputs),
    [formula],
  );
  const hasInputs = Object.keys(formula.inputs).length > 0;
  const label = metricEntry(term, language)?.short ?? term;

  return (
    <>
      <button
        type="button"
        data-testid={`alt-metric-formula-${term}`}
        onClick={() => setIsOpen(true)}
        className={cn('cursor-pointer tabular-nums', ALT_LINK)}
      >
        {formatValue(value)}
      </button>
      <AltModal
        isOpen={isOpen}
        title={t('tiered.levelModal.formulaTitle', { level: label })}
        onClose={close}
        // Fit the widest receipt line; each line stays a single line.
        panelClassName="w-fit min-w-72 max-w-[95vw]"
      >
        <div className="flex flex-col gap-2 overflow-x-auto text-sm" data-testid="alt-metric-formula-modal">
          <p className={FORMULA_LINE}>
            {parts.map((part, index) =>
              formula.inputs[part] === undefined ? (
                <span key={index}>{part}</span>
              ) : (
                <FVar key={index}>{varLabel(part, language)}</FVar>
              ),
            )}
          </p>
          {hasInputs ? (
            <p className={FORMULA_LINE}>
              {'= '}
              {parts.map((part, index) => {
                const input = formula.inputs[part];
                if (input === undefined) {
                  return <span key={index}>{part}</span>;
                }
                const rowPath = INPUT_ROW_PATH[part];
                if (!rowPath) {
                  return (
                    <span key={index} className="tabular-nums">
                      {formatInput(input)}
                    </span>
                  );
                }
                return (
                  <button
                    key={index}
                    type="button"
                    aria-label={varLabel(part, language)}
                    className={cn('cursor-pointer tabular-nums', ALT_LINK)}
                    onClick={() => {
                      close();
                      // Let the modal unmount before scrolling to the row.
                      window.setTimeout(() => jumpToMetric(rowPath), 50);
                    }}
                  >
                    {formatInput(input)}
                  </button>
                );
              })}
            </p>
          ) : null}
          <p className={FORMULA_RESULT}>= {formatValue(value)}</p>
        </div>
      </AltModal>
    </>
  );
};
