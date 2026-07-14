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
const DEFAULT_TIER: TieredDepth = 1;

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

const riskFractionToPct = (fraction: number): string =>
  String(Number((fraction * 100).toPrecision(12)));

// Alternate skin for tiered analysis, styled after showplayer.net. Two
// section cards with their titles sitting above: the new-run form
// (write-only fields + pills + Start) and the run history (filters +
// paged rows that expand into the full report).
const TieredAltPage = () => {
  const { t } = useUiLanguage();
  const [ticker, setTicker] = useState<string | null>(null);
  const [tier, setTier] = useState<TieredDepth | null>(DEFAULT_TIER);
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
  // Tier of runs this page started, so their rows show it while still
  // running (the backend only knows a run's tier once the report exists).
  const [pendingTiers, setPendingTiers] = useState<Record<string, TieredDepth>>({});
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

  // Server-side sizing defaults (.env) fill the capital/risk pills on
  // entry when nothing was picked yet, so what a run would actually use
  // is visible up front.
  useEffect(() => {
    void (async () => {
      try {
        const defaults = await tieredApi.sizingDefaults();
        const defaultCapital = defaults.capital;
        if (defaultCapital != null) {
          setCapital((prev) => prev ?? String(defaultCapital));
        }
        const defaultRisk = defaults.risk_fraction;
        if (defaultRisk != null) {
          setRiskPct((prev) => prev ?? riskFractionToPct(defaultRisk));
        }
      } catch {
        // no defaults reachable — the fields just start empty
      }
    })();
  }, []);

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

  // Rows the backend can't tier yet (still running) get the tier this
  // page submitted them with.
  const annotatedRuns = useMemo(
    () =>
      runs.map((run) =>
        run.tier == null && pendingTiers[run.task_id]
          ? { ...run, tier: pendingTiers[run.task_id] }
          : run,
      ),
    [runs, pendingTiers],
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
          // If capital/risk are still unset (no .env default either),
          // offer what this run actually used so the numbers on screen
          // and in the form agree.
          const inputs = result.sizing?.inputs;
          if (inputs?.capital != null) {
            const capitalUsed = String(inputs.capital);
            setCapital((prev) => prev ?? capitalUsed);
          }
          if (inputs?.risk_fraction != null) {
            const pctUsed = riskFractionToPct(inputs.risk_fraction);
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
      const tierUsed = tier ?? DEFAULT_TIER;
      const started = await tieredApi.start(
        ticker,
        tierUsed,
        Object.keys(sizing).length > 0 ? sizing : undefined,
      );
      storeNumber(SIZING_CAPITAL_STORAGE_KEY, capital);
      storeNumber(SIZING_RISK_PCT_STORAGE_KEY, riskPct);
      setTicker(null);
      setPendingTiers((prev) => ({ ...prev, [started.task_id]: tierUsed }));
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
  }, [ticker, submitting, tier, capital, riskPct, refreshRuns]);

  return (
    <main className="mx-auto flex min-h-full w-full max-w-7xl flex-col gap-6 px-4 pb-8 pt-4 md:px-6 lg:px-8">
      <section className="flex flex-col gap-2">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-500">
          {t('tiered.altForm.title')}
        </h2>
        <div className="rounded-lg bg-gray-900 p-4 text-gray-400 sm:p-6">
          <AltRunForm
            ticker={ticker}
            tier={tier}
            capital={capital}
            riskPct={riskPct}
            submitting={submitting}
            error={submitError}
            onTicker={setTicker}
            onTier={setTier}
            onCapital={setCapital}
            onRiskPct={setRiskPct}
            onStart={() => void handleStart()}
          />
        </div>
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-500">
          {t('tiered.history')}
        </h2>
        <div className="rounded-lg bg-gray-900 p-4 text-gray-400 sm:p-6">
          <AltRunHistory
            runs={annotatedRuns}
            expandedTaskId={expandedTaskId}
            expandedResult={expandedTaskId ? (details[expandedTaskId] ?? null) : null}
            expandedError={detailError}
            onToggle={handleToggle}
          />
        </div>
      </section>
    </main>
  );
};

export default TieredAltPage;
