import { Play } from 'lucide-react';
import type { TieredDepth } from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { HelpTerm } from '../tiered/terms';
import { ALT_COLOR, TAG_BASE } from './altStyles';
import { AltPill, AltPillRow, AltSelect } from './AltFields';

const TIERS: TieredDepth[] = [1, 2, 3];

// Dropdown suggestions only — any ticker can still be typed and entered.
const TICKER_IDEAS = ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', '600519', 'hk00700'];
const CAPITAL_IDEAS = ['10000', '50000', '100000', '200000', '500000', '1000000'];
const RISK_IDEAS = ['0.5', '1', '2'];

// Field colors follow the shared palette in field order (ALT_COLOR).
const TONE = {
  ticker: ALT_COLOR[1],
  tier: ALT_COLOR[2],
  capital: ALT_COLOR[3],
  risk: ALT_COLOR[4],
};

const isPositiveNumber = (raw: string): boolean => {
  const value = Number(raw);
  return Number.isFinite(value) && value > 0;
};

const isRiskPct = (raw: string): boolean => {
  const value = Number(raw);
  return Number.isFinite(value) && value > 0 && value < 100;
};

export interface AltRunFormProps {
  ticker: string | null;
  tier: TieredDepth | null;
  capital: string | null;
  riskPct: string | null;
  submitting: boolean;
  error: string | null;
  onTicker: (value: string | null) => void;
  onTier: (value: TieredDepth | null) => void;
  onCapital: (value: string | null) => void;
  onRiskPct: (value: string | null) => void;
  onStart: () => void;
}

// Section 1: the new-run form. Fields are write-only — every choice lands
// as a removable pill below; the Start pill launches the run. Nothing runs
// on change or select. Picking an already-picked option clears it, same as
// clicking its pill.
export const AltRunForm = ({
  ticker,
  tier,
  capital,
  riskPct,
  submitting,
  error,
  onTicker,
  onTier,
  onCapital,
  onRiskPct,
  onStart,
}: AltRunFormProps) => {
  const { t } = useUiLanguage();

  return (
    <div className="flex w-full flex-col gap-4">
      <div className="grid w-full grid-cols-2 gap-2 text-sm sm:grid-cols-4 sm:gap-3 md:gap-4">
        <AltSelect
          label={t('tiered.altForm.ticker')}
          options={TICKER_IDEAS.map((value) => ({ value, label: value }))}
          selected={ticker ? [ticker] : undefined}
          placeholder={t('tiered.altForm.tickerPh')}
          freeText
          onCommit={(value) => onTicker(value === ticker ? null : value)}
        />
        <AltSelect
          label={
            <HelpTerm label={t('tiered.altForm.tier')} helpKey="tiered.help.depth" underline={false} />
          }
          options={TIERS.map((value) => ({ value: String(value), label: String(value) }))}
          selected={tier !== null ? [String(tier)] : undefined}
          placeholder={t('tiered.altForm.tierPh')}
          onCommit={(value) =>
            onTier(Number(value) === tier ? null : (Number(value) as TieredDepth))
          }
        />
        <AltSelect
          label={
            <HelpTerm
              label={t('tiered.altForm.capital')}
              helpKey="tiered.help.sizingForm"
              underline={false}
            />
          }
          options={CAPITAL_IDEAS.map((value) => ({ value, label: value }))}
          selected={capital ? [capital] : undefined}
          placeholder={t('tiered.altForm.capitalPh')}
          inputMode="decimal"
          freeText
          validate={isPositiveNumber}
          onCommit={(value) => onCapital(value === capital ? null : value)}
        />
        <AltSelect
          label={
            <HelpTerm
              label={t('tiered.altForm.risk')}
              helpKey="tiered.help.sizingForm"
              underline={false}
            />
          }
          options={RISK_IDEAS.map((value) => ({ value, label: value }))}
          selected={riskPct ? [riskPct] : undefined}
          placeholder={t('tiered.altForm.riskPh')}
          inputMode="decimal"
          freeText
          validate={isRiskPct}
          onCommit={(value) => onRiskPct(value === riskPct ? null : value)}
        />
      </div>

      <AltPillRow>
        {ticker ? (
          <AltPill tone={TONE.ticker} onRemove={() => onTicker(null)}>
            {t('tiered.pill.ticker', { value: ticker })}
          </AltPill>
        ) : (
          <span className={`${TAG_BASE} ${ALT_COLOR.gray}`}>{t('tiered.altForm.emptyHint')}</span>
        )}
        {tier !== null ? (
          <AltPill tone={TONE.tier} onRemove={() => onTier(null)}>
            {t('tiered.pill.tier', { value: tier })}
          </AltPill>
        ) : null}
        {capital ? (
          <AltPill tone={TONE.capital} onRemove={() => onCapital(null)}>
            {t('tiered.pill.capital', { value: capital })}
          </AltPill>
        ) : null}
        {riskPct ? (
          <AltPill tone={TONE.risk} onRemove={() => onRiskPct(null)}>
            {t('tiered.pill.risk', { value: riskPct })}
          </AltPill>
        ) : null}
        <button
          type="button"
          onClick={onStart}
          disabled={!ticker || submitting}
          className="inline-flex cursor-pointer items-center gap-1.5 rounded bg-indigo-600 px-[9px] py-0.5 text-xs font-semibold text-gray-200 transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Play className="h-3 w-3" />
          {t('tiered.altForm.start')}
        </button>
      </AltPillRow>

      {error ? <p className="text-sm text-red-300">{error}</p> : null}
    </div>
  );
};
