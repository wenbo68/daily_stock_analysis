import type { TieredSizing } from '../../api/tiered';
import { Card } from '../common';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { formatPrice } from './termHelpers';
import { HelpTerm } from './terms';

// Stable machine-readable refusal codes → plain-language explanations.
const REASON_KEYS: Record<string, UiTextKey> = {
  sizing_off: 'tiered.sizing.reason.sizing_off',
  not_a_buy: 'tiered.sizing.reason.not_a_buy',
  no_entry: 'tiered.sizing.reason.no_entry',
  no_stop: 'tiered.sizing.reason.no_stop',
  stop_not_below_entry: 'tiered.sizing.reason.stop_not_below_entry',
  invalid_input: 'tiered.sizing.reason.invalid_input',
  too_small: 'tiered.sizing.reason.too_small',
};

interface StatProps {
  labelKey: UiTextKey;
  helpKey: UiTextKey;
  value: string;
}

const Stat = ({ labelKey, helpKey, value }: StatProps) => {
  const { t } = useUiLanguage();
  return (
    <div className="rounded-xl border border-border/40 bg-elevated/60 px-3 py-2">
      <div className="text-xs text-secondary-text">
        <HelpTerm label={t(labelKey)} helpKey={helpKey} />
      </div>
      <div className="mt-1 font-mono text-base text-foreground">{value}</div>
    </div>
  );
};

interface SizingCardProps {
  sizing: TieredSizing;
}

// Position sizing: how many shares the formula computed — or, just as
// deliberately, why it refused to print a number. Three states: sized,
// refused (plain-words reason), and off (explicit "fill in your capital
// and risk to turn this on").
export const SizingCard = ({ sizing }: SizingCardProps) => {
  const { t } = useUiLanguage();
  const isSized = sizing.shares !== null;
  const isOff = sizing.reason_code === 'sizing_off';
  const reasonKey = sizing.reason_code ? REASON_KEYS[sizing.reason_code] : undefined;

  return (
    <Card className="p-4" data-testid="sizing-card">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-foreground">
          <HelpTerm label={t('tiered.sizing.title')} helpKey="tiered.help.sizing" />
        </h3>
      </div>

      {isOff ? (
        <div data-testid="sizing-off">
          <p className="text-sm text-secondary-text">{t('tiered.sizing.offExplainer')}</p>
          <p className="mt-2 text-xs text-secondary-text">{t('tiered.sizing.offHint')}</p>
        </div>
      ) : isSized ? (
        <div data-testid="sizing-result">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Stat
              labelKey="tiered.sizing.shares"
              helpKey="tiered.help.shares"
              value={String(sizing.shares)}
            />
            <Stat
              labelKey="tiered.sizing.positionValue"
              helpKey="tiered.help.positionValue"
              value={formatPrice(sizing.position_value)}
            />
            <Stat
              labelKey="tiered.sizing.riskAmount"
              helpKey="tiered.help.riskAmount"
              value={formatPrice(sizing.risk_amount)}
            />
            <Stat
              labelKey="tiered.sizing.stopUsed"
              helpKey="tiered.help.stopUsed"
              value={formatPrice(sizing.inputs.stop_loss)}
            />
          </div>

          {sizing.risk_multiplier !== null && sizing.shares_before_multiplier !== null ? (
            <p className="mt-2 text-xs text-secondary-text">
              {t('tiered.sizing.multiplierApplied', {
                before: sizing.shares_before_multiplier,
                multiplier: sizing.risk_multiplier,
                after: sizing.shares ?? 0,
              })}
            </p>
          ) : null}
          {sizing.shares === 0 ? (
            <p className="mt-2 text-sm font-medium text-warning">
              {t('tiered.sizing.zeroShares')}
            </p>
          ) : null}
          {sizing.cap_applied ? (
            <p className="mt-2 text-xs text-secondary-text">{t('tiered.sizing.capApplied')}</p>
          ) : null}
          <p className="mt-2 text-xs text-secondary-text">
            {t('tiered.sizing.inputsLine', {
              capital: formatPrice(sizing.inputs.capital),
              riskPct:
                sizing.inputs.risk_fraction !== null
                  ? (sizing.inputs.risk_fraction * 100).toFixed(1)
                  : '—',
              entry: formatPrice(sizing.inputs.entry),
            })}
          </p>
        </div>
      ) : (
        <div data-testid="sizing-refused">
          <p className="text-sm text-warning">
            {reasonKey ? t(reasonKey) : sizing.refusal_reason}
          </p>
          {reasonKey && sizing.refusal_reason ? (
            <p className="mt-1 text-xs text-secondary-text">{sizing.refusal_reason}</p>
          ) : null}
        </div>
      )}

      {sizing.notes.length > 0 ? (
        <ul className="mt-3 space-y-1">
          {sizing.notes.map((note, index) => (
            <li key={index} className="text-xs text-secondary-text">
              {note}
            </li>
          ))}
        </ul>
      ) : null}
    </Card>
  );
};
