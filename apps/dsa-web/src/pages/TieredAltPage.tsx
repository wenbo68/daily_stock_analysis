import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Search } from 'lucide-react';
import {
  tieredApi,
  type TieredDepth,
  type TieredResult,
  type TieredSizingRequest,
} from '../api/tiered';
import { AltResult } from '../components/tiered-alt/AltResult';
import { STATUS_DOT } from '../components/tiered-alt/altStyles';
import { HelpTerm } from '../components/tiered/terms';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import type { UiLanguage, UiTextKey } from '../i18n/uiText';
import { cn } from '../utils/cn';

const POLL_INTERVAL_MS = 5000;
const DEPTHS: TieredDepth[] = [1, 2, 3];

// Shared with the main tiered page so the values carry across both skins.
const SIZING_CAPITAL_STORAGE_KEY = 'tiered.sizing.capital';
const SIZING_RISK_PCT_STORAGE_KEY = 'tiered.sizing.riskPct';

function formatTime(value: string | null, language: UiLanguage): string {
  if (!value) {
    return '—';
  }
  const date = new Date(value.endsWith('Z') ? value : `${value}Z`);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(language === 'en' ? 'en-US' : 'zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function readStoredNumber(key: string): string {
  try {
    return window.localStorage.getItem(key) ?? '';
  } catch {
    return '';
  }
}

function storeNumber(key: string, value: string): void {
  try {
    if (value) {
      window.localStorage.setItem(key, value);
    } else {
      window.localStorage.removeItem(key);
    }
  } catch {
    // storage unavailable (private mode) — the run still works
  }
}

const inputClass =
  'w-full rounded bg-gray-800 px-3 py-2 text-sm text-gray-300 placeholder-gray-500 outline-none focus:ring-1 focus:ring-blue-500';

// Alternate skin for tiered analysis, styled after showplayer.net: flat
// gray-900 canvas, gray-800 surfaces, ring badges, blue accents, whitespace
// instead of borders. Same API, same data, same i18n keys as /tiered.
const TieredAltPage = () => {
  const { t, language } = useUiLanguage();
  const [stockCode, setStockCode] = useState('');
  const [depth, setDepth] = useState<TieredDepth>(1);
  const [capitalInput, setCapitalInput] = useState(() =>
    readStoredNumber(SIZING_CAPITAL_STORAGE_KEY),
  );
  const [riskPctInput, setRiskPctInput] = useState(() =>
    readStoredNumber(SIZING_RISK_PCT_STORAGE_KEY),
  );
  const [runs, setRuns] = useState<Awaited<ReturnType<typeof tieredApi.listRuns>>>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [selectedResult, setSelectedResult] = useState<TieredResult | null>(null);
  const [selectedError, setSelectedError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const loadedDetailRef = useRef<string | null>(null);

  const anyRunning = useMemo(() => runs.some((run) => run.status === 'running'), [runs]);

  const refreshRuns = useCallback(async () => {
    try {
      const items = await tieredApi.listRuns();
      setRuns(items);
    } catch {
      // transient — next poll retries
    }
  }, []);

  useEffect(() => {
    void refreshRuns();
  }, [refreshRuns]);

  useEffect(() => {
    if (!anyRunning) {
      return;
    }
    const timer = window.setInterval(() => {
      void refreshRuns();
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [anyRunning, refreshRuns]);

  const selectedRun = useMemo(
    () => runs.find((run) => run.task_id === selectedTaskId) ?? null,
    [runs, selectedTaskId],
  );

  useEffect(() => {
    if (!selectedTaskId || !selectedRun) {
      return;
    }
    if (selectedRun.status === 'failed') {
      setSelectedResult(null);
      setSelectedError(selectedRun.error || t('tiered.error.title'));
      return;
    }
    if (selectedRun.status !== 'done' || loadedDetailRef.current === selectedTaskId) {
      return;
    }
    loadedDetailRef.current = selectedTaskId;
    void (async () => {
      try {
        const run = await tieredApi.getRun(selectedTaskId);
        setSelectedResult(run.result);
        setSelectedError(run.result ? null : run.error);
      } catch (error) {
        loadedDetailRef.current = null;
        setSelectedError(error instanceof Error ? error.message : String(error));
      }
    })();
  }, [selectedTaskId, selectedRun, t]);

  const handleSelect = useCallback((taskId: string) => {
    setSelectedTaskId(taskId);
    setSelectedResult(null);
    setSelectedError(null);
    loadedDetailRef.current = null;
  }, []);

  const sizingRequest = useMemo((): TieredSizingRequest | undefined => {
    const capital = Number(capitalInput);
    const riskPct = Number(riskPctInput);
    const request: TieredSizingRequest = {};
    if (capitalInput.trim() && Number.isFinite(capital) && capital > 0) {
      request.capital = capital;
    }
    if (riskPctInput.trim() && Number.isFinite(riskPct) && riskPct > 0 && riskPct < 100) {
      request.risk_fraction = riskPct / 100;
    }
    return Object.keys(request).length > 0 ? request : undefined;
  }, [capitalInput, riskPctInput]);

  const handleRun = useCallback(async () => {
    const code = stockCode.trim();
    if (!code || submitting) {
      return;
    }
    setSubmitError(null);
    setSubmitting(true);
    try {
      const started = await tieredApi.start(code, depth, sizingRequest);
      storeNumber(SIZING_CAPITAL_STORAGE_KEY, capitalInput.trim());
      storeNumber(SIZING_RISK_PCT_STORAGE_KEY, riskPctInput.trim());
      setStockCode('');
      await refreshRuns();
      handleSelect(started.task_id);
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : String(error));
    } finally {
      setSubmitting(false);
    }
  }, [
    stockCode,
    submitting,
    depth,
    sizingRequest,
    capitalInput,
    riskPctInput,
    refreshRuns,
    handleSelect,
  ]);

  return (
    <main className="mx-auto min-h-full w-full max-w-7xl px-4 pb-8 pt-4 md:px-6 lg:px-8">
      <div className="rounded-lg bg-gray-900 p-4 text-gray-400 sm:p-6 lg:p-8">
        <div className="mx-auto flex w-full max-w-4xl flex-col gap-8">
          <header>
            <h1 className="text-2xl font-bold text-gray-300">{t('tiered.alt.title')}</h1>
            <p className="mt-1 text-sm text-gray-500">{t('tiered.alt.subtitle')}</p>
          </header>

          <form
            className="flex flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              void handleRun();
            }}
          >
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
              <div className="flex flex-1 items-center rounded bg-gray-800">
                <span className="p-2 text-gray-500">
                  <Search className="h-4 w-4" />
                </span>
                <input
                  value={stockCode}
                  onChange={(event) => setStockCode(event.target.value)}
                  placeholder={t('tiered.inputPlaceholder')}
                  aria-label={t('tiered.inputPlaceholder')}
                  className="w-full bg-transparent py-2 pr-3 text-sm text-gray-300 placeholder-gray-500 outline-none"
                />
              </div>
              <button
                type="submit"
                disabled={!stockCode.trim() || submitting}
                className="cursor-pointer rounded bg-blue-600 px-5 py-2 text-sm font-semibold text-gray-200 hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {t('tiered.run')}
              </button>
            </div>

            <div className="flex flex-wrap items-center gap-x-8 gap-y-3">
              <div className="flex items-center gap-2" role="radiogroup" aria-label={t('tiered.depth.label')}>
                <span className="text-xs font-semibold text-gray-300">
                  <HelpTerm label={t('tiered.depth.label')} helpKey="tiered.help.depth" />
                </span>
                {DEPTHS.map((value) => (
                  <button
                    key={value}
                    type="button"
                    role="radio"
                    aria-checked={depth === value}
                    disabled={submitting}
                    onClick={() => setDepth(value)}
                    className={cn(
                      'cursor-pointer rounded px-3 py-1.5 text-xs font-semibold',
                      depth === value
                        ? 'bg-blue-600 text-gray-200'
                        : 'bg-gray-800 text-gray-400 hover:text-gray-300',
                    )}
                  >
                    {t(`tiered.depth.${value}` as UiTextKey)}
                  </button>
                ))}
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-semibold text-gray-300">
                  <HelpTerm label={t('tiered.sizingForm.title')} helpKey="tiered.help.sizingForm" />
                </span>
                <input
                  value={capitalInput}
                  onChange={(event) => setCapitalInput(event.target.value)}
                  placeholder={t('tiered.sizingForm.capital')}
                  aria-label={t('tiered.sizingForm.capital')}
                  inputMode="decimal"
                  className={cn(inputClass, 'w-40')}
                />
                <input
                  value={riskPctInput}
                  onChange={(event) => setRiskPctInput(event.target.value)}
                  placeholder={t('tiered.sizingForm.riskPct')}
                  aria-label={t('tiered.sizingForm.riskPct')}
                  inputMode="decimal"
                  className={cn(inputClass, 'w-40')}
                />
              </div>
            </div>

            {anyRunning ? <p className="text-sm text-gray-500">{t('tiered.running')}</p> : null}
            {submitError ? <p className="text-sm text-red-300">{submitError}</p> : null}
          </form>

          {runs.length > 0 ? (
            <div>
              <div className="mb-2 text-xs font-semibold text-gray-300">{t('tiered.history')}</div>
              <div className="flex gap-2 overflow-x-auto pb-1">
                {runs.map((run) => (
                  <button
                    key={run.task_id}
                    type="button"
                    onClick={() => handleSelect(run.task_id)}
                    className={cn(
                      'flex shrink-0 cursor-pointer items-center gap-2 rounded bg-gray-800 px-3 py-1.5 text-xs',
                      run.task_id === selectedTaskId
                        ? 'text-gray-200 ring-1 ring-inset ring-blue-500'
                        : 'text-gray-400 hover:text-gray-300',
                    )}
                  >
                    <span className={cn('h-1.5 w-1.5 rounded-full', STATUS_DOT[run.status])} />
                    <span className="font-semibold">{run.stock_code}</span>
                    <span className="text-gray-500">{formatTime(run.created_at, language)}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {selectedError ? <p className="text-sm text-red-300">{selectedError}</p> : null}
          {selectedResult ? (
            <AltResult result={selectedResult} />
          ) : !selectedError ? (
            <p className="py-10 text-center text-sm text-gray-600">
              {selectedRun?.status === 'running' ? t('tiered.running') : t('tiered.empty')}
            </p>
          ) : null}
        </div>
      </div>
    </main>
  );
};

export default TieredAltPage;
