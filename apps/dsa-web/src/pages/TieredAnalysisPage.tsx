import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Info, Layers, Search } from 'lucide-react';
import {
  tieredApi,
  type TieredDepth,
  type TieredDimension,
  type TieredResult,
  type TieredRunStatus,
  type TieredRunSummary,
  type TieredSizingRequest,
} from '../api/tiered';
import {
  AppPage,
  Badge,
  Button,
  Card,
  EmptyState,
  InlineAlert,
  Input,
  PageHeader,
} from '../components/common';
import { DebateCard } from '../components/tiered/DebateCard';
import { DepthSelector } from '../components/tiered/DepthSelector';
import { FinalVerdictCard } from '../components/tiered/FinalVerdictCard';
import { LevelTiles } from '../components/tiered/LevelTiles';
import { RiskCard } from '../components/tiered/RiskCard';
import { SizingCard } from '../components/tiered/SizingCard';
import {
  COVERAGE_BADGE,
  DIRECTION_BADGE,
  dedupeCitations,
  formatValue,
  metricAnchorId,
  sentimentCitations,
} from '../components/tiered/termHelpers';
import {
  HelpTerm,
  MetricTerm,
  NarrativeWithCitations,
} from '../components/tiered/terms';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import type { UiLanguage, UiTextKey } from '../i18n/uiText';
import { cn } from '../utils/cn';

const POLL_INTERVAL_MS = 5000;

const STATUS_BADGE: Record<TieredRunStatus, 'info' | 'success' | 'danger'> = {
  running: 'info',
  done: 'success',
  failed: 'danger',
};

const DIMENSION_LABEL_KEYS: Record<string, UiTextKey> = {
  technicals: 'tiered.dimension.technicals',
  fundamentals: 'tiered.dimension.fundamentals',
  macro_econ: 'tiered.dimension.macro_econ',
  sentiment: 'tiered.dimension.sentiment',
};

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

interface PayloadTableProps {
  dimension: string;
  payload: Record<string, unknown>;
}

// Metric rows carry anchor ids (metricAnchorId) so evidence references and
// formula inputs elsewhere on the page can scroll straight to their source.
const PayloadTable = ({ dimension, payload }: PayloadTableProps) => (
  <div className="space-y-3">
    {Object.entries(payload).map(([group, values]) => {
      if (values !== null && typeof values === 'object' && !Array.isArray(values)) {
        return (
          <div key={group}>
            <div className="label-uppercase mb-1">
              <MetricTerm term={group} />
            </div>
            <dl className="grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-2">
              {Object.entries(values as Record<string, unknown>).map(([key, value]) => (
                <div
                  key={key}
                  id={metricAnchorId(`${dimension}.${group}.${key}`)}
                  className="flex scroll-mt-24 items-baseline justify-between gap-3 border-b border-border/30 py-1"
                >
                  <dt className="text-xs text-secondary-text">
                    <MetricTerm term={key} />
                  </dt>
                  <dd className="font-mono text-xs text-foreground">{formatValue(value)}</dd>
                </div>
              ))}
            </dl>
          </div>
        );
      }
      return (
        <div
          key={group}
          id={metricAnchorId(`${dimension}.${group}`)}
          className="flex scroll-mt-24 items-baseline justify-between gap-3 border-b border-border/30 py-1"
        >
          <dt className="text-xs text-secondary-text">
            <MetricTerm term={group} />
          </dt>
          <dd className="font-mono text-xs text-foreground">{formatValue(values)}</dd>
        </div>
      );
    })}
  </div>
);

interface DimensionCardProps {
  dimension: TieredDimension;
}

const DimensionCard = ({ dimension }: DimensionCardProps) => {
  const { t } = useUiLanguage();
  const labelKey = DIMENSION_LABEL_KEYS[dimension.dimension];
  const uniqueCitations = dedupeCitations(dimension.citations);

  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-foreground">
          {labelKey ? t(labelKey) : dimension.dimension}
        </h3>
        <HelpTerm
          underline={false}
          helpKey="tiered.help.coverage"
          label={
            <Badge variant={COVERAGE_BADGE[dimension.coverage]}>
              {t(`tiered.coverage.${dimension.coverage}` as UiTextKey)}
            </Badge>
          }
        />
      </div>

      {dimension.narrative ? (
        <NarrativeWithCitations text={dimension.narrative} citations={uniqueCitations} />
      ) : null}

      {dimension.payload ? (
        <PayloadTable dimension={dimension.dimension} payload={dimension.payload} />
      ) : null}

      {uniqueCitations.length > 0 ? (
        <div className="mt-3">
          <div className="label-uppercase mb-1">{t('tiered.citations')}</div>
          <ul className="space-y-1">
            {uniqueCitations.map((citation, index) => (
              <li key={index} className="flex gap-2 text-xs">
                <span className="shrink-0 font-mono text-secondary-text">[{index + 1}]</span>
                {citation.url ? (
                  <a
                    href={citation.url}
                    target="_blank"
                    rel="noreferrer"
                    className="truncate text-cyan hover:underline"
                  >
                    {citation.title || citation.url}
                  </a>
                ) : (
                  <span className="truncate text-secondary-text">{citation.source_name}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {dimension.warnings.length > 0 ? (
        <div className="mt-3">
          <div className="label-uppercase mb-1">{t('tiered.dataNotes')}</div>
          <p className="mb-1 text-xs text-secondary-text">{t('tiered.dataNotesHint')}</p>
          <ul className="space-y-1">
            {dimension.warnings.map((warning, index) => (
              <li key={index} className="text-xs text-warning">
                {warning}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </Card>
  );
};

interface ResultViewProps {
  result: TieredResult;
}

const ResultView = ({ result }: ResultViewProps) => {
  const { t } = useUiLanguage();
  const citations = sentimentCitations(result.dimensions);
  // Old stored runs predate the final block — for them the run ended at
  // tier 1, so the final verdict IS the tier-1 verdict.
  const final = result.final ?? {
    tier: 1,
    direction: result.direction,
    coverage: result.coverage,
    confidence: null,
    levels: result.levels,
  };
  const usage = result.llm_usage ?? null;

  // Every depth renders the same skeleton, in the same order:
  // final verdict → order size → tier 1 → tier 2 → tier 3 → dimensions.
  return (
    <div className="space-y-4">
      <FinalVerdictCard
        symbol={result.symbol}
        final={final}
        tier1Direction={result.direction}
        tier2={result.tier2 ?? null}
        tier3={result.tier3 ?? null}
      />

      {result.sizing ? <SizingCard sizing={result.sizing} /> : null}

      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-3">
          <h3 className="text-sm font-semibold text-foreground">
            <HelpTerm label={t('tiered.tier1.title')} helpKey="tiered.help.tier1" />
          </h3>
          <HelpTerm
            underline={false}
            helpKey="tiered.help.direction"
            label={
              <Badge variant={DIRECTION_BADGE[result.direction]}>
                {t(`tiered.direction.${result.direction}` as UiTextKey)}
              </Badge>
            }
          />
          {result.score !== null ? (
            <span className="text-sm text-secondary-text">
              <HelpTerm label={t('tiered.score')} helpKey="tiered.help.score" />:{' '}
              <span className="font-mono text-foreground">{result.score}</span>
            </span>
          ) : null}
          <span className="flex items-center gap-1 text-sm text-secondary-text">
            <HelpTerm label={t('tiered.coverage')} helpKey="tiered.help.coverage" />:
            <Badge variant={COVERAGE_BADGE[result.coverage]}>
              {t(`tiered.coverage.${result.coverage}` as UiTextKey)}
            </Badge>
          </span>
        </div>

        {result.narrative ? (
          <div className="mt-3">
            <div className="label-uppercase mb-1">
              <HelpTerm label={t('tiered.narrative')} helpKey="tiered.help.narrative" />
            </div>
            <p className="text-sm leading-relaxed text-secondary-text">{result.narrative}</p>
          </div>
        ) : null}

        <div className="mt-4">
          <div className="label-uppercase mb-2">{t('tiered.levels')}</div>
          <LevelTiles
            levels={result.levels}
            levelsDetail={result.levels_detail}
            citations={citations}
          />
          <p className="mt-2 text-xs text-secondary-text">{t('tiered.levelsNote')}</p>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3 text-sm">
          {result.signal?.logged ? (
            <>
              <span className="text-success">
                {t('tiered.signalSaved', { id: result.signal.signal_id ?? '—' })}
              </span>
              <Link to="/decision-signals" className="text-cyan hover:underline">
                {t('tiered.viewSignals')}
              </Link>
            </>
          ) : result.signal ? (
            <span className="text-warning">
              {t('tiered.signalSkipped', { reason: result.signal.reason ?? '' })}
            </span>
          ) : null}
          {usage && usage.total.calls > 0 ? (
            <span className="text-xs text-secondary-text">
              <HelpTerm
                label={t('tiered.llmUsage', {
                  calls: usage.total.calls,
                  tokens: usage.total.prompt_tokens + usage.total.completion_tokens,
                })}
                helpKey="tiered.help.llmUsage"
              />
            </span>
          ) : null}
        </div>

        {result.warnings.length > 0 ? (
          <div className="mt-3">
            <div className="label-uppercase mb-1">{t('tiered.dataNotes')}</div>
            <p className="mb-1 text-xs text-secondary-text">{t('tiered.dataNotesHint')}</p>
            <ul className="space-y-1">
              {result.warnings.map((warning, index) => (
                <li key={index} className="text-xs text-warning">
                  {warning}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </Card>

      {result.tier2 ? <DebateCard section={result.tier2} citations={citations} /> : null}
      {result.tier3 ? <RiskCard section={result.tier3} citations={citations} /> : null}

      <div>
        <div className="label-uppercase mb-2">{t('tiered.dimensions')}</div>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {result.dimensions.map((dimension) => (
            <DimensionCard key={dimension.dimension} dimension={dimension} />
          ))}
        </div>
      </div>
    </div>
  );
};

const TieredAnalysisPage = () => {
  const { t, language } = useUiLanguage();
  const [stockCode, setStockCode] = useState('');
  const [depth, setDepth] = useState<TieredDepth>(1);
  const [capitalInput, setCapitalInput] = useState(() =>
    readStoredNumber(SIZING_CAPITAL_STORAGE_KEY),
  );
  const [riskPctInput, setRiskPctInput] = useState(() =>
    readStoredNumber(SIZING_RISK_PCT_STORAGE_KEY),
  );
  const [runs, setRuns] = useState<TieredRunSummary[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [selectedResult, setSelectedResult] = useState<TieredResult | null>(null);
  const [selectedError, setSelectedError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const loadedDetailRef = useRef<string | null>(null);

  const anyRunning = useMemo(
    () => runs.some((run) => run.status === 'running'),
    [runs],
  );

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
    <AppPage>
      <PageHeader
        eyebrow="v2"
        title={t('tiered.title')}
        description={t('tiered.subtitle')}
      />

      <Card className="mt-4 p-4">
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            void handleRun();
          }}
        >
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <div className="flex-1">
              <Input
                value={stockCode}
                onChange={(event) => setStockCode(event.target.value)}
                placeholder={t('tiered.inputPlaceholder')}
                aria-label={t('tiered.inputPlaceholder')}
              />
            </div>
            <Button
              type="submit"
              variant="primary"
              isLoading={submitting}
              disabled={!stockCode.trim() || submitting}
            >
              <Search className="mr-1 h-4 w-4" />
              {t('tiered.run')}
            </Button>
          </div>

          <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
            <DepthSelector value={depth} onChange={setDepth} disabled={submitting} />
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-secondary-text">
                <HelpTerm label={t('tiered.sizingForm.title')} helpKey="tiered.help.sizingForm" />
              </span>
              <Input
                value={capitalInput}
                onChange={(event) => setCapitalInput(event.target.value)}
                placeholder={t('tiered.sizingForm.capital')}
                aria-label={t('tiered.sizingForm.capital')}
                inputMode="decimal"
                className="w-40"
              />
              <Input
                value={riskPctInput}
                onChange={(event) => setRiskPctInput(event.target.value)}
                placeholder={t('tiered.sizingForm.riskPct')}
                aria-label={t('tiered.sizingForm.riskPct')}
                inputMode="decimal"
                className="w-40"
              />
            </div>
          </div>
        </form>
        {anyRunning ? (
          <p className="mt-3 text-sm text-secondary-text">{t('tiered.running')}</p>
        ) : null}
      </Card>

      {submitError ? (
        <div className="mt-4">
          <InlineAlert variant="danger" title={t('tiered.error.title')} message={submitError} />
        </div>
      ) : null}

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-[280px_1fr]">
        <Card className="h-fit p-4">
          <h2 className="text-sm font-semibold text-foreground">{t('tiered.history')}</h2>
          <p className="mt-1 text-xs text-secondary-text">{t('tiered.historyHint')}</p>
          {runs.length === 0 ? (
            <p className="mt-4 text-sm text-secondary-text">{t('tiered.empty')}</p>
          ) : (
            <ul className="mt-3 space-y-1">
              {runs.map((run) => (
                <li key={run.task_id}>
                  <button
                    type="button"
                    onClick={() => handleSelect(run.task_id)}
                    className={cn(
                      'flex w-full items-center justify-between gap-2 rounded-lg px-2 py-2 text-left transition-colors',
                      run.task_id === selectedTaskId
                        ? 'bg-elevated text-foreground'
                        : 'text-secondary-text hover:bg-elevated/60 hover:text-foreground',
                    )}
                  >
                    <span className="flex items-baseline gap-2">
                      <span className="font-mono text-sm">{run.stock_code}</span>
                      <span className="text-xs">{formatTime(run.created_at, language)}</span>
                    </span>
                    <Badge variant={STATUS_BADGE[run.status]}>
                      {t(`tiered.status.${run.status}` as UiTextKey)}
                    </Badge>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <div>
          {selectedError ? (
            <InlineAlert variant="danger" title={t('tiered.error.title')} message={selectedError} />
          ) : null}
          {selectedResult ? (
            <ResultView result={selectedResult} />
          ) : !selectedError ? (
            <EmptyState
              icon={<Layers className="h-8 w-8" />}
              title={
                selectedRun?.status === 'running' ? t('tiered.running') : t('tiered.empty')
              }
            />
          ) : null}
        </div>
      </div>

      <Card className="mt-4 p-4">
        <div className="flex items-start gap-2">
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-cyan" />
          <p className="text-xs leading-relaxed text-secondary-text">{t('tiered.signalsExplainer')}</p>
        </div>
      </Card>
    </AppPage>
  );
};

export default TieredAnalysisPage;
