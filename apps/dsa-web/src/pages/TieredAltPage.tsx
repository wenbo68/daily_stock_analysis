import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  tieredApi,
  type TieredDepth,
  type TieredResult,
  type TieredRunSummary,
  type TieredSizingRequest,
} from '../api/tiered';
import { AltRunForm } from '../components/tiered-alt/AltRunForm';
import { AltRunHistory } from '../components/tiered-alt/AltRunHistory';
import { useUiLanguage } from '../contexts/UiLanguageContext';

const POLL_INTERVAL_MS = 5000;

// Shared with the main tiered page so the values carry across both skins.
const SIZING_CAPITAL_STORAGE_KEY = 'tiered.sizing.capital';
const SIZING_RISK_PCT_STORAGE_KEY = 'tiered.sizing.riskPct';

function readStoredNumber(key: string): string | null {
  try {
    return window.localStorage.getItem(key) || null;
  } catch {
    return null;
  }
}

function storeNumber(key: string, value: string | null): void {
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

// Alternate skin for tiered analysis, styled after showplayer.net. Two
// sections: the new-run form (write-only fields + pills + Start) and the
// run history (filters + paged rows that expand into the full report).
const TieredAltPage = () => {
  const { t } = useUiLanguage();
  const [ticker, setTicker] = useState<string | null>(null);
  const [depth, setDepth] = useState<TieredDepth | null>(null);
  const [capital, setCapital] = useState<string | null>(() =>
    readStoredNumber(SIZING_CAPITAL_STORAGE_KEY),
  );
  const [riskPct, setRiskPct] = useState<string | null>(() =>
    readStoredNumber(SIZING_RISK_PCT_STORAGE_KEY),
  );
  const [runs, setRuns] = useState<TieredRunSummary[]>([]);
  const [expandedTaskId, setExpandedTaskId] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<string, TieredResult>>({});
  const [detailError, setDetailError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const loadingDetailRef = useRef<string | null>(null);

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

  const expandedRun = useMemo(
    () => runs.find((run) => run.task_id === expandedTaskId) ?? null,
    [runs, expandedTaskId],
  );

  // Fetch the full report the first time a finished run is expanded (a run
  // started as Running loads here too, the moment polling flips it to done).
  useEffect(() => {
    const taskId = expandedTaskId;
    if (!taskId || expandedRun?.status !== 'done' || details[taskId]) {
      return;
    }
    if (loadingDetailRef.current === taskId) {
      return;
    }
    loadingDetailRef.current = taskId;
    void (async () => {
      try {
        const run = await tieredApi.getRun(taskId);
        const result = run.result;
        if (result) {
          setDetails((prev) => ({ ...prev, [taskId]: result }));
          setDetailError(null);
          // There is no server-side default capital/risk — but if none is
          // picked yet, offer what this run actually used so the numbers on
          // screen and in the form agree.
          const inputs = result.sizing?.inputs;
          if (inputs?.capital != null) {
            const capitalUsed = String(inputs.capital);
            setCapital((prev) => prev ?? capitalUsed);
          }
          if (inputs?.risk_fraction != null) {
            const pctUsed = String(Number((inputs.risk_fraction * 100).toPrecision(12)));
            setRiskPct((prev) => prev ?? pctUsed);
          }
        } else {
          setDetailError(run.error || t('tiered.error.title'));
        }
      } catch (error) {
        setDetailError(error instanceof Error ? error.message : String(error));
      } finally {
        loadingDetailRef.current = null;
      }
    })();
  }, [expandedTaskId, expandedRun?.status, details, t]);

  const handleToggle = useCallback((taskId: string) => {
    setDetailError(null);
    setExpandedTaskId((prev) => (prev === taskId ? null : taskId));
  }, []);

  const handleStart = useCallback(async () => {
    if (!ticker || submitting) {
      return;
    }
    setSubmitError(null);
    setSubmitting(true);
    try {
      const sizing: TieredSizingRequest = {};
      const capitalValue = Number(capital);
      if (capital && Number.isFinite(capitalValue) && capitalValue > 0) {
        sizing.capital = capitalValue;
      }
      const pctValue = Number(riskPct);
      if (riskPct && Number.isFinite(pctValue) && pctValue > 0 && pctValue < 100) {
        sizing.risk_fraction = pctValue / 100;
      }
      const started = await tieredApi.start(
        ticker,
        depth ?? 1,
        Object.keys(sizing).length > 0 ? sizing : undefined,
      );
      storeNumber(SIZING_CAPITAL_STORAGE_KEY, capital);
      storeNumber(SIZING_RISK_PCT_STORAGE_KEY, riskPct);
      setTicker(null);
      // The new run is already in the backend list as Running; show it at
      // the top of the history, expanded, until polling flips it to done.
      await refreshRuns();
      setDetailError(null);
      setExpandedTaskId(started.task_id);
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : String(error));
    } finally {
      setSubmitting(false);
    }
  }, [ticker, submitting, depth, capital, riskPct, refreshRuns]);

  return (
    <main className="mx-auto flex min-h-full w-full max-w-7xl flex-col gap-6 px-4 pb-8 pt-4 md:px-6 lg:px-8">
      <section className="rounded-lg bg-gray-900 p-4 text-gray-400 sm:p-6">
        <AltRunForm
          ticker={ticker}
          depth={depth}
          capital={capital}
          riskPct={riskPct}
          submitting={submitting}
          error={submitError}
          onTicker={setTicker}
          onDepth={setDepth}
          onCapital={setCapital}
          onRiskPct={setRiskPct}
          onStart={() => void handleStart()}
        />
      </section>

      <section className="rounded-lg bg-gray-900 p-4 text-gray-400 sm:p-6">
        <AltRunHistory
          runs={runs}
          expandedTaskId={expandedTaskId}
          expandedResult={expandedTaskId ? (details[expandedTaskId] ?? null) : null}
          expandedError={detailError}
          onToggle={handleToggle}
        />
      </section>
    </main>
  );
};

export default TieredAltPage;
