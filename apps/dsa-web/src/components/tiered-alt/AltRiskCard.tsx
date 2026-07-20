import { Fragment, useState, type ReactNode } from 'react';
import type { TieredRiskCardEntry } from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { cn } from '../../utils/cn';
import { flashElement, formatPrice, jumpToMetric } from '../tiered/termHelpers';
import { computedCellId } from './altFormat';
import { ALT_LINK, FORMULA_LINE, FORMULA_RESULT, TAG_BASE } from './altStyles';
import { AltCard, AltModal, AltModalDivider, AltSectionLabel, FVar, MODAL_BODY } from './AltUi';

// The display-only risk card: 6 deterministic pre-trade checks (owner
// decision 2026-07-21 trimmed the original 13 — concentration/ownership
// return with the portfolio feature, VaR folded into the gap check, the
// rest were redundant). Numbered, each as value → action → reason; every
// number in a current-shape entry is clickable and opens a receipt modal
// (formula → this run's numbers, linked to their sources → result). By
// explicit owner decision the card affects NOTHING — the run's outlook,
// action, levels and sizing never read it. The backend ships numbers only
// ({id, status, values}); all wording lives here. Old stored runs carry
// the retired 13-entry card and still render (text-only).

const STATUS_TAG: Record<TieredRiskCardEntry['status'], string> = {
  ok: 'bg-emerald-500/20 text-emerald-300 ring-emerald-500/30',
  flag: 'bg-amber-500/20 text-amber-300 ring-amber-500/30',
  na: 'bg-gray-500/20 text-gray-400 ring-gray-500/30',
};

const STATUS_KEYS: Record<TieredRiskCardEntry['status'], UiTextKey> = {
  ok: 'tiered.riskCard.ok',
  flag: 'tiered.riskCard.flag',
  na: 'tiered.riskCard.na',
};

// A number for the value sentences: at most 2 decimals, no float noise.
const num = (value: unknown): string =>
  typeof value === 'number' ? String(Number(value.toFixed(2))) : '—';

// A 0-1 fraction as a percentage with at most 1 decimal.
const pct = (value: unknown): string =>
  typeof value === 'number' ? String(Number((value * 100).toFixed(1))) : '—';

const asNum = (value: unknown): number | null =>
  typeof value === 'number' ? value : null;

// Split a raw i18n template on its {placeholders} and substitute nodes,
// so the numbers inside a sentence can be buttons, not just text.
const fillTemplate = (template: string, parts: Record<string, ReactNode>): ReactNode[] =>
  template.split(/(\{\w+\})/g).map((segment, index) => {
    const match = /^\{(\w+)\}$/.exec(segment);
    return match ? (
      <Fragment key={index}>{parts[match[1]] ?? ''}</Fragment>
    ) : (
      <Fragment key={index}>{segment}</Fragment>
    );
  });

// ---- receipt-modal building blocks (formula → plugged numbers → result) --

// A plugged-in number that links to the technicals row it came from.
const TechNum = ({
  metric,
  text,
  onNavigate,
}: {
  metric: string;
  text: string;
  onNavigate: () => void;
}) => (
  <button
    type="button"
    aria-label={metric.replace(/_/g, ' ')}
    className={cn('cursor-pointer tabular-nums', ALT_LINK)}
    onClick={() => {
      onNavigate();
      window.setTimeout(() => jumpToMetric(`technicals.${metric}`), 50);
    }}
  >
    {text}
  </button>
);

// A plugged-in number that flashes the plan level it came from.
const LevelNum = ({
  levelKey,
  text,
  onNavigate,
}: {
  levelKey: 'entry' | 'stop_loss' | 'take_profit';
  text: string;
  onNavigate: () => void;
}) => (
  <button
    type="button"
    aria-label={levelKey.replace(/_/g, ' ')}
    className={cn('cursor-pointer tabular-nums', ALT_LINK)}
    onClick={() => {
      onNavigate();
      window.setTimeout(() => flashElement(computedCellId(levelKey)), 50);
    }}
  >
    {text}
  </button>
);

interface ReceiptProps {
  values: Record<string, unknown>;
  onNavigate: () => void;
  t: (key: UiTextKey, params?: Record<string, string | number>) => string;
}

// One formula block: the words line, the plugged-in line, the result line —
// the same shape as the plan-level and shares receipts.
const Receipt = ({
  words,
  plugged,
  result,
}: {
  words: ReactNode;
  plugged: ReactNode;
  result: ReactNode;
}) => (
  <div className="flex flex-col gap-2 overflow-x-auto">
    <p className={FORMULA_LINE}>{words}</p>
    <p className={FORMULA_LINE}>{plugged}</p>
    <p className={FORMULA_RESULT}>{result}</p>
  </div>
);

const liquidityReceipt = ({ values, onNavigate }: ReceiptProps) => (
  <Receipt
    words={
      <>
        <FVar>shares</FVar> ÷ <FVar>avg volume 20</FVar>
      </>
    }
    plugged={
      <>
        = {num(values.shares)} ÷{' '}
        <TechNum metric="avg_volume_20" text={num(values.avg_volume_20)} onNavigate={onNavigate} />
      </>
    }
    result={`= ${pct(values.fraction_of_adv)}%`}
  />
);

const volatilityReceipt = ({ values, onNavigate }: ReceiptProps) => (
  <Receipt
    words={
      <>
        <FVar>atr 14</FVar> ÷ <FVar>close</FVar>
      </>
    }
    plugged={
      <>
        = <TechNum metric="atr_14" text={num(values.atr_14)} onNavigate={onNavigate} /> ÷{' '}
        <TechNum metric="close" text={num(values.close)} onNavigate={onNavigate} />
      </>
    }
    result={`= ${pct(values.atr_fraction)}%`}
  />
);

const rewardRiskReceipt = ({ values, onNavigate, t }: ReceiptProps) => (
  <div className={MODAL_BODY}>
    <Receipt
      words={
        <>
          (<FVar>target</FVar> − <FVar>entry</FVar>) ÷ (<FVar>entry</FVar> −{' '}
          <FVar>stop loss</FVar>)
        </>
      }
      plugged={
        <>
          = (
          <LevelNum levelKey="take_profit" text={num(values.take_profit)} onNavigate={onNavigate} />{' '}
          − <LevelNum levelKey="entry" text={num(values.entry)} onNavigate={onNavigate} />) ÷ (
          <LevelNum levelKey="entry" text={num(values.entry)} onNavigate={onNavigate} /> −{' '}
          <LevelNum levelKey="stop_loss" text={num(values.stop_loss)} onNavigate={onNavigate} />)
        </>
      }
      result={`= ${num(values.ratio)}`}
    />
    {values.goal != null ? (
      <p>{t('tiered.riskCard.goalLine', { goal: num(values.goal) })}</p>
    ) : null}
  </div>
);

const stopAtrReceipt = ({ values, onNavigate }: ReceiptProps) => (
  <Receipt
    words={
      <>
        (<FVar>entry</FVar> − <FVar>stop loss</FVar>) ÷ <FVar>atr 14</FVar>
      </>
    }
    plugged={
      <>
        = (<LevelNum levelKey="entry" text={num(values.entry)} onNavigate={onNavigate} /> −{' '}
        <LevelNum levelKey="stop_loss" text={num(values.stop_loss)} onNavigate={onNavigate} />) ÷{' '}
        <TechNum metric="atr_14" text={num(values.atr_14)} onNavigate={onNavigate} />
      </>
    }
    result={`= ${num(values.atr_multiple)}`}
  />
);

const stopVsSwingLowReceipt = ({ values, onNavigate, t }: ReceiptProps) => (
  <div className={MODAL_BODY}>
    <p>
      {t('tiered.riskCard.stopLine')}{' '}
      <LevelNum levelKey="stop_loss" text={num(values.stop_loss)} onNavigate={onNavigate} />
    </p>
    <p>
      {t('tiered.riskCard.swingLowLine')}{' '}
      <TechNum metric="swing_low_20" text={num(values.swing_low_20)} onNavigate={onNavigate} />
    </p>
    <p className={FORMULA_RESULT.replace('whitespace-nowrap ', '')}>
      {t(
        values.stop_at_or_above_swing_low
          ? 'tiered.riskCard.stopAboveLow'
          : 'tiered.riskCard.stopBelowLow',
      )}
    </p>
  </div>
);

const gapStressReceipt = ({ values, onNavigate, t }: ReceiptProps) => {
  const worstOpen = asNum(values.worst_open);
  return (
    <div className={MODAL_BODY}>
      <div>
        <AltSectionLabel>{t('tiered.riskCard.scenarioWorst')}</AltSectionLabel>
        {worstOpen == null ? (
          <p>{t('tiered.riskCard.noWorstDay')}</p>
        ) : (
          <div className="flex flex-col gap-2">
            <Receipt
              words={
                <>
                  <FVar>open</FVar> = <FVar>entry</FVar> × (1 + <FVar>worst day 1y</FVar>)
                </>
              }
              plugged={
                <>
                  = <LevelNum levelKey="entry" text={num(values.entry)} onNavigate={onNavigate} />{' '}
                  × (1 +{' '}
                  <TechNum
                    metric="worst_day_1y"
                    text={num(values.worst_day_1y)}
                    onNavigate={onNavigate}
                  />
                  )
                </>
              }
              result={`= ${formatPrice(worstOpen)}`}
            />
            {values.worst_gaps_stop ? (
              <Receipt
                words={
                  <>
                    <FVar>loss</FVar> = <FVar>shares</FVar> × (<FVar>entry</FVar> −{' '}
                    <FVar>open</FVar>)
                  </>
                }
                plugged={
                  <>
                    = {num(values.shares)} × (
                    <LevelNum levelKey="entry" text={num(values.entry)} onNavigate={onNavigate} />{' '}
                    − {formatPrice(worstOpen)})
                  </>
                }
                result={`= ${num(values.worst_loss)} (${t('tiered.riskCard.extraVsPlan', {
                  extra: num(values.worst_extra),
                  planned: num(values.loss_at_stop),
                })})`}
              />
            ) : (
              <p>
                {t('tiered.riskCard.worstHolds', {
                  stop: num(values.stop_loss),
                })}
              </p>
            )}
          </div>
        )}
      </div>
      <AltModalDivider />
      <div>
        <AltSectionLabel>{t('tiered.riskCard.scenarioAtr')}</AltSectionLabel>
        <div className="flex flex-col gap-2">
          <Receipt
            words={
              <>
                <FVar>open</FVar> = <FVar>stop loss</FVar> − 1 × <FVar>atr 14</FVar>
              </>
            }
            plugged={
              <>
                ={' '}
                <LevelNum levelKey="stop_loss" text={num(values.stop_loss)} onNavigate={onNavigate} />{' '}
                − 1 × <TechNum metric="atr_14" text={num(values.atr_14)} onNavigate={onNavigate} />
              </>
            }
            result={`= ${num(values.atr_open)}`}
          />
          <Receipt
            words={
              <>
                <FVar>loss</FVar> = <FVar>shares</FVar> × (<FVar>entry</FVar> − <FVar>open</FVar>)
              </>
            }
            plugged={
              <>
                = {num(values.shares)} × (
                <LevelNum levelKey="entry" text={num(values.entry)} onNavigate={onNavigate} /> −{' '}
                {num(values.atr_open)})
              </>
            }
            result={`= ${num(values.atr_loss)} (${t('tiered.riskCard.extraVsPlan', {
              extra: num(values.atr_extra),
              planned: num(values.loss_at_stop),
            })})`}
          />
        </div>
      </div>
    </div>
  );
};

// Receipt builder per current-shape entry id; ids without one (the
// retired legacy ids on old stored runs) render text-only.
const RECEIPTS: Record<string, (props: ReceiptProps) => ReactNode> = {
  liquidity: liquidityReceipt,
  gap_stress: gapStressReceipt,
  volatility: volatilityReceipt,
  reward_risk: rewardRiskReceipt,
  stop_atr: stopAtrReceipt,
  stop_vs_swing_low: stopVsSwingLowReceipt,
};

// The value sentence per entry: the i18n template plus the params to pour
// into it. Legacy ids (old stored runs) keep their original sentences.
const valueParts = (
  entry: TieredRiskCardEntry,
): { key: UiTextKey; params: Record<string, string> } | null => {
  const v = entry.values;
  switch (entry.id) {
    case 'liquidity':
      return {
        key: 'tiered.riskCard.liquidity.value',
        params: { fraction: pct(v.fraction_of_adv), flag: pct(v.flag_fraction) },
      };
    case 'gap_stress': {
      if (v.atr_open === undefined) {
        // Legacy shape (single 1-ATR scenario).
        return {
          key: 'tiered.riskCard.gap_stress.value',
          params: { loss: num(v.loss_if_gap), gapPrice: num(v.gap_price) },
        };
      }
      if (v.worst_open === undefined) {
        return {
          key: 'tiered.riskCard.gap_stress.valueNoWorst',
          params: { atrOpen: num(v.atr_open), atrExtra: num(v.atr_extra) },
        };
      }
      if (v.worst_gaps_stop) {
        return {
          key: 'tiered.riskCard.gap_stress.value2',
          params: {
            worstOpen: num(v.worst_open),
            worstExtra: num(v.worst_extra),
            atrOpen: num(v.atr_open),
            atrExtra: num(v.atr_extra),
          },
        };
      }
      return {
        key: 'tiered.riskCard.gap_stress.valueNoGap',
        params: {
          worstOpen: num(v.worst_open),
          atrOpen: num(v.atr_open),
          atrExtra: num(v.atr_extra),
        },
      };
    }
    case 'volatility':
      return {
        key: 'tiered.riskCard.volatility.value',
        params: { fraction: pct(v.atr_fraction), flag: pct(v.flag_fraction) },
      };
    case 'reward_risk':
      if (v.goal !== undefined) {
        return {
          key: 'tiered.riskCard.reward_risk.value2',
          params: { ratio: num(v.ratio), goal: num(v.goal) },
        };
      }
      return { key: 'tiered.riskCard.reward_risk.value', params: { ratio: num(v.ratio) } };
    case 'stop_atr':
      return {
        key: 'tiered.riskCard.stop_atr.value',
        params: { multiple: num(v.atr_multiple) },
      };
    case 'stop_vs_swing_low':
      return {
        key: 'tiered.riskCard.stop_vs_swing_low.value',
        params: { stop: num(v.stop_loss), low: num(v.swing_low_20) },
      };
    // ---- retired ids old stored runs still carry ----
    case 'concentration':
      return {
        key: 'tiered.riskCard.concentration.value',
        params: { fraction: pct(v.fraction), cap: pct(v.cap_fraction) },
      };
    case 'cash':
      return {
        key: 'tiered.riskCard.cash.value',
        params: { cashLeft: num(v.cash_left), capital: num(v.capital) },
      };
    case 'max_loss':
      return {
        key: 'tiered.riskCard.max_loss.value',
        params: { amount: num(v.risk_amount), fraction: pct(v.fraction) },
      };
    case 'var':
      return {
        key: 'tiered.riskCard.var.value',
        params: { amount: num(v.var_amount), planned: num(v.risk_amount) },
      };
    case 'staleness':
      return {
        key: 'tiered.riskCard.staleness.value',
        params: { close: num(v.close), entry: num(v.entry) },
      };
    case 'both_entries':
      return {
        key: 'tiered.riskCard.both_entries.value',
        params: { risk: num(v.combined_risk), budget: num(v.risk_budget) },
      };
    case 'ownership_context':
      return {
        key: 'tiered.riskCard.ownership_context.value',
        params: { value: num(v.combined_value), fraction: pct(v.combined_fraction) },
      };
    default:
      return null;
  }
};

// Why an entry could not be computed on this run.
const naReasonKey = (entry: TieredRiskCardEntry): UiTextKey => {
  if (entry.id === 'ownership_context') {
    return 'tiered.riskCard.naNoOwnership';
  }
  if (entry.values.is_sized === false) {
    return 'tiered.riskCard.naNotSized';
  }
  return 'tiered.riskCard.naMissingData';
};

const RiskEntryRow = ({ entry, index }: { entry: TieredRiskCardEntry; index: number }) => {
  const { t } = useUiLanguage();
  const [isOpen, setIsOpen] = useState(false);
  const close = () => setIsOpen(false);

  const na = entry.status === 'na';
  const sentence = na ? null : valueParts(entry);
  const receipt = !na && RECEIPTS[entry.id] ? RECEIPTS[entry.id] : null;

  // Every number in the sentence opens the entry's receipt modal (all
  // risk-card numbers are computed, never cited, so the modal shows the
  // computation with each source number linked to where it lives).
  const numberNode = (text: string): ReactNode =>
    receipt ? (
      <button
        type="button"
        className={cn('cursor-pointer tabular-nums', ALT_LINK)}
        onClick={() => setIsOpen(true)}
      >
        {text}
      </button>
    ) : (
      <span className="tabular-nums">{text}</span>
    );

  return (
    <li data-testid={`alt-risk-card-${entry.id}`} className="text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold text-gray-300">
          {index + 1}. {t(`tiered.riskCard.${entry.id}` as UiTextKey)}
        </span>
        <span className={cn(TAG_BASE, STATUS_TAG[entry.status])}>
          {t(STATUS_KEYS[entry.status])}
        </span>
        {na || sentence === null ? (
          <span className="text-gray-500">{t(naReasonKey(entry))}</span>
        ) : (
          <span className="text-gray-300">
            {fillTemplate(
              t(sentence.key),
              Object.fromEntries(
                Object.entries(sentence.params).map(([name, text]) => [name, numberNode(text)]),
              ),
            )}
          </span>
        )}
      </div>
      {!na ? (
        <div className="mt-0.5 flex flex-col gap-0.5 pl-4 text-gray-500">
          <p>
            <span className="font-semibold text-gray-400">
              {t('tiered.riskCard.actionLabel')}
            </span>{' '}
            {t(`tiered.riskCard.${entry.id}.action` as UiTextKey)}
          </p>
          <p>
            <span className="font-semibold text-gray-400">
              {t('tiered.riskCard.reasonLabel')}
            </span>{' '}
            {t(`tiered.riskCard.${entry.id}.reason` as UiTextKey)}
          </p>
        </div>
      ) : null}
      {receipt ? (
        <AltModal
          isOpen={isOpen}
          title={t(`tiered.riskCard.${entry.id}` as UiTextKey)}
          onClose={close}
          panelClassName="w-fit min-w-72 max-w-[95vw]"
        >
          {receipt({ values: entry.values, onNavigate: close, t })}
        </AltModal>
      ) : null}
    </li>
  );
};

export interface AltRiskCardProps {
  entries: TieredRiskCardEntry[];
}

export const AltRiskCard = ({ entries }: AltRiskCardProps) => {
  const { t } = useUiLanguage();
  return (
    <AltCard testId="alt-risk-card">
      <p className="mb-3 text-xs text-gray-500">{t('tiered.riskCard.intro')}</p>
      <ol className="flex flex-col gap-3">
        {entries.map((entry, index) => (
          <RiskEntryRow key={entry.id} entry={entry} index={index} />
        ))}
      </ol>
    </AltCard>
  );
};
