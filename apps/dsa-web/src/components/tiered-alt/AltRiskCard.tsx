import type { TieredRiskCardEntry } from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { cn } from '../../utils/cn';
import { TAG_BASE } from './altStyles';
import { AltCard } from './AltUi';

// The display-only risk card (outlook redesign): 13 deterministic
// pre-trade checks, numbered, each as value → action → reason. By
// explicit owner decision the card affects NOTHING — the run's outlook,
// action, levels and sizing never read it; the user reviews these in
// real runs and decides later which to wire in. The backend ships
// numbers only ({id, status, values}); all wording lives here.

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

// The value sentence per entry, built from the backend's raw numbers.
// Every id has a fixed placeholder set (risk_card.py is the contract).
const valueText = (
  entry: TieredRiskCardEntry,
  t: (key: UiTextKey, params?: Record<string, string | number>) => string,
): string => {
  const v = entry.values;
  switch (entry.id) {
    case 'concentration':
      return t('tiered.riskCard.concentration.value', {
        fraction: pct(v.fraction),
        cap: pct(v.cap_fraction),
      });
    case 'cash':
      return t('tiered.riskCard.cash.value', {
        cashLeft: num(v.cash_left),
        capital: num(v.capital),
      });
    case 'max_loss':
      return t('tiered.riskCard.max_loss.value', {
        amount: num(v.risk_amount),
        fraction: pct(v.fraction),
      });
    case 'liquidity':
      return t('tiered.riskCard.liquidity.value', {
        fraction: pct(v.fraction_of_adv),
        flag: pct(v.flag_fraction),
      });
    case 'var':
      return t('tiered.riskCard.var.value', {
        amount: num(v.var_amount),
        planned: num(v.risk_amount),
      });
    case 'gap_stress':
      return t('tiered.riskCard.gap_stress.value', {
        loss: num(v.loss_if_gap),
        gapPrice: num(v.gap_price),
      });
    case 'volatility':
      return t('tiered.riskCard.volatility.value', {
        fraction: pct(v.atr_fraction),
        flag: pct(v.flag_fraction),
      });
    case 'reward_risk':
      return t('tiered.riskCard.reward_risk.value', { ratio: num(v.ratio) });
    case 'stop_atr':
      return t('tiered.riskCard.stop_atr.value', { multiple: num(v.atr_multiple) });
    case 'stop_vs_swing_low':
      return t('tiered.riskCard.stop_vs_swing_low.value', {
        stop: num(v.stop_loss),
        low: num(v.swing_low_20),
      });
    case 'staleness':
      return t('tiered.riskCard.staleness.value', {
        close: num(v.close),
        entry: num(v.entry),
      });
    case 'both_entries':
      return t('tiered.riskCard.both_entries.value', {
        risk: num(v.combined_risk),
        budget: num(v.risk_budget),
      });
    case 'ownership_context':
      return t('tiered.riskCard.ownership_context.value', {
        value: num(v.combined_value),
        fraction: pct(v.combined_fraction),
      });
    default:
      return '';
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

export interface AltRiskCardProps {
  entries: TieredRiskCardEntry[];
}

export const AltRiskCard = ({ entries }: AltRiskCardProps) => {
  const { t } = useUiLanguage();
  return (
    <AltCard testId="alt-risk-card">
      <p className="mb-3 text-xs text-gray-500">{t('tiered.riskCard.intro')}</p>
      <ol className="flex flex-col gap-3">
        {entries.map((entry, index) => {
          const na = entry.status === 'na';
          return (
            <li
              key={entry.id}
              data-testid={`alt-risk-card-${entry.id}`}
              className="text-xs"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold text-gray-300">
                  {index + 1}. {t(`tiered.riskCard.${entry.id}` as UiTextKey)}
                </span>
                <span className={cn(TAG_BASE, STATUS_TAG[entry.status])}>
                  {t(STATUS_KEYS[entry.status])}
                </span>
                {na ? (
                  <span className="text-gray-500">{t(naReasonKey(entry))}</span>
                ) : (
                  <span className="tabular-nums text-gray-300">{valueText(entry, t)}</span>
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
            </li>
          );
        })}
      </ol>
    </AltCard>
  );
};
