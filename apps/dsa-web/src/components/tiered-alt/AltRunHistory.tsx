import { useMemo, useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import type { TieredResult, TieredRunSummary } from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiLanguage, UiTextKey } from '../../i18n/uiText';
import { cn } from '../../utils/cn';
import { DIRECTION_TAG, PILL_TONE, STATUS_DOT, TAG_BASE } from './altStyles';
import { AltPairField, AltPill, AltPillRow, AltSelect, AltTextField } from './AltFields';
import { AltResult } from './AltResult';
import { AltTag } from './AltUi';

const PAGE_SIZE = 15;
const FILTER_DIRECTIONS = ['buy', 'hold', 'sell'] as const;

const RUNNING_TAG = 'bg-sky-500/20 text-sky-300 ring-sky-500/30';
const FAILED_TAG = 'bg-red-500/20 text-red-300 ring-red-500/30';

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

function formatTime(run: TieredRunSummary, language: UiLanguage): string {
  const date = runTime(run);
  if (!date) {
    return '—';
  }
  return new Intl.DateTimeFormat(language === 'en' ? 'en-US' : 'zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

interface HistoryFilters {
  ticker: string | null;
  dateStart: string | null;
  dateEnd: string | null;
  direction: string | null;
  sharesMin: string | null;
  sharesMax: string | null;
}

const NO_FILTERS: HistoryFilters = {
  ticker: null,
  dateStart: null,
  dateEnd: null,
  direction: null,
  sharesMin: null,
  sharesMax: null,
};

function matchesFilters(run: TieredRunSummary, filters: HistoryFilters): boolean {
  if (filters.ticker && !run.stock_code.toUpperCase().includes(filters.ticker.toUpperCase())) {
    return false;
  }
  if (filters.direction && run.direction !== filters.direction) {
    return false;
  }
  const time = runTime(run);
  if (filters.dateStart && (!time || time < parseDay(filters.dateStart))) {
    return false;
  }
  if (filters.dateEnd && (!time || time >= parseDay(filters.dateEnd, 1))) {
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
// entered or picked — no search button — and show as removable pills.
// Below, one row per run (15 per page); clicking a row expands the full
// report inline. A freshly started run appears at the top as Running and
// turns into a normal row when it finishes.
export const AltRunHistory = ({
  runs,
  expandedTaskId,
  expandedResult,
  expandedError,
  onToggle,
}: AltRunHistoryProps) => {
  const { t, language } = useUiLanguage();
  const [filters, setFilters] = useState<HistoryFilters>(NO_FILTERS);
  const [page, setPage] = useState(1);

  const updateFilters = (patch: Partial<HistoryFilters>) => {
    setFilters((prev) => ({ ...prev, ...patch }));
    setPage(1);
  };

  const filtered = useMemo(
    () => runs.filter((run) => matchesFilters(run, filters)),
    [runs, filters],
  );
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount);
  const visible = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  const hasFilters = Object.values(filters).some((value) => value !== null);

  const pills: { key: string; tone: string; label: string; patch: Partial<HistoryFilters> }[] = [];
  if (filters.ticker) {
    pills.push({ key: 'ticker', tone: PILL_TONE.ticker, label: filters.ticker, patch: { ticker: null } });
  }
  if (filters.dateStart) {
    pills.push({
      key: 'dateStart',
      tone: PILL_TONE.date,
      label: t('tiered.pill.dateStart', { value: filters.dateStart }),
      patch: { dateStart: null },
    });
  }
  if (filters.dateEnd) {
    pills.push({
      key: 'dateEnd',
      tone: PILL_TONE.date,
      label: t('tiered.pill.dateEnd', { value: filters.dateEnd }),
      patch: { dateEnd: null },
    });
  }
  if (filters.direction) {
    pills.push({
      key: 'direction',
      tone: DIRECTION_TAG[filters.direction as keyof typeof DIRECTION_TAG] ?? PILL_TONE.neutral,
      label: t(`tiered.direction.${filters.direction}` as UiTextKey),
      patch: { direction: null },
    });
  }
  if (filters.sharesMin) {
    pills.push({
      key: 'sharesMin',
      tone: PILL_TONE.shares,
      label: t('tiered.pill.sharesMin', { value: filters.sharesMin }),
      patch: { sharesMin: null },
    });
  }
  if (filters.sharesMax) {
    pills.push({
      key: 'sharesMax',
      tone: PILL_TONE.shares,
      label: t('tiered.pill.sharesMax', { value: filters.sharesMax }),
      patch: { sharesMax: null },
    });
  }

  return (
    <div className="flex w-full flex-col gap-4">
      <h2 className="font-semibold text-gray-300">{t('tiered.history')}</h2>

      <div className="grid w-full grid-cols-2 gap-2 text-sm sm:grid-cols-4 sm:gap-3 md:gap-4">
        <AltTextField
          label={t('tiered.altForm.ticker')}
          placeholder={t('tiered.inputPlaceholder')}
          onCommit={(value) => updateFilters({ ticker: value })}
        />
        <AltPairField
          label={t('tiered.altFilter.date')}
          start={{
            placeholder: t('tiered.altFilter.dateStart'),
            validate: isValidDay,
            onCommit: (value) => updateFilters({ dateStart: value }),
          }}
          end={{
            placeholder: t('tiered.altFilter.dateEnd'),
            validate: isValidDay,
            onCommit: (value) => updateFilters({ dateEnd: value }),
          }}
        />
        <AltSelect
          label={t('tiered.altFilter.direction')}
          options={FILTER_DIRECTIONS.map((value) => ({
            value,
            label: t(`tiered.direction.${value}` as UiTextKey),
          }))}
          value={filters.direction ?? undefined}
          placeholder={t('tiered.altFilter.any')}
          onCommit={(value) => updateFilters({ direction: value })}
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
          <span className={`${TAG_BASE} ${PILL_TONE.neutral}`}>{t('tiered.altFilter.empty')}</span>
        ) : (
          pills.map((pill) => (
            <AltPill key={pill.key} tone={pill.tone} onRemove={() => updateFilters(pill.patch)}>
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
                  <span className="flex-1 text-xs text-gray-500">{formatTime(run, language)}</span>
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

      {pageCount > 1 ? (
        <div className="flex items-center justify-center gap-3 text-xs text-gray-500">
          <button
            type="button"
            aria-label={t('tiered.altHistory.prev')}
            disabled={safePage <= 1}
            onClick={() => setPage(safePage - 1)}
            className="cursor-pointer rounded p-1 hover:text-gray-300 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <span>{t('tiered.altHistory.page', { page: safePage, total: pageCount })}</span>
          <button
            type="button"
            aria-label={t('tiered.altHistory.next')}
            disabled={safePage >= pageCount}
            onClick={() => setPage(safePage + 1)}
            className="cursor-pointer rounded p-1 hover:text-gray-300 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      ) : null}
    </div>
  );
};
