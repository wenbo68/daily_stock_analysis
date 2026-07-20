import { useState } from 'react';
import { Play } from 'lucide-react';
import type { TieredDepth } from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { HelpTerm } from '../tiered/terms';
import { tickerCurrency } from './altCurrency';
import { AltPill, AltPillRow, AltSelect } from './AltFields';
import { AltModal } from './AltUi';

// Tier 3 retired (outlook redesign) — the picker offers 1 and 2 only.
const TIERS: TieredDepth[] = [1, 2];

// Dropdown suggestions only — any ticker can still be typed and entered.
const TICKER_IDEAS = ['AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', '600519', 'hk00700'];
const CAPITAL_IDEAS = ['10000', '50000', '100000', '200000', '500000', '1000000'];
const RISK_IDEAS = ['0.5', '1', '2'];
const OWNERSHIP_IDEAS = ['100', '200', '500', '1000', '2000'];

// Field colors follow the ai-hedge-fund convention — by meaning, not by
// position: cyan = the ticker's identity, plain gray = money values,
// red = the loss you accept, green = a long holding, yellow = neutral
// settings.
const TONE = {
  ticker: 'bg-cyan-500/20 text-cyan-300 ring-cyan-500/30',
  capital: 'bg-gray-500/20 text-gray-300 ring-gray-500/30',
  risk: 'bg-red-500/20 text-red-300 ring-red-500/30',
  ownership: 'bg-emerald-500/20 text-emerald-300 ring-emerald-500/30',
  tier: 'bg-amber-500/20 text-amber-300 ring-amber-500/30',
};

// The Start control is a pill like its neighbors, in the next palette slot.
const START_PILL =
  'inline-flex cursor-pointer items-center gap-1.5 rounded px-[9px] py-0.5 text-xs font-semibold ring-1 ring-inset transition hover:opacity-80 disabled:cursor-not-allowed disabled:opacity-50 bg-indigo-500/20 text-indigo-300 ring-indigo-500/30';

const isPositiveNumber = (raw: string): boolean => {
  const value = Number(raw);
  return Number.isFinite(value) && value > 0;
};

const isRiskPct = (raw: string): boolean => {
  const value = Number(raw);
  return Number.isFinite(value) && value > 0 && value < 100;
};

// Whole positive share counts only — 0 shares is expressed by leaving the
// field unset (its default).
const isShareCount = (raw: string): boolean => {
  const value = Number(raw);
  return Number.isInteger(value) && value > 0;
};

export interface AltRunFormProps {
  ticker: string | null;
  tier: TieredDepth | null;
  capital: string | null;
  riskPct: string | null;
  ownership: string | null;
  submitting: boolean;
  error: string | null;
  onTicker: (value: string | null) => void;
  onTier: (value: TieredDepth | null) => void;
  onCapital: (value: string | null) => void;
  onRiskPct: (value: string | null) => void;
  onOwnership: (value: string | null) => void;
  onStart: () => void;
}

// Section 1: the new-run form. Fields are write-only — every choice lands
// as a removable pill below; the Start pill launches the run only when the
// four required fields are picked (a popup explains otherwise). Ownership
// is the one optional field: no pill means 0 shares held. Capital is in
// the ticker's own trading currency, so it can't be picked before the
// ticker. Picking an already-picked dropdown option clears it, same as
// clicking its pill.
export const AltRunForm = ({
  ticker,
  tier,
  capital,
  riskPct,
  ownership,
  submitting,
  error,
  onTicker,
  onTier,
  onCapital,
  onRiskPct,
  onOwnership,
  onStart,
}: AltRunFormProps) => {
  const { t } = useUiLanguage();
  const [notice, setNotice] = useState<string | null>(null);

  const currency = ticker ? tickerCurrency(ticker) : null;

  const commitCapital = (value: string) => {
    if (!ticker) {
      setNotice(t('tiered.altForm.needTickerFirst'));
      return;
    }
    onCapital(value === capital ? null : value);
  };

  const handleStart = () => {
    if (!ticker || tier === null || !capital || !riskPct) {
      setNotice(t('tiered.altForm.allRequired'));
      return;
    }
    onStart();
  };

  return (
    <div className="flex w-full flex-col gap-4">
      <div className="grid w-full grid-cols-2 gap-2 text-sm sm:grid-cols-5 sm:gap-3 md:gap-4">
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
            <HelpTerm
              label={
                currency
                  ? t('tiered.altForm.capitalCurrency', { currency })
                  : t('tiered.altForm.capital')
              }
              helpKey="tiered.help.capital"
              underline={false}
            />
          }
          options={CAPITAL_IDEAS.map((value) => ({ value, label: value }))}
          selected={capital ? [capital] : undefined}
          placeholder={t('tiered.altForm.capitalPh')}
          inputMode="decimal"
          freeText
          validate={isPositiveNumber}
          onCommit={commitCapital}
        />
        <AltSelect
          label={
            <HelpTerm
              label={t('tiered.altForm.risk')}
              helpKey="tiered.help.riskPct"
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
        <AltSelect
          label={
            <HelpTerm
              label={t('tiered.altForm.ownership')}
              helpKey="tiered.help.ownership"
              underline={false}
            />
          }
          options={OWNERSHIP_IDEAS.map((value) => ({ value, label: value }))}
          selected={ownership ? [ownership] : undefined}
          placeholder={t('tiered.altForm.ownershipPh')}
          inputMode="numeric"
          freeText
          validate={isShareCount}
          onCommit={(value) => onOwnership(value === ownership ? null : value)}
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
      </div>

      <AltPillRow>
        {ticker ? (
          <AltPill tone={TONE.ticker} onRemove={() => onTicker(null)}>
            {t('tiered.pill.ticker', { value: ticker })}
          </AltPill>
        ) : null}
        {capital ? (
          <AltPill tone={TONE.capital} onRemove={() => onCapital(null)}>
            {t('tiered.pill.capital', { value: capital, currency: currency ?? '' }).trim()}
          </AltPill>
        ) : null}
        {riskPct ? (
          <AltPill tone={TONE.risk} onRemove={() => onRiskPct(null)}>
            {t('tiered.pill.risk', { value: riskPct })}
          </AltPill>
        ) : null}
        {ownership ? (
          <AltPill tone={TONE.ownership} onRemove={() => onOwnership(null)}>
            {t('tiered.pill.ownership', { value: ownership })}
          </AltPill>
        ) : null}
        {tier !== null ? (
          <AltPill tone={TONE.tier} onRemove={() => onTier(null)}>
            {t('tiered.pill.tier', { value: tier })}
          </AltPill>
        ) : null}
        <button type="button" onClick={handleStart} disabled={submitting} className={START_PILL}>
          <Play className="h-3 w-3" />
          {t('tiered.altForm.start')}
        </button>
      </AltPillRow>

      {error ? <p className="text-sm text-red-300">{error}</p> : null}

      <AltModal
        isOpen={notice !== null}
        title={t('tiered.altForm.noticeTitle')}
        onClose={() => setNotice(null)}
      >
        <p className="text-sm leading-relaxed">{notice}</p>
      </AltModal>
    </div>
  );
};
