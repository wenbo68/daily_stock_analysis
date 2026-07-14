import { useMemo, useState } from 'react';
import type { TieredResult, TieredRunSummary } from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { cn } from '../../utils/cn';
import { ALT_COLOR, DIRECTION_TAG, STATUS_DOT, TAG_BASE } from './altStyles';
import { AltPageSelector, AltPairField, AltPill, AltPillRow, AltSelect } from './AltFields';
import { AltResult } from './AltResult';
import { AltTag } from './AltUi';

const PAGE_SIZE = 10;
const FILTER_DIRECTIONS = ['buy', 'hold', 'sell'] as const;
const FILTER_TIERS = ['1', '2', '3'] as const;

const RUNNING_TAG = 'bg-sky-500/20 text-sky-300 ring-sky-500/30';
const FAILED_TAG = 'bg-red-500/20 text-red-300 ring-red-500/30';

// Filter colors follow the shared palette in field order; a range's Min
// and Max share one color (ALT_COLOR).
const TONE = {
  ticker: ALT_COLOR[1],
  date: ALT_COLOR[2],
  verdict: ALT_COLOR[3],
  tier: ALT_COLOR[4],
  shares: ALT_COLOR[5],
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

interface HistoryFilters {
  tickers: string[];
  dateMin: string | null;
  dateMax: string | null;
  directions: string[];
  tiers: string[];
  sharesMin: string | null;
  sharesMax: string | null;
}

const NO_FILTERS: HistoryFilters = {
  tickers: [],
  dateMin: null,
  dateMax: null,
  directions: [],
  tiers: [],
  sharesMin: null,
  sharesMax: null,
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
  if (filters.directions.length > 0 && !filters.directions.includes(run.direction ?? '')) {
    return false;
  }
  if (filters.tiers.length > 0 && !filters.tiers.includes(String(run.tier ?? ''))) {
    return false;
  }
  const time = runTime(run);
  if (filters.dateMin && (!time || time < parseDay(filters.dateMin))) {
    return false;
  }
  if (filters.dateMax && (!time || time >= parseDay(filters.dateMax, 1))) {
    return false;
  }
  if (filters.sharesMin && !(run.shares != null && run.shares >= Number(filters.sharesMin))) {
    return false;
  }
  if (filters.sharesMax && !(run.shares != null && run.shares <= Number(filters.sharesMax))) {
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
// (ticker, verdict and tier take several values at once). Below, one row
// per run (10 per page); clicking a row expands the full report inline. A
// freshly started run appears at the top as Running and turns into a
// normal row when it finishes.
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
    filters.directions.length > 0 ||
    filters.tiers.length > 0 ||
    filters.dateMin !== null ||
    filters.dateMax !== null ||
    filters.sharesMin !== null ||
    filters.sharesMax !== null;

  const pills: { key: string; tone: string; label: string; onRemove: () => void }[] = [];
  filters.tickers.forEach((ticker) => {
    pills.push({
      key: `ticker-${ticker}`,
      tone: TONE.ticker,
      label: t('tiered.pill.ticker', { value: ticker }),
      onRemove: () => updateFilters({ tickers: toggled(filters.tickers, ticker) }),
    });
  });
  if (filters.dateMin) {
    pills.push({
      key: 'dateMin',
      tone: TONE.date,
      label: t('tiered.pill.dateMin', { value: filters.dateMin }),
      onRemove: () => updateFilters({ dateMin: null }),
    });
  }
  if (filters.dateMax) {
    pills.push({
      key: 'dateMax',
      tone: TONE.date,
      label: t('tiered.pill.dateMax', { value: filters.dateMax }),
      onRemove: () => updateFilters({ dateMax: null }),
    });
  }
  filters.directions.forEach((direction) => {
    pills.push({
      key: `direction-${direction}`,
      tone: TONE.verdict,
      label: t('tiered.pill.verdict', {
        value: t(`tiered.direction.${direction}` as UiTextKey),
      }),
      onRemove: () => updateFilters({ directions: toggled(filters.directions, direction) }),
    });
  });
  filters.tiers.forEach((tier) => {
    pills.push({
      key: `tier-${tier}`,
      tone: TONE.tier,
      label: t('tiered.pill.tier', { value: tier }),
      onRemove: () => updateFilters({ tiers: toggled(filters.tiers, tier) }),
    });
  });
  if (filters.sharesMin) {
    pills.push({
      key: 'sharesMin',
      tone: TONE.shares,
      label: t('tiered.pill.sharesMin', { value: filters.sharesMin }),
      onRemove: () => updateFilters({ sharesMin: null }),
    });
  }
  if (filters.sharesMax) {
    pills.push({
      key: 'sharesMax',
      tone: TONE.shares,
      label: t('tiered.pill.sharesMax', { value: filters.sharesMax }),
      onRemove: () => updateFilters({ sharesMax: null }),
    });
  }

  return (
    <div className="flex w-full flex-col gap-4">
      <div className="grid w-full grid-cols-2 gap-2 text-sm sm:grid-cols-3 sm:gap-3 lg:grid-cols-5 lg:gap-4">
        <AltSelect
          label={t('tiered.altForm.ticker')}
          options={knownTickers.map((value) => ({ value, label: value }))}
          selected={filters.tickers}
          placeholder={t('tiered.altFilter.tickerPh')}
          multi
          onCommit={(value) => updateFilters({ tickers: toggled(filters.tickers, value) })}
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
        <AltSelect
          label={t('tiered.altFilter.direction')}
          options={FILTER_DIRECTIONS.map((value) => ({
            value,
            label: t(`tiered.direction.${value}` as UiTextKey),
          }))}
          selected={filters.directions}
          placeholder={t('tiered.altFilter.directionPh')}
          multi
          onCommit={(value) => updateFilters({ directions: toggled(filters.directions, value) })}
        />
        <AltSelect
          label={t('tiered.altFilter.tier')}
          options={FILTER_TIERS.map((value) => ({ value, label: value }))}
          selected={filters.tiers}
          placeholder={t('tiered.altFilter.tierPh')}
          multi
          onCommit={(value) => updateFilters({ tiers: toggled(filters.tiers, value) })}
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
      </div>

      <AltPillRow>
        {pills.length === 0 ? (
          <span className={`${TAG_BASE} ${ALT_COLOR.gray}`}>{t('tiered.altFilter.empty')}</span>
        ) : (
          pills.map((pill) => (
            <AltPill key={pill.key} tone={pill.tone} onRemove={pill.onRemove}>
              {pill.label}
            </AltPill>
          ))
        )}
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
                    'flex w-full cursor-pointer items-center gap-3 rounded px-2 py-2.5 text-start text-sm hover:bg-gray-800/60',
                    isExpanded ? 'bg-gray-800/40' : '',
                  )}
                >
                  <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', STATUS_DOT[run.status])} />
                  <span className="w-20 shrink-0 font-semibold text-gray-300 sm:w-24">
                    {run.stock_code}
                  </span>
                  <span className="flex-1 text-xs tabular-nums text-gray-500">{formatTime(run)}</span>
                  <span className="w-12 shrink-0 text-xs text-gray-500 sm:w-14">
                    {run.tier == null ? '—' : t('tiered.altHistory.tier', { value: run.tier })}
                  </span>
                  {run.status === 'running' ? (
                    <AltTag tone={RUNNING_TAG}>{t('tiered.status.running')}</AltTag>
                  ) : run.status === 'failed' ? (
                    <AltTag tone={FAILED_TAG}>{t('tiered.status.failed')}</AltTag>
                  ) : (
                    <AltTag tone={DIRECTION_TAG[run.direction ?? 'unknown']}>
                      {t(`tiered.direction.${run.direction ?? 'unknown'}` as UiTextKey)}
                    </AltTag>
                  )}
                  <span className="w-20 shrink-0 text-right text-xs tabular-nums text-gray-400 sm:w-24">
                    {run.shares == null ? '—' : t('tiered.altHistory.shares', { value: run.shares })}
                  </span>
                </button>
                {isExpanded ? (
                  <div className="px-2 pb-5 pt-3">
                    {run.status === 'failed' ? (
                      <p className="text-sm text-red-300">
                        {run.error ?? expandedError ?? t('tiered.error.title')}
                      </p>
                    ) : run.status === 'running' ? (
                      <p className="text-sm text-gray-500">{t('tiered.running')}</p>
                    ) : expandedResult ? (
                      <AltResult result={expandedResult} />
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
