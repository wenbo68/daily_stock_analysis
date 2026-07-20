import { useMemo, useState } from 'react';
import type { TieredResult, TieredRunSummary } from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { cn } from '../../utils/cn';
import { plainNumber, riskPctText } from './altFormat';
import { ALT_COLOR, OUTLOOK_TEXT, STATUS_DOT } from './altStyles';
import { AltPageSelector, AltPairField, AltPill, AltPillRow, AltSelect } from './AltFields';
import { AltResult } from './AltResult';

const PAGE_SIZE = 10;
// Outlook redesign: the verdict filter became the outlook filter. Old
// stored runs are mapped by the backend digest (buy→bullish, …).
const FILTER_OUTLOOKS = ['bullish', 'neutral', 'bearish'] as const;
// Old stored runs went to tier 3, so the history filter keeps offering it.
const FILTER_TIERS = ['1', '2', '3'] as const;

// The filter grid and every run row share this template, so each row value
// sits exactly under its filter column.
const ROW_GRID = 'grid w-full grid-cols-2 gap-2 sm:grid-cols-3 sm:gap-3 lg:grid-cols-4 lg:gap-4 xl:grid-cols-7';

// Filter colors follow the shared palette in field order; a range's Min
// and Max share one color (ALT_COLOR).
const TONE = {
  ticker: ALT_COLOR[1],
  capital: ALT_COLOR[2],
  risk: ALT_COLOR[3],
  tier: ALT_COLOR[4],
  verdict: ALT_COLOR[5],
  shares: ALT_COLOR[6],
  date: ALT_COLOR[7],
};

// Accepts 2026/07/14 or 2026-07-14; day boundaries are the viewer's local time.
const DAY_RE = /^\d{4}[/-]\d{2}[/-]\d{2}$/;

const isValidDay = (raw: string): boolean => {
  if (!DAY_RE.test(raw)) {
    return false;
  }
  return !Number.isNaN(parseDay(raw).getTime());
};

function parseDay(raw: string, plusDays = 0): Date {
  const [year, month, day] = raw.split(/[/-]/).map(Number);
  return new Date(year, month - 1, day + plusDays);
}

const isWholeNumber = (raw: string): boolean => /^\d+$/.test(raw);

const isPositiveNumber = (raw: string): boolean => {
  const value = Number(raw);
  return Number.isFinite(value) && value > 0;
};

const isRiskPct = (raw: string): boolean => {
  const value = Number(raw);
  return Number.isFinite(value) && value > 0 && value < 100;
};

function runTime(run: TieredRunSummary): Date | null {
  if (!run.created_at) {
    return null;
  }
  const date = new Date(run.created_at.endsWith('Z') ? run.created_at : `${run.created_at}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

// yyyy/mm/dd, hh:mm in the viewer's local time, 24-hour clock.
function formatTime(run: TieredRunSummary): string {
  const date = runTime(run);
  if (!date) {
    return '—';
  }
  const pad = (part: number) => String(part).padStart(2, '0');
  return (
    `${date.getFullYear()}/${pad(date.getMonth() + 1)}/${pad(date.getDate())}, ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}

// The run's risk input as the percent the user typed ('1%'), or a dash.
function riskCell(run: TieredRunSummary): string {
  return run.risk_fraction == null ? '—' : `${riskPctText(run.risk_fraction)}%`;
}

// The row's outlook: stored on new runs; rows fetched before the backend
// digest existed map their legacy verdict here as a fallback.
const LEGACY_OUTLOOK: Record<string, string> = {
  buy: 'bullish',
  hold: 'neutral',
  sell: 'bearish',
};

function runOutlook(run: TieredRunSummary): string {
  return run.outlook ?? LEGACY_OUTLOOK[run.direction ?? ''] ?? 'unknown';
}

interface HistoryFilters {
  tickers: string[];
  capitalMin: string | null;
  capitalMax: string | null;
  riskMin: string | null;
  riskMax: string | null;
  tiers: string[];
  outlooks: string[];
  sharesMin: string | null;
  sharesMax: string | null;
  dateMin: string | null;
  dateMax: string | null;
}

const NO_FILTERS: HistoryFilters = {
  tickers: [],
  capitalMin: null,
  capitalMax: null,
  riskMin: null,
  riskMax: null,
  tiers: [],
  outlooks: [],
  sharesMin: null,
  sharesMax: null,
  dateMin: null,
  dateMax: null,
};

// Add the value if absent, remove it if present — how multi-value filters
// clear from the dropdown as well as from the pill.
function toggled(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((item) => item !== value) : [...list, value];
}

function matchesFilters(run: TieredRunSummary, filters: HistoryFilters): boolean {
  if (filters.tickers.length > 0 && !filters.tickers.includes(run.stock_code)) {
    return false;
  }
  if (filters.capitalMin && !(run.capital != null && run.capital >= Number(filters.capitalMin))) {
    return false;
  }
  if (filters.capitalMax && !(run.capital != null && run.capital <= Number(filters.capitalMax))) {
    return false;
  }
  const riskPct = run.risk_fraction != null ? run.risk_fraction * 100 : null;
  if (filters.riskMin && !(riskPct != null && riskPct >= Number(filters.riskMin))) {
    return false;
  }
  if (filters.riskMax && !(riskPct != null && riskPct <= Number(filters.riskMax))) {
    return false;
  }
  if (filters.tiers.length > 0 && !filters.tiers.includes(String(run.tier ?? ''))) {
    return false;
  }
  if (filters.outlooks.length > 0 && !filters.outlooks.includes(runOutlook(run))) {
    return false;
  }
  if (filters.sharesMin && !(run.shares != null && run.shares >= Number(filters.sharesMin))) {
    return false;
  }
  if (filters.sharesMax && !(run.shares != null && run.shares <= Number(filters.sharesMax))) {
    return false;
  }
  const time = runTime(run);
  if (filters.dateMin && (!time || time < parseDay(filters.dateMin))) {
    return false;
  }
  if (filters.dateMax && (!time || time >= parseDay(filters.dateMax, 1))) {
    return false;
  }
  return true;
}

export interface AltRunHistoryProps {
  runs: TieredRunSummary[];
  expandedTaskId: string | null;
  expandedResult: TieredResult | null;
  expandedError: string | null;
  onToggle: (taskId: string) => void;
}

// Section 2: run history. Filters at the top apply the moment something is
// entered or picked — no search button — and show as removable pills
// (ticker, tier and verdict take several values at once). Below, one row
// per run (10 per page), each fact sitting directly under its filter:
// ticker, capital, risk, tier, verdict, shares, date. Clicking a row
// expands the full report inline. A freshly started run appears at the top
// as Running and turns into a normal row when it finishes.
export const AltRunHistory = ({
  runs,
  expandedTaskId,
  expandedResult,
  expandedError,
  onToggle,
}: AltRunHistoryProps) => {
  const { t } = useUiLanguage();
  const [filters, setFilters] = useState<HistoryFilters>(NO_FILTERS);
  const [page, setPage] = useState(1);

  const updateFilters = (patch: Partial<HistoryFilters>) => {
    setFilters((prev) => ({ ...prev, ...patch }));
    setPage(1);
  };

  // Every ticker that has ever been run, for the ticker filter's dropdown.
  const knownTickers = useMemo(
    () => Array.from(new Set(runs.map((run) => run.stock_code))).sort(),
    [runs],
  );

  const filtered = useMemo(
    () => runs.filter((run) => matchesFilters(run, filters)),
    [runs, filters],
  );
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount);
  const visible = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  const hasFilters =
    filters.tickers.length > 0 ||
    filters.tiers.length > 0 ||
    filters.outlooks.length > 0 ||
    filters.capitalMin !== null ||
    filters.capitalMax !== null ||
    filters.riskMin !== null ||
    filters.riskMax !== null ||
    filters.sharesMin !== null ||
    filters.sharesMax !== null ||
    filters.dateMin !== null ||
    filters.dateMax !== null;

  // Pills in filter order: ticker, capital, risk, tier, verdict, shares, date.
  const pills: { key: string; tone: string; label: string; onRemove: () => void }[] = [];
  filters.tickers.forEach((ticker) => {
    pills.push({
      key: `ticker-${ticker}`,
      tone: TONE.ticker,
      label: t('tiered.pill.ticker', { value: ticker }),
      onRemove: () => updateFilters({ tickers: toggled(filters.tickers, ticker) }),
    });
  });
  ([
    ['capitalMin', TONE.capital, 'tiered.pill.capitalMin'],
    ['capitalMax', TONE.capital, 'tiered.pill.capitalMax'],
    ['riskMin', TONE.risk, 'tiered.pill.riskMin'],
    ['riskMax', TONE.risk, 'tiered.pill.riskMax'],
  ] as const).forEach(([field, tone, labelKey]) => {
    const value = filters[field];
    if (value) {
      pills.push({
        key: field,
        tone,
        label: t(labelKey, { value }),
        onRemove: () => updateFilters({ [field]: null }),
      });
    }
  });
  filters.tiers.forEach((tier) => {
    pills.push({
      key: `tier-${tier}`,
      tone: TONE.tier,
      label: t('tiered.pill.tier', { value: tier }),
      onRemove: () => updateFilters({ tiers: toggled(filters.tiers, tier) }),
    });
  });
  filters.outlooks.forEach((outlook) => {
    pills.push({
      key: `outlook-${outlook}`,
      tone: TONE.verdict,
      label: t('tiered.pill.outlook', {
        value: t(`tiered.outlook.${outlook}` as UiTextKey),
      }),
      onRemove: () => updateFilters({ outlooks: toggled(filters.outlooks, outlook) }),
    });
  });
  ([
    ['sharesMin', TONE.shares, 'tiered.pill.sharesMin'],
    ['sharesMax', TONE.shares, 'tiered.pill.sharesMax'],
    ['dateMin', TONE.date, 'tiered.pill.dateMin'],
    ['dateMax', TONE.date, 'tiered.pill.dateMax'],
  ] as const).forEach(([field, tone, labelKey]) => {
    const value = filters[field];
    if (value) {
      pills.push({
        key: field,
        tone,
        label: t(labelKey, { value }),
        onRemove: () => updateFilters({ [field]: null }),
      });
    }
  });

  return (
    <div className="flex w-full flex-col gap-4">
      <div className={cn(ROW_GRID, 'text-sm')}>
        <AltSelect
          label={t('tiered.altForm.ticker')}
          options={knownTickers.map((value) => ({ value, label: value }))}
          selected={filters.tickers}
          placeholder={t('tiered.altFilter.tickerPh')}
          multi
          onCommit={(value) => updateFilters({ tickers: toggled(filters.tickers, value) })}
        />
        <AltPairField
          label={t('tiered.altFilter.capital')}
          start={{
            placeholder: t('tiered.altFilter.min'),
            inputMode: 'decimal',
            validate: isPositiveNumber,
            onCommit: (value) => updateFilters({ capitalMin: value }),
          }}
          end={{
            placeholder: t('tiered.altFilter.max'),
            inputMode: 'decimal',
            validate: isPositiveNumber,
            onCommit: (value) => updateFilters({ capitalMax: value }),
          }}
        />
        <AltPairField
          label={t('tiered.altFilter.risk')}
          start={{
            placeholder: t('tiered.altFilter.min'),
            inputMode: 'decimal',
            validate: isRiskPct,
            onCommit: (value) => updateFilters({ riskMin: value }),
          }}
          end={{
            placeholder: t('tiered.altFilter.max'),
            inputMode: 'decimal',
            validate: isRiskPct,
            onCommit: (value) => updateFilters({ riskMax: value }),
          }}
        />
        <AltSelect
          label={t('tiered.altFilter.tier')}
          options={FILTER_TIERS.map((value) => ({ value, label: value }))}
          selected={filters.tiers}
          placeholder={t('tiered.altFilter.tierPh')}
          multi
          onCommit={(value) => updateFilters({ tiers: toggled(filters.tiers, value) })}
        />
        <AltSelect
          label={t('tiered.altFilter.outlook')}
          options={FILTER_OUTLOOKS.map((value) => ({
            value,
            label: t(`tiered.outlook.${value}` as UiTextKey),
          }))}
          selected={filters.outlooks}
          placeholder={t('tiered.altFilter.outlookPh')}
          multi
          onCommit={(value) => updateFilters({ outlooks: toggled(filters.outlooks, value) })}
        />
        <AltPairField
          label={t('tiered.altFilter.shares')}
          start={{
            placeholder: t('tiered.altFilter.min'),
            inputMode: 'decimal',
            validate: isWholeNumber,
            onCommit: (value) => updateFilters({ sharesMin: value }),
          }}
          end={{
            placeholder: t('tiered.altFilter.max'),
            inputMode: 'decimal',
            validate: isWholeNumber,
            onCommit: (value) => updateFilters({ sharesMax: value }),
          }}
        />
        <AltPairField
          label={t('tiered.altFilter.date')}
          start={{
            placeholder: t('tiered.altFilter.min'),
            validate: isValidDay,
            onCommit: (value) => updateFilters({ dateMin: value }),
          }}
          end={{
            placeholder: t('tiered.altFilter.max'),
            validate: isValidDay,
            onCommit: (value) => updateFilters({ dateMax: value }),
          }}
        />
      </div>

      {/* the row keeps its height when empty so pills cause no layout shift */}
      <AltPillRow>
        {pills.map((pill) => (
          <AltPill key={pill.key} tone={pill.tone} onRemove={pill.onRemove}>
            {pill.label}
          </AltPill>
        ))}
      </AltPillRow>

      {visible.length === 0 ? (
        <p className="py-8 text-center text-sm text-gray-600">
          {hasFilters && runs.length > 0 ? t('tiered.altHistory.none') : t('tiered.empty')}
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-gray-800">
          {visible.map((run) => {
            const isExpanded = run.task_id === expandedTaskId;
            return (
              <li key={run.task_id}>
                <button
                  type="button"
                  onClick={() => onToggle(run.task_id)}
                  className={cn(
                    ROW_GRID,
                    'cursor-pointer items-center rounded py-2.5 text-start text-sm hover:bg-gray-800/60',
                    isExpanded ? 'bg-gray-800/40' : '',
                  )}
                >
                  <span className="flex min-w-0 items-center gap-3">
                    <span
                      className={cn('h-1.5 w-1.5 shrink-0 rounded-full', STATUS_DOT[run.status])}
                    />
                    <span className="truncate font-semibold text-gray-300">{run.stock_code}</span>
                  </span>
                  <span
                    id={`alt-run-${run.task_id}-capital`}
                    className="text-xs tabular-nums text-gray-400"
                  >
                    {run.capital == null ? '—' : plainNumber(run.capital)}
                  </span>
                  <span
                    id={`alt-run-${run.task_id}-risk`}
                    className="text-xs tabular-nums text-gray-400"
                  >
                    {riskCell(run)}
                  </span>
                  <span className="text-xs text-gray-500">
                    {run.tier == null ? '—' : t('tiered.altHistory.tier', { value: run.tier })}
                  </span>
                  {run.status === 'running' ? (
                    <span className="text-xs text-sky-300">{t('tiered.status.running')}</span>
                  ) : run.status === 'failed' ? (
                    <span className="text-xs text-red-300">{t('tiered.status.failed')}</span>
                  ) : (
                    <span className={cn('text-xs', OUTLOOK_TEXT[runOutlook(run)])}>
                      {t(`tiered.outlook.${runOutlook(run)}` as UiTextKey)}
                    </span>
                  )}
                  <span className="text-xs tabular-nums text-gray-400">
                    {run.shares == null ? '—' : t('tiered.altHistory.shares', { value: run.shares })}
                  </span>
                  <span className="truncate text-xs tabular-nums text-gray-500">
                    {formatTime(run)}
                  </span>
                </button>
                {isExpanded ? (
                  <div className="pb-5 pt-3">
                    {run.status === 'failed' ? (
                      <p className="text-sm text-red-300">
                        {run.error ?? expandedError ?? t('tiered.error.title')}
                      </p>
                    ) : run.status === 'running' ? (
                      <p className="text-sm text-gray-500">{t('tiered.running')}</p>
                    ) : expandedResult ? (
                      <AltResult
                        result={expandedResult}
                        taskId={run.task_id}
                        runDate={runTime(run)}
                      />
                    ) : expandedError ? (
                      <p className="text-sm text-red-300">{expandedError}</p>
                    ) : (
                      <p className="text-sm text-gray-500">{t('tiered.altHistory.loading')}</p>
                    )}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}

      <AltPageSelector
        page={safePage}
        pageCount={pageCount}
        onPage={setPage}
        labels={{
          first: t('tiered.altHistory.first'),
          prev: t('tiered.altHistory.prev'),
          next: t('tiered.altHistory.next'),
          last: t('tiered.altHistory.last'),
        }}
      />
    </div>
  );
};
