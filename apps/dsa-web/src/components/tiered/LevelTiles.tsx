import { useMemo, useState, type ReactNode } from 'react';
import type {
  TieredCitation,
  TieredLevelDetail,
  TieredLevels,
  TieredLevelsDetail,
} from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { formatPrice, jumpToMetric } from './termHelpers';
import { EvidenceRefList, HelpTerm, MetricTerm } from './terms';
import { TieredModal } from './TieredModal';

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

// Formula inputs that exist as rows on the technicals dimension card;
// their plugged-in numbers become jump links. Derived values
// (ideal_entry, stop_loss) and constants have no source row.
const TECHNICALS_INPUT_KEYS = new Set([
  'close',
  'sma_20',
  'sma_60',
  'swing_low_20',
  'atr_14',
]);

interface FormulaWithNumbersProps {
  formula: string;
  inputs: Record<string, number>;
  onNavigate: () => void;
}

// The formula with each input name replaced by this run's number. Numbers
// whose input lives on the technicals card are links that scroll to that
// row (the user's "hyperlink to the source" spec).
const FormulaWithNumbers = ({ formula, inputs, onNavigate }: FormulaWithNumbersProps) => {
  const parts = useMemo(() => {
    const keys = Object.keys(inputs).sort((a, b) => b.length - a.length);
    if (keys.length === 0) {
      return [formula];
    }
    const splitter = new RegExp(`(${keys.join('|')})`, 'g');
    return formula.split(splitter);
  }, [formula, inputs]);

  return (
    <code className="block whitespace-pre-wrap font-mono text-sm text-foreground">
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
              className="text-cyan underline decoration-dotted hover:decoration-solid"
              onClick={() => {
                onNavigate();
                window.setTimeout(() => jumpToMetric(`technicals.${part}`), 50);
              }}
            >
              {formatPrice(value)}
            </button>
          );
        }
        return (
          <span key={index} className="border-b border-dotted border-secondary-text/60">
            {formatPrice(value)}
          </span>
        );
      })}
    </code>
  );
};

interface LevelTileProps {
  levelKey: LevelKey;
  finalValue: number | null;
  detail: TieredLevelDetail | null;
  citations: TieredCitation[];
}

const LevelTile = ({ levelKey, finalValue, detail, citations }: LevelTileProps) => {
  const { t } = useUiLanguage();
  const [openModal, setOpenModal] = useState<'formula' | 'adjustment' | null>(null);
  const close = () => setOpenModal(null);

  const label = t(LEVEL_LABEL_KEYS[levelKey]);
  const hasBase = detail?.base !== null && detail?.base !== undefined;
  // New runs carry a reasons list; old stored runs a single paragraph.
  const reasonText =
    detail?.reason ?? detail?.reasons?.map((reason) => reason.text).join(' ') ?? null;
  const hasAdjustmentStory = Boolean(detail && (reasonText || detail.rejection));

  // Old stored runs (no audit trail): the plain tile from v1.
  if (!detail) {
    return (
      <div className="rounded-xl border border-border/40 bg-elevated/60 px-3 py-2">
        <div className="text-xs text-secondary-text">
          <HelpTerm label={label} helpKey={LEVEL_HELP_KEYS[levelKey]} />
        </div>
        <div className="mt-1 font-mono text-base text-foreground">{formatPrice(finalValue)}</div>
      </div>
    );
  }

  let adjustmentRow: ReactNode;
  if (detail.adjusted !== null) {
    adjustmentRow = (
      <button
        type="button"
        data-testid={`level-adjusted-${levelKey}`}
        onClick={() => setOpenModal('adjustment')}
        className="font-mono text-sm text-cyan underline decoration-dotted hover:decoration-solid"
      >
        {formatPrice(detail.adjusted)}
      </button>
    );
  } else if (detail.rejection) {
    adjustmentRow = (
      <button
        type="button"
        data-testid={`level-adjusted-${levelKey}`}
        onClick={() => setOpenModal('adjustment')}
        className="text-xs text-warning underline decoration-dotted hover:decoration-solid"
      >
        {t('tiered.levels.adjustmentRejected')}
      </button>
    );
  } else {
    adjustmentRow = (
      <span className="text-xs text-secondary-text">{t('tiered.levels.noAdjustment')}</span>
    );
  }

  return (
    <div className="rounded-xl border border-border/40 bg-elevated/60 px-3 py-2">
      <div className="text-xs text-secondary-text">
        <HelpTerm label={label} helpKey={LEVEL_HELP_KEYS[levelKey]} />
      </div>

      <div className="mt-1 flex items-baseline gap-2">
        <span className="text-[10px] uppercase tracking-wide text-secondary-text">
          <HelpTerm label={t('tiered.levels.base')} helpKey="tiered.help.levelBase" />
        </span>
        {hasBase ? (
          <button
            type="button"
            data-testid={`level-base-${levelKey}`}
            onClick={() => setOpenModal('formula')}
            className="font-mono text-base text-foreground underline decoration-dotted hover:decoration-solid"
          >
            {formatPrice(detail.base)}
          </button>
        ) : (
          <span className="font-mono text-base text-foreground">—</span>
        )}
      </div>

      <div className="mt-0.5 flex items-baseline gap-2">
        <span className="text-[10px] uppercase tracking-wide text-secondary-text">
          <HelpTerm label={t('tiered.levels.adjusted')} helpKey="tiered.help.levelAdjusted" />
        </span>
        {adjustmentRow}
      </div>

      <TieredModal
        isOpen={openModal === 'formula'}
        title={t('tiered.levelModal.formulaTitle', { level: label })}
        onClose={close}
      >
        {detail.formula ? (
          <div className="space-y-3 text-sm">
            <div>
              <div className="label-uppercase mb-1">{t('tiered.levelModal.formula')}</div>
              <code className="block whitespace-pre-wrap font-mono text-sm text-foreground">
                {detail.formula}
              </code>
            </div>
            <div>
              <div className="label-uppercase mb-1">{t('tiered.levelModal.withNumbers')}</div>
              <FormulaWithNumbers
                formula={detail.formula}
                inputs={detail.inputs ?? {}}
                onNavigate={close}
              />
              <div className="mt-1 font-mono text-sm text-foreground">
                = {formatPrice(detail.base)}
              </div>
            </div>
            {detail.inputs && Object.keys(detail.inputs).length > 0 ? (
              <div>
                <div className="label-uppercase mb-1">{t('tiered.levelModal.inputs')}</div>
                <ul className="space-y-0.5">
                  {Object.entries(detail.inputs).map(([key, value]) => (
                    <li key={key} className="flex items-baseline justify-between gap-3 text-xs">
                      <span className="text-secondary-text">
                        <MetricTerm term={key} />
                      </span>
                      <span className="font-mono text-foreground">{formatPrice(value)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            <p className="text-xs text-secondary-text">{t('tiered.levelModal.inputsHint')}</p>
          </div>
        ) : (
          <p className="text-sm text-secondary-text">{t('tiered.levelModal.noBase')}</p>
        )}
      </TieredModal>

      <TieredModal
        isOpen={openModal === 'adjustment'}
        title={t('tiered.levelModal.adjustTitle', { level: label })}
        onClose={close}
      >
        <div className="space-y-3 text-sm">
          {detail.rejection ? (
            <p className="text-warning">
              {t('tiered.levelModal.rejectedNote')}
              <span className="mt-1 block text-xs">{detail.rejection}</span>
            </p>
          ) : null}
          {detail.adjusted !== null ? (
            <p className="font-mono text-foreground">
              {formatPrice(detail.base)} → {formatPrice(detail.adjusted)}
            </p>
          ) : null}
          {reasonText ? (
            <div>
              <div className="label-uppercase mb-1">{t('tiered.levelModal.reason')}</div>
              <p className="leading-relaxed text-secondary-text">{reasonText}</p>
            </div>
          ) : null}
          {detail.evidence.length > 0 ? (
            <div>
              <div className="label-uppercase mb-1">{t('tiered.levelModal.references')}</div>
              <ul className="space-y-1">
                {detail.evidence.map((refPath, index) => (
                  <li key={index} className="flex gap-2 text-xs">
                    <span className="shrink-0 font-mono text-secondary-text">[{index + 1}]</span>
                    <EvidenceRefList refs={[refPath]} citations={citations} onNavigate={close} />
                  </li>
                ))}
              </ul>
              <p className="mt-1 text-xs text-secondary-text">
                {t('tiered.levelModal.referencesHint')}
              </p>
            </div>
          ) : null}
          {!hasAdjustmentStory ? (
            <p className="text-secondary-text">{t('tiered.levels.noAdjustment')}</p>
          ) : null}
        </div>
      </TieredModal>
    </div>
  );
};

interface LevelTilesProps {
  levels: TieredLevels;
  levelsDetail: TieredLevelsDetail | null | undefined;
  citations: TieredCitation[];
}

// The four price levels. With an audit trail (v2 runs) each tile shows the
// formula base (click → formula modal) and the AI-adjusted number below it
// (click → reasoning modal); old stored runs fall back to plain numbers.
export const LevelTiles = ({ levels, levelsDetail, citations }: LevelTilesProps) => (
  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
    {LEVEL_ORDER.map((key) => (
      <LevelTile
        key={key}
        levelKey={key}
        finalValue={levels[key]}
        detail={levelsDetail?.levels?.[key] ?? null}
        citations={citations}
      />
    ))}
  </div>
);
