import { useMemo, useState } from 'react';
import type {
  TieredCitation,
  TieredLevelDetail,
  TieredLevels,
  TieredLevelsDetail,
} from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { cn } from '../../utils/cn';
import { formatPrice, jumpToMetric } from '../tiered/termHelpers';
import { HelpTerm as BaseHelpTerm, MetricTerm } from '../tiered/terms';
import { ALT_LINK } from './altStyles';
import { AltEvidenceRefs, AltModal } from './AltUi';

// Alt skin rule: help popups everywhere, dotted underlines nowhere.
const HelpTerm = (props: Parameters<typeof BaseHelpTerm>[0]) => (
  <BaseHelpTerm underline={false} {...props} />
);

const LEVEL_ORDER = ['entry', 'secondary_entry', 'stop_loss', 'take_profit'] as const;
type LevelKey = (typeof LEVEL_ORDER)[number];

const LEVEL_LABEL_KEYS: Record<LevelKey, UiTextKey> = {
  entry: 'tiered.levels.entry',
  secondary_entry: 'tiered.levels.secondaryEntry',
  stop_loss: 'tiered.levels.stopLoss',
  take_profit: 'tiered.levels.takeProfit',
};

const LEVEL_HELP_KEYS: Record<LevelKey, UiTextKey> = {
  entry: 'tiered.help.entry',
  secondary_entry: 'tiered.help.secondaryEntry',
  stop_loss: 'tiered.help.stopLoss',
  take_profit: 'tiered.help.takeProfit',
};

// Formula inputs with a source row on the technicals card (see LevelTiles).
const TECHNICALS_INPUT_KEYS = new Set(['close', 'sma_20', 'sma_60', 'swing_low_20', 'atr_14']);

interface AltFormulaProps {
  formula: string;
  inputs: Record<string, number>;
  onNavigate: () => void;
}

// The formula with each input replaced by this run's number; numbers whose
// input lives on the technicals card link to that row.
const AltFormula = ({ formula, inputs, onNavigate }: AltFormulaProps) => {
  const parts = useMemo(() => {
    const keys = Object.keys(inputs).sort((a, b) => b.length - a.length);
    if (keys.length === 0) {
      return [formula];
    }
    return formula.split(new RegExp(`(${keys.join('|')})`, 'g'));
  }, [formula, inputs]);

  return (
    <code className="block whitespace-pre-wrap text-sm text-gray-300">
      {parts.map((part, index) => {
        const value = inputs[part];
        if (value === undefined) {
          return <span key={index}>{part}</span>;
        }
        if (TECHNICALS_INPUT_KEYS.has(part)) {
          return (
            <button
              key={index}
              type="button"
              aria-label={part}
              className={cn('cursor-pointer', ALT_LINK)}
              onClick={() => {
                onNavigate();
                window.setTimeout(() => jumpToMetric(`technicals.${part}`), 50);
              }}
            >
              {formatPrice(value)}
            </button>
          );
        }
        return <span key={index}>{formatPrice(value)}</span>;
      })}
    </code>
  );
};

interface AltLevelProps {
  levelKey: LevelKey;
  finalValue: number | null;
  detail: TieredLevelDetail | null;
  citations: TieredCitation[];
}

const AltLevel = ({ levelKey, finalValue, detail, citations }: AltLevelProps) => {
  const { t } = useUiLanguage();
  const [isOpen, setIsOpen] = useState(false);
  const close = () => setIsOpen(false);

  const label = t(LEVEL_LABEL_KEYS[levelKey]);

  // One subdued line tells the whole base→adjusted story; the modal has
  // the receipts (formula, plugged-in numbers, AI reasoning, evidence).
  let story: string | null = null;
  if (detail && detail.base !== null) {
    if (detail.adjusted !== null) {
      story = t('tiered.alt.levelStory', {
        base: formatPrice(detail.base),
        adjusted: formatPrice(detail.adjusted),
      });
    } else if (detail.rejection) {
      story = t('tiered.alt.levelStoryRejected', { base: formatPrice(detail.base) });
    } else {
      story = t('tiered.alt.levelStoryNoChange', { base: formatPrice(detail.base) });
    }
  }

  return (
    <div data-testid={`alt-level-${levelKey}`}>
      <div className="text-xs font-semibold text-gray-500">
        <HelpTerm label={label} helpKey={LEVEL_HELP_KEYS[levelKey]} />
      </div>
      <div className="mt-1 text-xl font-bold tabular-nums text-gray-300">
        {formatPrice(finalValue)}
      </div>
      {story ? (
        <button
          type="button"
          data-testid={`alt-level-story-${levelKey}`}
          onClick={() => setIsOpen(true)}
          className={cn('mt-0.5 cursor-pointer text-xs', ALT_LINK)}
        >
          {story}
        </button>
      ) : null}

      {detail ? (
        <AltModal isOpen={isOpen} title={label} onClose={close}>
          <div className="flex flex-col gap-4">
            {detail.formula ? (
              <div>
                <div className="mb-1 text-xs font-semibold text-gray-500">
                  {t('tiered.levelModal.formula')}
                </div>
                <code className="block whitespace-pre-wrap text-sm text-gray-300">
                  {detail.formula}
                </code>
              </div>
            ) : (
              <p>{t('tiered.levelModal.noBase')}</p>
            )}

            {detail.formula ? (
              <div>
                <div className="mb-1 text-xs font-semibold text-gray-500">
                  {t('tiered.levelModal.withNumbers')}
                </div>
                <AltFormula formula={detail.formula} inputs={detail.inputs ?? {}} onNavigate={close} />
                <div className="mt-1 text-sm text-gray-300">= {formatPrice(detail.base)}</div>
                <p className="mt-1 text-xs text-gray-500">{t('tiered.levelModal.inputsHint')}</p>
              </div>
            ) : null}

            {detail.rejection ? (
              <div>
                <p className="text-amber-300">{t('tiered.levelModal.rejectedNote')}</p>
                <p className="mt-1 text-xs">{detail.rejection}</p>
              </div>
            ) : null}

            {detail.adjusted !== null ? (
              <div className="text-sm text-gray-300">
                {formatPrice(detail.base)} → {formatPrice(detail.adjusted)}
              </div>
            ) : null}

            {detail.reason ? (
              <div>
                <div className="mb-1 text-xs font-semibold text-gray-500">
                  {t('tiered.levelModal.reason')}
                </div>
                <p className="leading-relaxed">{detail.reason}</p>
              </div>
            ) : null}

            {detail.evidence.length > 0 ? (
              <div>
                <div className="mb-1 text-xs font-semibold text-gray-500">
                  {t('tiered.levelModal.references')}
                </div>
                <ul className="flex flex-col gap-1">
                  {detail.evidence.map((refPath, index) => (
                    <li key={index} className="flex gap-2 text-xs">
                      <span className="shrink-0 text-gray-500">[{index + 1}]</span>
                      <AltEvidenceRefs refs={[refPath]} citations={citations} onNavigate={close} />
                    </li>
                  ))}
                </ul>
                <p className="mt-1 text-xs text-gray-500">{t('tiered.levelModal.referencesHint')}</p>
              </div>
            ) : null}

            {detail.inputs && Object.keys(detail.inputs).length > 0 ? (
              <div>
                <div className="mb-1 text-xs font-semibold text-gray-500">
                  {t('tiered.levelModal.inputs')}
                </div>
                <ul className="flex flex-col gap-0.5">
                  {Object.entries(detail.inputs).map(([key, value]) => (
                    <li key={key} className="flex items-baseline justify-between gap-3 text-xs">
                      <span>
                        <MetricTerm term={key} />
                      </span>
                      <span className="tabular-nums text-gray-300">{formatPrice(value)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        </AltModal>
      ) : null}
    </div>
  );
};

interface AltLevelsProps {
  levels: TieredLevels;
  levelsDetail: TieredLevelsDetail | null | undefined;
  citations: TieredCitation[];
}

export const AltLevels = ({ levels, levelsDetail, citations }: AltLevelsProps) => (
  <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
    {LEVEL_ORDER.map((key) => (
      <AltLevel
        key={key}
        levelKey={key}
        finalValue={levels[key]}
        detail={levelsDetail?.levels?.[key] ?? null}
        citations={citations}
      />
    ))}
  </div>
);
