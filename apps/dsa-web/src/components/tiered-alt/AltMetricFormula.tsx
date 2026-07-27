import { useState, type ReactNode } from 'react';
import type { TieredMetricFormula } from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiLanguage } from '../../i18n/uiText';
import { metricEntry } from '../../i18n/metricLabels';
import { cn } from '../../utils/cn';
import { formatValue, jumpToMetric } from '../tiered/termHelpers';
import { ALT_LINK, FORMULA_LINE, FORMULA_RESULT } from './altStyles';
import { AltModal, FVar, MODAL_STRONG } from './AltUi';

// A technicals metric value with its computation receipt: clicking the
// value (a number OR a rule-derived label like "bullish") opens the
// three-part receipt the trade-plan levels use — the formula/rule in
// words, this run's ingredients, and the result. Multi-outcome rules
// (branches) render one line per outcome, in both the words and the
// plugged section (owner format 2026-07-28):
//   bullish: index_close > index_sma_200 && …
//   bearish: index_close < index_sma_200 && …
//   mixed:   else
// The plugged-line style is picked by inspecting the words (see
// TieredMetricFormula in api/tiered): substitution (numbers replace
// their tokens in place) or an "ingredient = value" list (rules whose
// ingredients are words).

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

// Split a formula/condition on its input tokens (longest first, so
// `close` never eats into `close_5d_ago`) — the AltLevels splitter,
// minus its prose expansion, which technicals receipts don't need.
const splitOnInputs = (text: string, inputs: TieredMetricFormula['inputs']): string[] => {
  const keys = Object.keys(inputs).sort((a, b) => b.length - a.length);
  if (keys.length === 0) {
    return [text];
  }
  return text.split(new RegExp(`(${keys.join('|')})`, 'g'));
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

// A formula/condition string with its input tokens rendered as italic
// labels ('words') or this run's values ('plugged').
const TokenText = ({
  text,
  inputs,
  mode,
  onNavigate,
}: {
  text: string;
  inputs: TieredMetricFormula['inputs'];
  mode: 'words' | 'plugged';
  onNavigate: () => void;
}) => {
  const { language } = useUiLanguage();
  return (
    <>
      {splitOnInputs(text, inputs).map((part, index) => {
        const input = inputs[part];
        if (input === undefined) {
          return <span key={index}>{part}</span>;
        }
        return mode === 'words' ? (
          <FVar key={index}>{varLabel(part, language)}</FVar>
        ) : (
          <PluggedValue key={index} inputKey={part} value={input} onNavigate={onNavigate} />
        );
      })}
    </>
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
  const branches = formula.branches ?? null;
  const entries = Object.entries(formula.inputs);
  // Substitution style: every ingredient token appears in the words, so
  // the plugged line(s) can replace them in place. Otherwise the
  // ingredients are listed as "name = value" pairs (rule receipts whose
  // ingredients are words).
  const wordsText = branches
    ? branches.map((branch) => branch.condition ?? '').join(' ')
    : formula.formula ?? '';
  const isSubstituted =
    entries.length > 0 && entries.every(([key]) => wordsText.includes(key));
  const label = metricEntry(term, language)?.short ?? term;

  // One branch line: "label: condition" (or "label: else"); the plugged
  // variant leads with "=" on the first line, indents the rest.
  const branchLine = (
    branch: { label: string; condition: string | null },
    index: number,
    mode: 'words' | 'plugged',
  ): ReactNode => (
    <p key={`${mode}-${index}`} className={FORMULA_LINE}>
      {mode === 'plugged' ? (
        <span className="inline-block w-4">{index === 0 ? '=' : ''}</span>
      ) : null}
      <span className={MODAL_STRONG}>{branch.label}</span>
      {': '}
      {branch.condition === null ? (
        'else'
      ) : (
        <TokenText text={branch.condition} inputs={formula.inputs} mode={mode} onNavigate={close} />
      )}
    </p>
  );

  let plugged: ReactNode = null;
  if (isSubstituted && branches) {
    plugged = branches.map((branch, index) => branchLine(branch, index, 'plugged'));
  } else if (isSubstituted && formula.formula) {
    plugged = (
      <p className={FORMULA_LINE}>
        {'= '}
        <TokenText text={formula.formula} inputs={formula.inputs} mode="plugged" onNavigate={close} />
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
          <div className="flex flex-col gap-0.5">
            {branches ? (
              branches.map((branch, index) => branchLine(branch, index, 'words'))
            ) : (
              <p className={FORMULA_LINE}>
                <TokenText
                  text={formula.formula ?? ''}
                  inputs={formula.inputs}
                  mode="words"
                  onNavigate={close}
                />
              </p>
            )}
          </div>
          {plugged ? <div className="flex flex-col gap-0.5">{plugged}</div> : null}
          <p className={FORMULA_RESULT}>= {formatValue(value)}</p>
        </div>
      </AltModal>
    </>
  );
};
