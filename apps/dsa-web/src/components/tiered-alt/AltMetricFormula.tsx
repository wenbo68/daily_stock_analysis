import { useState, type ReactNode } from 'react';
import type { TieredMetricFormula } from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiLanguage } from '../../i18n/uiText';
import { metricEntry } from '../../i18n/metricLabels';
import { cn } from '../../utils/cn';
import { formatValue, jumpToMetric } from '../tiered/termHelpers';
import { formatMetricValue } from './altFormat';
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
// Rules with all-numeric ingredients substitute the numbers into each
// branch line; rules with word ingredients ("rising") instead fold the
// ingredients into the result line (owner format 2026-07-28):
//   = neutral: 14d RSI = 49.31 && MACD histogram = falling && …

// Inputs that ARE payload rows on the same card — their plugged numbers
// jump to that row, so every number in a receipt points at a place it
// already appears (the levels-table rule).
const INPUT_ROW_PATH: Record<string, string> = {
  close: 'technicals.price.close',
  high_1y: 'technicals.price.high_1y',
  low_1y: 'technicals.price.low_1y',
  sma_50: 'technicals.daily.sma_50',
  sma_10w: 'technicals.weekly.sma_10w',
  atr_14: 'technicals.volatility.atr_14',
  avg_vol_60d: 'technicals.volume.avg_vol_60d',
  avg_vol_5d: 'technicals.volume.avg_vol_5d',
  rsi_14: 'technicals.daily.rsi_14',
  rs_1m: 'technicals.market.rs_1m',
  rs_3m: 'technicals.market.rs_3m',
  // Fundamentals receipts. next_earnings_date appears only in OLD stored
  // runs' receipts (the earnings group); new runs publish it under
  // quarterly_report with no receipt referencing it.
  next_earnings_date: 'fundamentals.earnings.next_earnings_date',
  fcf: 'fundamentals.profitability.fcf',
  // The growth-trend receipts cite the published YoY rows by key.
  revenue_yoy_q: 'fundamentals.growth.revenue_yoy_q',
  eps_yoy_q: 'fundamentals.growth.eps_yoy_q',
  // Positioning receipts: the float is the one ingredient that is
  // also a published row.
  float_shares: 'positioning.ownership.float_shares',
};

// On-screen names for receipt-only ingredients (values the formula needs
// that are not published as rows) — never raw underscore tokens. Keys
// that ARE rows take their name from metricLabels; entries here also
// cover receipts stored before a key was promoted to a row (avg_vol_5).
const HELPER_VAR_LABEL: Record<string, string> = {
  close_5d_ago: 'close 5 days ago',
  avg_gain_14: 'avg gain (14d)',
  avg_loss_14: 'avg loss (14d)',
  avg_vol_5: 'avg volume (5d)',
  stock_return_1m: 'stock return (1m)',
  index_return_1m: 'index return (1m)',
  stock_return_3m: 'stock return (3m)',
  index_return_3m: 'index return (3m)',
  worst_close: 'worst-day close',
  prev_close: 'previous close',
  index_close: 'index close',
  index_sma_200: 'index 200-day average',
  index_range_pct: 'index position in 1y range (%)',
  ma_stack: 'moving-average check',
  pivot_structure: 'pivot structure',
  macd_hist: 'MACD histogram',
  macd_line: 'MACD line',
  atr_20_bars_ago: 'atr 14 (20 days ago)',
  // Fundamentals receipt ingredients (raw statement values and
  // consensus estimates — none are published rows). Variable names
  // follow the user-facing word canon: "sales" and "earnings".
  sales_q: 'quarterly sales',
  sales_q_year_ago: 'sales same quarter last year',
  eps_q: 'quarterly EPS',
  eps_q_year_ago: 'EPS same quarter last year',
  prior_quarter_yoy: "prior quarter's yoy growth",
  gross_earnings: 'gross earnings',
  operating_earnings: 'operating earnings',
  earnings: 'earnings',
  sales: 'sales (fiscal year)',
  equity: "shareholders' equity",
  total_liabilities: 'total liabilities',
  current_assets: 'short-term assets',
  current_liabilities: 'short-term liabilities',
  operating_cash_flow: 'operating cash flow',
  capital_spending: 'capital spending',
  estimate_now: 'consensus EPS estimate now',
  estimate_90d_ago: 'consensus EPS estimate 90 days ago',
  next_dividend_payment_date: 'next dividend payment date',
  today: 'today',
  // Positioning receipt ingredients (2026-08-01) — raw disclosure and
  // options-board values that are not published rows.
  shorted_shares: 'shorted shares',
  prior_report_shares: 'shorted shares (prior report)',
  insider_buy_money: 'insider buying ($)',
  insider_sell_money: 'insider selling ($)',
  held_puts: 'held put contracts',
  held_calls: 'held call contracts',
  puts_traded_today: 'puts traded today',
  calls_traded_today: 'calls traded today',
  atm_call_price: 'at-the-money call price',
  atm_put_price: 'at-the-money put price',
  stock_price: 'stock price',
  // Old stored runs' receipts used the pre-canon variable names.
  revenue_q: 'quarterly sales',
  revenue_q_year_ago: 'sales same quarter last year',
  gross_profit: 'gross earnings',
  operating_income: 'operating earnings',
  net_income: 'earnings',
  revenue: 'sales (fiscal year)',
  yoy_now: "this quarter's yoy growth",
  yoy_prior: "prior quarter's yoy growth",
};

// Helper names win over metricLabels here: a receipt ingredient like
// "earnings" collides with a payload group key of the same name, and
// the receipt must speak the ingredient's name, not the group's.
const varLabel = (key: string, language: UiLanguage): string =>
  HELPER_VAR_LABEL[key] ?? metricEntry(key, language)?.short ?? key.replace(/_/g, ' ');

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

interface AltBlankValueProps {
  /** The payload key of the blank metric — names the modal and selects
      its per-field blank reason from metricLabels. */
  term: string;
}

// A blank metric value: renders as a clickable "n/a" that opens a modal
// explaining why this field can be empty (owner request 2026-07-31).
// The reason is the field's static `blank` text from metricLabels; a
// field without one gets the generic fallback.
export const AltBlankValue = ({ term }: AltBlankValueProps) => {
  const { t, language } = useUiLanguage();
  const [isOpen, setIsOpen] = useState(false);
  const entry = metricEntry(term, language);
  const label = entry?.short ?? term;
  return (
    <>
      <button
        type="button"
        data-testid={`alt-metric-blank-${term}`}
        onClick={() => setIsOpen(true)}
        className={cn('cursor-pointer', ALT_LINK)}
      >
        n/a
      </button>
      <AltModal
        isOpen={isOpen}
        title={t('tiered.alt.blankTitle', { label })}
        onClose={() => setIsOpen(false)}
        panelClassName="w-fit min-w-72 max-w-md"
      >
        <p className="whitespace-pre-line text-sm" data-testid="alt-metric-blank-modal">
          {entry?.blank ?? t('tiered.alt.blankFallback')}
        </p>
      </AltModal>
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
  // Substitution style: every ingredient is a number AND its token
  // appears in the words, so the plugged line(s) can replace them in
  // place. Rules with word ingredients ("rising") instead fold the
  // "name = value" pairs into the result line.
  const wordsText = branches
    ? branches.map((branch) => branch.condition ?? '').join(' ')
    : formula.formula ?? '';
  const hasWordInput = entries.some(([, input]) => typeof input === 'string');
  const isSubstituted =
    entries.length > 0 && !hasWordInput && entries.every(([key]) => wordsText.includes(key));
  const label = metricEntry(term, language)?.short ?? term;

  // One branch line: "label: condition" (or "label: else"); the plugged
  // variant leads with "= " on the first line and indents the rest by
  // the same "= " (kept invisible so every line's spacing is identical
  // to the result line's own "= ").
  const branchLine = (
    branch: { label: string; condition: string | null },
    index: number,
    mode: 'words' | 'plugged',
  ): ReactNode => (
    <p key={`${mode}-${index}`} className={FORMULA_LINE}>
      {mode === 'plugged' ? (
        <span className={index === 0 ? undefined : 'invisible'}>{'= '}</span>
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
  }

  // Word-ingredient rules skip the plugged section: the ingredients ride
  // on the result line as "= label: name = value && name = value".
  const mergedIngredients = !isSubstituted && entries.length > 0;
  const resultLine = mergedIngredients ? (
    <p className={FORMULA_LINE}>
      <span className={MODAL_STRONG}>= {formatMetricValue(term, value)}</span>
      {': '}
      {entries.map(([key, input], index) => (
        <span key={key}>
          {index > 0 ? ' && ' : ''}
          <FVar>{varLabel(key, language)}</FVar>
          {' = '}
          <PluggedValue inputKey={key} value={input} onNavigate={close} />
        </span>
      ))}
    </p>
  ) : (
    <p className={FORMULA_RESULT}>= {formatMetricValue(term, value)}</p>
  );

  return (
    <>
      <button
        type="button"
        data-testid={`alt-metric-formula-${term}`}
        onClick={() => setIsOpen(true)}
        className={cn('cursor-pointer tabular-nums', ALT_LINK)}
      >
        {formatMetricValue(term, value)}
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
          {resultLine}
        </div>
      </AltModal>
    </>
  );
};
