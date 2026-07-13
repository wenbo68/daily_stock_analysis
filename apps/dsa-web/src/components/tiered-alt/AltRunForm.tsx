import { Play } from 'lucide-react';
import type { TieredDepth } from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { HelpTerm } from '../tiered/terms';
import { PILL_TONE, TAG_BASE } from './altStyles';
import { AltPill, AltPillRow, AltSelect } from './AltFields';

const DEPTHS: TieredDepth[] = [1, 2, 3];

// Dropdown suggestions only — any ticker can still be typed and entered.
const TICKER_IDEAS = ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', '600519', 'hk00700'];
const CAPITAL_IDEAS = ['10000', '50000', '100000', '200000', '500000', '1000000'];
const RISK_IDEAS = ['0.5', '1', '2'];

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
  depth: TieredDepth | null;
  capital: string | null;
  riskPct: string | null;
  submitting: boolean;
  error: string | null;
  onTicker: (value: string | null) => void;
  onDepth: (value: TieredDepth | null) => void;
  onCapital: (value: string | null) => void;
  onRiskPct: (value: string | null) => void;
  onStart: () => void;
}

// Section 1: the new-run form. Fields are write-only — every choice lands
// as a removable pill below; the Start pill launches the run. Nothing runs
// on change or select.
export const AltRunForm = ({
  ticker,
  depth,
  capital,
  riskPct,
  submitting,
  error,
  onTicker,
  onDepth,
  onCapital,
  onRiskPct,
  onStart,
}: AltRunFormProps) => {
  const { t } = useUiLanguage();

  return (
    <div className="flex w-full flex-col gap-4">
      <h2 className="font-semibold text-gray-300">{t('tiered.altForm.title')}</h2>

      <div className="grid w-full grid-cols-2 gap-2 text-sm sm:grid-cols-4 sm:gap-3 md:gap-4">
        <AltSelect
          label={t('tiered.altForm.ticker')}
          options={TICKER_IDEAS.map((value) => ({ value, label: value }))}
          value={ticker ?? undefined}
          placeholder={t('tiered.inputPlaceholder')}
          freeText
          onCommit={(value) => onTicker(value)}
        />
        <AltSelect
          label={
            <HelpTerm label={t('tiered.depth.label')} helpKey="tiered.help.depth" underline={false} />
          }
          options={DEPTHS.map((value) => ({
            value: String(value),
            label: t(`tiered.depth.${value}` as UiTextKey),
          }))}
          value={String(depth ?? 1)}
          placeholder={t('tiered.depth.1')}
          onCommit={(value) => onDepth(Number(value) as TieredDepth)}
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
          value={capital ?? undefined}
          placeholder={t('tiered.sizingForm.capital')}
          inputMode="decimal"
          freeText
          validate={isPositiveNumber}
          onCommit={(value) => onCapital(value)}
        />
        <AltSelect
          label={
            <HelpTerm
              label={t('tiered.altForm.risk')}
              helpKey="tiered.help.sizingForm"
              underline={false}
            />
          }
          options={RISK_IDEAS.map((value) => ({ value, label: `${value} %` }))}
          value={riskPct ?? undefined}
          placeholder={t('tiered.sizingForm.riskPct')}
          inputMode="decimal"
          freeText
          validate={isRiskPct}
          onCommit={(value) => onRiskPct(value)}
        />
      </div>

      <AltPillRow>
        {ticker ? (
          <AltPill tone={PILL_TONE.ticker} onRemove={() => onTicker(null)}>
            {ticker}
          </AltPill>
        ) : (
          <span className={`${TAG_BASE} ${PILL_TONE.neutral}`}>{t('tiered.altForm.emptyHint')}</span>
        )}
        {depth !== null ? (
          <AltPill tone={PILL_TONE.depth} onRemove={() => onDepth(null)}>
            {t(`tiered.depth.${depth}` as UiTextKey)}
          </AltPill>
        ) : null}
        {capital ? (
          <AltPill tone={PILL_TONE.capital} onRemove={() => onCapital(null)}>
            {t('tiered.pill.capital', { value: capital })}
          </AltPill>
        ) : null}
        {riskPct ? (
          <AltPill tone={PILL_TONE.risk} onRemove={() => onRiskPct(null)}>
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
