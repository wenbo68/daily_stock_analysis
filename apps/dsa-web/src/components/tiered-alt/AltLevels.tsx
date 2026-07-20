import { useMemo, useState, type ReactNode } from 'react';
import type {
  TieredCitation,
  TieredLevelDetail,
  TieredLevels,
  TieredLevelsDetail,
} from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { cn } from '../../utils/cn';
import { flashElement, formatPrice, jumpToMetric } from '../tiered/termHelpers';
import { HelpTerm as BaseHelpTerm } from '../tiered/terms';
import { adjustedCellId, computedCellId } from './altFormat';
import { ALT_LINK, FORMULA_LINE, FORMULA_RESULT } from './altStyles';
import {
  AltEvidenceRefs,
  AltModal,
  AltSectionLabel,
  FVar,
  MODAL_BODY,
} from './AltUi';

// Alt skin rule: help popups everywhere, dotted underlines nowhere.
const HelpTerm = (props: Parameters<typeof BaseHelpTerm>[0]) => (
  <BaseHelpTerm underline={false} {...props} />
);

// Backup entry retired (owner decision, 2026-07-21): the plan is one
// order at the ideal entry, so the table shows three levels — old stored
// runs simply no longer render their backup column.
const LEVEL_ORDER = ['entry', 'stop_loss', 'take_profit'] as const;
type LevelKey = (typeof LEVEL_ORDER)[number];

const LEVEL_LABEL_KEYS: Record<LevelKey, UiTextKey> = {
  entry: 'tiered.levels.entry',
  stop_loss: 'tiered.levels.stopLoss',
  take_profit: 'tiered.levels.takeProfit',
};

const LEVEL_HELP_KEYS: Record<LevelKey, UiTextKey> = {
  entry: 'tiered.help.entry',
  stop_loss: 'tiered.help.stopLoss',
  take_profit: 'tiered.help.takeProfit',
};

// Formula inputs with a source row on the technicals card.
const TECHNICALS_INPUT_KEYS = new Set([
  'close', 'sma_20', 'sma_60', 'swing_low_20', 'swing_low_60',
  'swing_high_20', 'swing_high_60', 'high_52w', 'atr_14',
]);

// Formula inputs that ARE another computed level of this same table (the
// stop uses the computed entry, the target uses the computed stop) — their
// numbers link to that computed cell, so every number in a formula points
// at a place it already appeared.
const COMPUTED_CELL_INPUTS: Record<string, LevelKey> = {
  ideal_entry: 'entry',
  stop_loss: 'stop_loss',
};

// On-screen names for formula variables — never raw underscore tokens.
const VAR_LABEL: Record<string, string> = {
  close: 'close',
  sma_20: 'sma 20',
  sma_60: 'sma 60',
  swing_low_20: 'swing low 20',
  swing_low_60: 'swing low 60',
  swing_high_20: 'swing high 20',
  swing_high_60: 'swing high 60',
  high_52w: '52w high',
  round_level: 'round level',
  atr_14: 'atr 14',
  ideal_entry: 'ideal entry',
  stop_loss: 'stop loss',
};

// The stored formulas name two input GROUPS in prose. Expanding the
// phrases into the run's actual input keys lets the split-and-link
// machinery below turn every one of them into a real, clickable number.
const SUPPORT_KEYS = ['sma_20', 'sma_60', 'swing_low_20', 'swing_low_60', 'round_level'];
const RESISTANCE_KEYS = ['swing_high_20', 'swing_high_60', 'high_52w'];

const expandProse = (formula: string, inputs: Record<string, number>): string => {
  let expanded = formula;
  const supports = SUPPORT_KEYS.filter((key) => inputs[key] !== undefined);
  if (supports.length > 0) {
    expanded = expanded.replace('support candidates', supports.join(', '));
  }
  const resistances = RESISTANCE_KEYS.filter((key) => inputs[key] !== undefined);
  if (resistances.length > 0) {
    expanded = expanded.replace(
      'nearest overhead resistance',
      `nearest of (${resistances.join(', ')})`,
    );
  }
  return expanded;
};

const splitOnInputs = (formula: string, inputs: Record<string, number>): string[] => {
  const keys = Object.keys(inputs).sort((a, b) => b.length - a.length);
  if (keys.length === 0) {
    return [formula];
  }
  return expandProse(formula, inputs).split(new RegExp(`(${keys.join('|')})`, 'g'));
};

// The round level is computed on the spot (the largest round price below
// the close), so it has no source row to link to — clicking it opens a
// small how-computed note instead.
const RoundLevelNumber = ({ value }: { value: number }) => {
  const { t } = useUiLanguage();
  const [isOpen, setIsOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        aria-label={VAR_LABEL.round_level}
        data-testid="alt-round-level"
        className={cn('cursor-pointer tabular-nums', ALT_LINK)}
        onClick={() => setIsOpen(true)}
      >
        {formatPrice(value)}
      </button>
      <AltModal
        isOpen={isOpen}
        title={t('tiered.alt.roundLevelTitle')}
        onClose={() => setIsOpen(false)}
      >
        <p className={MODAL_BODY}>
          {t('tiered.alt.roundLevelBody', { value: formatPrice(value) })}
        </p>
      </AltModal>
    </>
  );
};

// One plugged-in number, linking to where it already appears — a
// technicals metric row, or another computed cell of the levels table.
const InputNumberLink = ({
  inputKey,
  value,
  onNavigate,
}: {
  inputKey: string;
  value: number;
  onNavigate: () => void;
}) => {
  if (inputKey === 'round_level') {
    return <RoundLevelNumber value={value} />;
  }
  const computedTarget = COMPUTED_CELL_INPUTS[inputKey];
  const jump = TECHNICALS_INPUT_KEYS.has(inputKey)
    ? () => jumpToMetric(`technicals.${inputKey}`)
    : computedTarget
      ? () => flashElement(computedCellId(computedTarget))
      : null;
  if (!jump) {
    return <span className="tabular-nums">{formatPrice(value)}</span>;
  }
  return (
    <button
      type="button"
      aria-label={VAR_LABEL[inputKey] ?? inputKey}
      className={cn('cursor-pointer tabular-nums', ALT_LINK)}
      onClick={() => {
        onNavigate();
        // Let the modal unmount before scrolling to the row behind it.
        window.setTimeout(jump, 50);
      }}
    >
      {formatPrice(value)}
    </button>
  );
};

interface AltFormulaProps {
  formula: string;
  inputs: Record<string, number>;
  onNavigate: () => void;
}

// The formula in words: variables italic, everything else as written.
const AltFormulaWords = ({ formula, inputs }: Omit<AltFormulaProps, 'onNavigate'>) => (
  <>
    {splitOnInputs(formula, inputs).map((part, index) =>
      inputs[part] === undefined ? (
        <span key={index}>{part}</span>
      ) : (
        <FVar key={index}>{VAR_LABEL[part] ?? part}</FVar>
      ),
    )}
  </>
);

// The formula with each input replaced by this run's number.
const AltFormula = ({ formula, inputs, onNavigate }: AltFormulaProps) => {
  const parts = useMemo(() => splitOnInputs(formula, inputs), [formula, inputs]);

  return (
    <>
      {parts.map((part, index) =>
        inputs[part] === undefined ? (
          <span key={index}>{part}</span>
        ) : (
          <InputNumberLink key={index} inputKey={part} value={inputs[part]} onNavigate={onNavigate} />
        ),
      )}
    </>
  );
};

interface AltLevelCellProps {
  levelKey: LevelKey;
  detail: TieredLevelDetail | null;
  label: string;
  citations: TieredCitation[];
}

// The computed (formula-base) number. Clicking it opens the receipts, in
// the shares-computation shape: the formula, the formula with this run's
// numbers plugged in (each number a link to its source), and the result.
const AltComputedCell = ({ levelKey, detail, label }: Omit<AltLevelCellProps, 'citations'>) => {
  const { t } = useUiLanguage();
  const [isOpen, setIsOpen] = useState(false);
  const close = () => setIsOpen(false);

  if (!detail || detail.base === null) {
    return <span className="text-gray-600">—</span>;
  }

  return (
    <>
      <button
        type="button"
        id={computedCellId(levelKey)}
        data-testid={`alt-level-computed-${levelKey}`}
        onClick={() => setIsOpen(true)}
        className={cn('cursor-pointer tabular-nums', ALT_LINK)}
      >
        {formatPrice(detail.base)}
      </button>
      <AltModal
        isOpen={isOpen}
        title={t('tiered.levelModal.formulaTitle', { level: label })}
        onClose={close}
        // Fit the widest formula line; each line stays a single line.
        panelClassName="w-fit min-w-72 max-w-[95vw]"
      >
        {!detail.formula ? (
          <p>{t('tiered.levelModal.noBase')}</p>
        ) : (
          <div className="flex flex-col gap-2 overflow-x-auto text-sm" data-testid="alt-formula-modal">
            <p className={FORMULA_LINE} data-testid="alt-formula-words">
              <AltFormulaWords formula={detail.formula} inputs={detail.inputs ?? {}} />
            </p>
            <p className={FORMULA_LINE} data-testid="alt-formula-plugged">
              {'= '}
              <AltFormula formula={detail.formula} inputs={detail.inputs ?? {}} onNavigate={close} />
            </p>
            <p className={FORMULA_RESULT}>= {formatPrice(detail.base)}</p>
          </div>
        )}
      </AltModal>
    </>
  );
};

// The AI's adjusted number — or "keep" when the computed value stands.
// Clicking the number opens why the AI moved it, with its references.
const AltAdjustedCell = ({ levelKey, detail, label, citations }: AltLevelCellProps) => {
  const { t } = useUiLanguage();
  const [isOpen, setIsOpen] = useState(false);
  const close = () => setIsOpen(false);

  if (!detail || detail.base === null) {
    return <span className="text-gray-600">—</span>;
  }
  if (detail.adjusted === null) {
    return (
      <span data-testid={`alt-level-keep-${levelKey}`} className="text-gray-500">
        {t('tiered.alt.levels.keep')}
      </span>
    );
  }

  return (
    <>
      <button
        type="button"
        id={adjustedCellId(levelKey)}
        data-testid={`alt-level-adjusted-${levelKey}`}
        onClick={() => setIsOpen(true)}
        className={cn('cursor-pointer tabular-nums', ALT_LINK)}
      >
        {formatPrice(detail.adjusted)}
      </button>
      <AltModal
        isOpen={isOpen}
        title={t('tiered.levelModal.adjustTitle', { level: label })}
        onClose={close}
      >
        <div className={MODAL_BODY}>
          <div className="tabular-nums">
            {formatPrice(detail.base)} → {formatPrice(detail.adjusted)}
          </div>
          {detail.reason ? (
            <div>
              <AltSectionLabel>{t('tiered.levelModal.reason')}</AltSectionLabel>
              <p>{detail.reason}</p>
            </div>
          ) : null}
          {detail.evidence.length > 0 ? (
            <div>
              <AltSectionLabel>{t('tiered.levelModal.references')}</AltSectionLabel>
              <ul className="flex flex-col gap-1">
                {detail.evidence.map((refPath, index) => (
                  <li key={index} className="flex gap-2 text-xs">
                    <span className="shrink-0 text-gray-500">[{index + 1}]</span>
                    <AltEvidenceRefs refs={[refPath]} citations={citations} onNavigate={close} />
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      </AltModal>
    </>
  );
};

interface AltLevelsProps {
  levels: TieredLevels;
  levelsDetail: TieredLevelsDetail | null | undefined;
  citations: TieredCitation[];
}

const CELL = 'py-1.5 pr-4 text-sm';
const ROW_LABEL = 'py-1.5 pr-4 text-xs text-gray-500';

// The tier-1 price levels as a computed/adjusted table: the formula bases
// on top, the AI's validated adjustments beneath them (chronological —
// what was computed first, then what the AI did to it). Old runs without
// the audit trail fall back to a single row of the stored values.
export const AltLevels = ({ levels, levelsDetail, citations }: AltLevelsProps) => {
  const { t } = useUiLanguage();
  const details = levelsDetail?.levels ?? null;

  const headerCells: ReactNode = (
    <tr>
      <th className="pb-1.5 pr-4" />
      {LEVEL_ORDER.map((key) => (
        <th key={key} className="pb-1.5 pr-4 text-left text-xs font-semibold text-gray-500">
          <HelpTerm label={t(LEVEL_LABEL_KEYS[key])} helpKey={LEVEL_HELP_KEYS[key]} />
        </th>
      ))}
    </tr>
  );

  return (
    <div className="overflow-x-auto" data-testid="alt-levels-table">
      <table className="w-full">
        <thead>{headerCells}</thead>
        <tbody>
          {details ? (
            <>
              <tr>
                <td className={ROW_LABEL}>{t('tiered.alt.levels.computed')}</td>
                {LEVEL_ORDER.map((key) => (
                  <td key={key} className={CELL}>
                    <AltComputedCell
                      levelKey={key}
                      detail={details[key] ?? null}
                      label={t(LEVEL_LABEL_KEYS[key])}
                    />
                  </td>
                ))}
              </tr>
              <tr>
                <td className={ROW_LABEL}>{t('tiered.alt.levels.adjusted')}</td>
                {LEVEL_ORDER.map((key) => (
                  <td key={key} className={CELL}>
                    <AltAdjustedCell
                      levelKey={key}
                      detail={details[key] ?? null}
                      label={t(LEVEL_LABEL_KEYS[key])}
                      citations={citations}
                    />
                  </td>
                ))}
              </tr>
            </>
          ) : (
            <tr>
              <td className={ROW_LABEL} />
              {LEVEL_ORDER.map((key) => (
                <td key={key} className={cn(CELL, 'tabular-nums text-gray-300')}>
                  {formatPrice(levels[key])}
                </td>
              ))}
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
};
