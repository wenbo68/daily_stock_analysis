import { useMemo, useState, type ReactNode } from 'react';
import type { TieredMetricFormula } from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiLanguage } from '../../i18n/uiText';
import { metricEntry } from '../../i18n/metricLabels';
import { cn } from '../../utils/cn';
import { formatValue, jumpToMetric } from '../tiered/termHelpers';
import { ALT_LINK, FORMULA_LINE, FORMULA_RESULT } from './altStyles';
import { AltModal, FVar } from './AltUi';

// A technicals metric value with its computation receipt: clicking the
// value (a number OR a rule-derived label like "bullish") opens the
// three-line receipt the trade-plan levels use — the formula/rule in
// words, this run's ingredients, and the result. Two plugged-line styles,
// picked by inspecting the words (see TieredMetricFormula in api/tiered):
// substitution (numbers replace their tokens in place) or an
// "ingredient = value" list (rules whose ingredients are words).

// Inputs that ARE payload rows on the same card — their plugged numbers
// jump to that row, so every number in a receipt points at a place it
// already appears (the levels-table rule).
const INPUT_ROW_PATH: Record<string, string> = {
  close: 'technicals.price.close',
  high_1y: 'technicals.price.high_1y',
  sma_50: 'technicals.daily.sma_50',
  atr_14: 'technicals.volatility.atr_14',
  avg_vol_60d: 'technicals.volume.avg_vol_60d',
  rsi_14: 'technicals.daily.rsi_14',
  rs_3m: 'technicals.relative_strength.rs_3m',
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
  index_close: 'index close',
  index_sma_200: 'index 200-day average',
  index_range_pct: 'index position in 1y range (%)',
  rs_1m: 'vs index (1m)',
  ma_stack: 'moving-average check',
  pivot_structure: 'pivot structure',
  macd_hist: 'MACD histogram',
  macd_line: 'MACD line',
  atr_20_bars_ago: 'atr 14 (20 days ago)',
};

const varLabel = (key: string, language: UiLanguage): string =>
  metricEntry(key, language)?.short ?? HELPER_VAR_LABEL[key] ?? key.replace(/_/g, ' ');

// Split the formula on its input tokens (longest first, so `close` never
// eats into `close_5d_ago`) — the AltLevels splitter, minus its prose
// expansion, which technicals receipts don't need.
const splitOnInputs = (formula: string, inputs: TieredMetricFormula['inputs']): string[] => {
  const keys = Object.keys(inputs).sort((a, b) => b.length - a.length);
  if (keys.length === 0) {
    return [formula];
  }
  return formula.split(new RegExp(`(${keys.join('|')})`, 'g'));
};

// Plugged numbers: big volumes as "48.10 million", everything else with
// its meaningful decimals kept (an RSI average gain is 0.1017, which
// formatValue's toFixed(2) would flatten to 0.10). Word ingredients
// ("up", "sideways") pass through.
const formatInput = (value: number | string): string => {
  if (typeof value === 'string') {
    return value;
  }
  if (Math.abs(value) >= 1e6) {
    return formatValue(value);
  }
  return String(Number(value.toFixed(4)));
};

interface PluggedValueProps {
  inputKey: string;
  value: number | string;
  onNavigate: () => void;
}

// One plugged ingredient value — linking back to its payload row when it
// has one, plain otherwise.
const PluggedValue = ({ inputKey, value, onNavigate }: PluggedValueProps) => {
  const { language } = useUiLanguage();
  const rowPath = INPUT_ROW_PATH[inputKey];
  if (!rowPath) {
    return <span className="tabular-nums">{formatInput(value)}</span>;
  }
  return (
    <button
      type="button"
      aria-label={varLabel(inputKey, language)}
      className={cn('cursor-pointer tabular-nums', ALT_LINK)}
      onClick={() => {
        onNavigate();
        // Let the modal unmount before scrolling to the row.
        window.setTimeout(() => jumpToMetric(rowPath), 50);
      }}
    >
      {formatInput(value)}
    </button>
  );
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
  const entries = Object.entries(formula.inputs);
  // Substitution style: every ingredient token appears in the words, so
  // the plugged line can replace them in place. Otherwise the ingredients
  // are listed as "name = value" pairs (rule receipts).
  const isSubstituted =
    entries.length > 0 && entries.every(([key]) => formula.formula.includes(key));
  const parts = useMemo(
    () => splitOnInputs(formula.formula, formula.inputs),
    [formula],
  );
  const label = metricEntry(term, language)?.short ?? term;

  let plugged: ReactNode = null;
  if (isSubstituted) {
    plugged = (
      <p className={FORMULA_LINE}>
        {'= '}
        {parts.map((part, index) => {
          const input = formula.inputs[part];
          return input === undefined ? (
            <span key={index}>{part}</span>
          ) : (
            <PluggedValue key={index} inputKey={part} value={input} onNavigate={close} />
          );
        })}
      </p>
    );
  } else if (entries.length > 0) {
    plugged = (
      <p className={FORMULA_LINE}>
        {entries.map(([key, input], index) => (
          <span key={key}>
            {index > 0 ? '; ' : ''}
            <FVar>{varLabel(key, language)}</FVar>
            {' = '}
            <PluggedValue inputKey={key} value={input} onNavigate={close} />
          </span>
        ))}
      </p>
    );
  }

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
          {plugged}
          <p className={FORMULA_RESULT}>= {formatValue(value)}</p>
        </div>
      </AltModal>
    </>
  );
};
