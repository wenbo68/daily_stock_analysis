import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Info, Layers, Search } from 'lucide-react';
import {
  tieredApi,
  type TieredDimension,
  type TieredResult,
  type TieredRunStatus,
  type TieredRunSummary,
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
import { useUiLanguage } from '../contexts/UiLanguageContext';
import { metricLabel } from '../i18n/metricLabels';
import type { UiLanguage, UiTextKey } from '../i18n/uiText';
import { cn } from '../utils/cn';

const POLL_INTERVAL_MS = 5000;

const DIRECTION_BADGE: Record<TieredResult['direction'], 'success' | 'warning' | 'danger' | 'default'> = {
  buy: 'success',
  hold: 'warning',
  sell: 'danger',
  unknown: 'default',
};

const COVERAGE_BADGE: Record<TieredDimension['coverage'], 'success' | 'warning' | 'danger'> = {
  full: 'success',
  partial: 'warning',
  unavailable: 'danger',
};

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

function formatValue(value: unknown): string {
  if (value === null || value === undefined) {
    return '—';
  }
  if (typeof value === 'number') {
    const abs = Math.abs(value);
    if (abs >= 1e12) {
      return `${(value / 1e12).toFixed(2)} trillion`;
    }
    if (abs >= 1e9) {
      return `${(value / 1e9).toFixed(2)} billion`;
    }
    if (abs >= 1e6) {
      return `${(value / 1e6).toFixed(2)} million`;
    }
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
  }
  return String(value);
}

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

interface PayloadTableProps {
  payload: Record<string, unknown>;
}

const PayloadTable = ({ payload }: PayloadTableProps) => {
  const { language } = useUiLanguage();

  return (
    <div className="space-y-3">
      {Object.entries(payload).map(([group, values]) => {
        if (values !== null && typeof values === 'object' && !Array.isArray(values)) {
          return (
            <div key={group}>
              <div className="label-uppercase mb-1">{metricLabel(group, language)}</div>
              <dl className="grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-2">
                {Object.entries(values as Record<string, unknown>).map(([key, value]) => (
                  <div key={key} className="flex items-baseline justify-between gap-3 border-b border-border/30 py-1">
                    <dt className="text-xs text-secondary-text">{metricLabel(key, language)}</dt>
                    <dd className="font-mono text-xs text-foreground">{formatValue(value)}</dd>
                  </div>
                ))}
              </dl>
            </div>
          );
        }
        return (
          <div key={group} className="flex items-baseline justify-between gap-3 border-b border-border/30 py-1">
            <dt className="text-xs text-secondary-text">{metricLabel(group, language)}</dt>
            <dd className="font-mono text-xs text-foreground">{formatValue(values)}</dd>
          </div>
        );
      })}
    </div>
  );
};

interface DimensionCardProps {
  dimension: TieredDimension;
}

const DimensionCard = ({ dimension }: DimensionCardProps) => {
  const { t } = useUiLanguage();
  const labelKey = DIMENSION_LABEL_KEYS[dimension.dimension];
  // Old stored runs may hold one citation per quote (several per source);
  // collapse to one entry per source so numbering matches inline [n] marks.
  const uniqueCitations = dimension.citations.filter(
    (citation, index, all) =>
      all.findIndex(
        (other) => (other.url || other.source_name) === (citation.url || citation.source_name),
      ) === index,
  );

  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-foreground">
          {labelKey ? t(labelKey) : dimension.dimension}
        </h3>
        <Badge variant={COVERAGE_BADGE[dimension.coverage]}>
          {t(`tiered.coverage.${dimension.coverage}` as UiTextKey)}
        </Badge>
      </div>

      {dimension.narrative ? (
        <p className="mb-3 text-sm leading-relaxed text-secondary-text">{dimension.narrative}</p>
      ) : null}

      {dimension.payload ? <PayloadTable payload={dimension.payload} /> : null}

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

interface LevelTileProps {
  label: string;
  value: number | null;
}

const LevelTile = ({ label, value }: LevelTileProps) => (
  <div className="rounded-xl border border-border/40 bg-elevated/60 px-3 py-2">
    <div className="text-xs text-secondary-text">{label}</div>
    <div className="mt-1 font-mono text-base text-foreground">{value ?? '—'}</div>
  </div>
);

interface ResultViewProps {
  result: TieredResult;
}

const ResultView = ({ result }: ResultViewProps) => {
  const { t } = useUiLanguage();

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-lg font-semibold text-foreground">{result.symbol}</h2>
          <Badge variant={DIRECTION_BADGE[result.direction]} size="md" glow>
            {t(`tiered.direction.${result.direction}` as UiTextKey)}
          </Badge>
          {result.score !== null ? (
            <span className="text-sm text-secondary-text">
              {t('tiered.score')}: <span className="font-mono text-foreground">{result.score}</span>
            </span>
          ) : null}
          <span className="flex items-center gap-1 text-sm text-secondary-text">
            {t('tiered.coverage')}:
            <Badge variant={COVERAGE_BADGE[result.coverage]}>
              {t(`tiered.coverage.${result.coverage}` as UiTextKey)}
            </Badge>
          </span>
        </div>

        {result.narrative ? (
          <div className="mt-3">
            <div className="label-uppercase mb-1">{t('tiered.narrative')}</div>
            <p className="text-sm leading-relaxed text-secondary-text">{result.narrative}</p>
          </div>
        ) : null}

        <div className="mt-4">
          <div className="label-uppercase mb-2">{t('tiered.levels')}</div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <LevelTile label={t('tiered.levels.entry')} value={result.levels.entry} />
            <LevelTile label={t('tiered.levels.secondaryEntry')} value={result.levels.secondary_entry} />
            <LevelTile label={t('tiered.levels.stopLoss')} value={result.levels.stop_loss} />
            <LevelTile label={t('tiered.levels.takeProfit')} value={result.levels.take_profit} />
          </div>
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

  const handleRun = useCallback(async () => {
    const code = stockCode.trim();
    if (!code || submitting) {
      return;
    }
    setSubmitError(null);
    setSubmitting(true);
    try {
      const started = await tieredApi.start(code);
      setStockCode('');
      await refreshRuns();
      handleSelect(started.task_id);
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : String(error));
    } finally {
      setSubmitting(false);
    }
  }, [stockCode, submitting, refreshRuns, handleSelect]);

  return (
    <AppPage>
      <PageHeader
        eyebrow="v1"
        title={t('tiered.title')}
        description={t('tiered.subtitle')}
      />

      <Card className="mt-4 p-4">
        <form
          className="flex flex-col gap-3 sm:flex-row sm:items-center"
          onSubmit={(event) => {
            event.preventDefault();
            void handleRun();
          }}
        >
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
