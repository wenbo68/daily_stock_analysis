import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Search, X } from 'lucide-react';
import {
  tieredApi,
  type TieredDepth,
  type TieredResult,
  type TieredSizingRequest,
} from '../api/tiered';
import { AltResult } from '../components/tiered-alt/AltResult';
import { AltSelect } from '../components/tiered-alt/AltUi';
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
        // There is no server-side default capital/risk — but if the boxes
        // are empty, offer what this run actually used so the numbers on
        // screen and in the form agree.
        const inputs = run.result?.sizing?.inputs;
        if (inputs?.capital != null) {
          setCapitalInput((prev) => prev || String(inputs.capital));
        }
        if (inputs?.risk_fraction != null) {
          const pct = Number((inputs.risk_fraction * 100).toPrecision(12));
          setRiskPctInput((prev) => prev || String(pct));
        }
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

  const depthOptions = DEPTHS.map((value) => ({
    value: String(value),
    label: t(`tiered.depth.${value}` as UiTextKey),
  }));

  const historyOptions = runs.map((run) => ({
    value: run.task_id,
    label: `${run.stock_code} · ${formatTime(run.created_at, language)}`,
    node: (
      <span className="flex items-center gap-2">
        <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', STATUS_DOT[run.status])} />
        <span>{run.stock_code}</span>
        <span className="ml-auto font-normal text-gray-500">
          {formatTime(run.created_at, language)}
        </span>
      </span>
    ),
  }));

  const capitalOptions = ['10000', '50000', '100000', '200000', '500000', '1000000'].map(
    (value) => ({ value, label: value }),
  );
  const riskOptions = ['0.5', '1', '2'].map((value) => ({ value, label: `${value} %` }));

  return (
    <main className="mx-auto min-h-full w-full max-w-7xl px-4 pb-8 pt-4 md:px-6 lg:px-8">
      <div className="rounded-lg bg-gray-900 p-4 text-gray-400 sm:p-6 lg:p-8">
        <div className="flex w-full flex-col gap-6">
          {/* showplayer.net top bar: a grid of labeled controls; the run
              only starts on the indigo search button, never on change. */}
          <form
            className="grid w-full grid-cols-2 gap-2 text-sm sm:grid-cols-3 sm:gap-3 md:gap-4 lg:grid-cols-5"
            onSubmit={(event) => {
              event.preventDefault();
              void handleRun();
            }}
          >
            <div className="col-span-2 flex w-full flex-col gap-2 sm:col-span-1">
              <span className="font-semibold text-gray-300">{t('tiered.altForm.ticker')}</span>
              <div className="flex w-full items-center gap-2">
                <div className="flex w-full items-center rounded bg-gray-800">
                  <input
                    value={stockCode}
                    onChange={(event) => setStockCode(event.target.value)}
                    placeholder={t('tiered.inputPlaceholder')}
                    aria-label={t('tiered.altForm.ticker')}
                    className="w-full bg-transparent pl-3 text-gray-300 placeholder-gray-500 outline-none"
                  />
                  {stockCode ? (
                    <button
                      type="button"
                      aria-label={t('tiered.altForm.clear')}
                      onClick={() => setStockCode('')}
                      className="cursor-pointer p-2 text-gray-500 hover:text-gray-300"
                    >
                      <X className="h-5 w-5" />
                    </button>
                  ) : null}
                </div>
                <button
                  type="submit"
                  aria-label={t('tiered.run')}
                  disabled={!stockCode.trim() || submitting}
                  className="cursor-pointer rounded bg-indigo-600 p-2 text-gray-200 hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Search className="h-5 w-5" />
                </button>
              </div>
            </div>

            <AltSelect
              mode="select"
              label={
                <HelpTerm
                  label={t('tiered.depth.label')}
                  helpKey="tiered.help.depth"
                  underline={false}
                />
              }
              options={depthOptions}
              value={String(depth)}
              onSelect={(value) => setDepth(Number(value) as TieredDepth)}
            />
            <AltSelect
              mode="text"
              label={
                <HelpTerm
                  label={t('tiered.altForm.capital')}
                  helpKey="tiered.help.sizingForm"
                  underline={false}
                />
              }
              options={capitalOptions}
              value={capitalInput}
              onText={setCapitalInput}
              placeholder={t('tiered.sizingForm.capital')}
              inputMode="decimal"
            />
            <AltSelect
              mode="text"
              label={
                <HelpTerm
                  label={t('tiered.altForm.risk')}
                  helpKey="tiered.help.sizingForm"
                  underline={false}
                />
              }
              options={riskOptions}
              value={riskPctInput}
              onText={setRiskPctInput}
              placeholder={t('tiered.sizingForm.riskPct')}
              inputMode="decimal"
            />
            <AltSelect
              mode="select"
              label={t('tiered.history')}
              options={historyOptions}
              value={selectedTaskId ?? ''}
              onSelect={handleSelect}
              placeholder={t('tiered.empty')}
            />
          </form>

          {anyRunning ? <p className="text-sm text-gray-500">{t('tiered.running')}</p> : null}
          {submitError ? <p className="text-sm text-red-300">{submitError}</p> : null}
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
