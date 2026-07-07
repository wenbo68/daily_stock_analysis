import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Layers, Search } from 'lucide-react';
import { tieredApi, type TieredDimension, type TieredResult } from '../api/tiered';
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
import type { UiTextKey } from '../i18n/uiText';

const POLL_INTERVAL_MS = 4000;

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
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
  }
  return String(value);
}

const PayloadTable: React.FC<{ payload: Record<string, unknown> }> = ({ payload }) => (
  <div className="space-y-3">
    {Object.entries(payload).map(([group, values]) => {
      if (values !== null && typeof values === 'object' && !Array.isArray(values)) {
        return (
          <div key={group}>
            <div className="label-uppercase mb-1">{group}</div>
            <dl className="grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-2">
              {Object.entries(values as Record<string, unknown>).map(([key, value]) => (
                <div key={key} className="flex items-baseline justify-between gap-3 border-b border-border/30 py-1">
                  <dt className="text-xs text-secondary-text">{key}</dt>
                  <dd className="font-mono text-xs text-foreground">{formatValue(value)}</dd>
                </div>
              ))}
            </dl>
          </div>
        );
      }
      return (
        <div key={group} className="flex items-baseline justify-between gap-3 border-b border-border/30 py-1">
          <dt className="text-xs text-secondary-text">{group}</dt>
          <dd className="font-mono text-xs text-foreground">{formatValue(values)}</dd>
        </div>
      );
    })}
  </div>
);

const DimensionCard: React.FC<{ dimension: TieredDimension }> = ({ dimension }) => {
  const { t } = useUiLanguage();
  const labelKey = DIMENSION_LABEL_KEYS[dimension.dimension];

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

      {dimension.citations.length > 0 ? (
        <div className="mt-3">
          <div className="label-uppercase mb-1">{t('tiered.citations')}</div>
          <ul className="space-y-1">
            {dimension.citations.map((citation, index) => (
              <li key={index} className="truncate text-xs">
                {citation.url ? (
                  <a
                    href={citation.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-cyan hover:underline"
                  >
                    {citation.title || citation.url}
                  </a>
                ) : (
                  <span className="text-secondary-text">{citation.source_name}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {dimension.warnings.length > 0 ? (
        <ul className="mt-3 space-y-1">
          {dimension.warnings.map((warning, index) => (
            <li key={index} className="text-xs text-warning">
              {warning}
            </li>
          ))}
        </ul>
      ) : null}
    </Card>
  );
};

const LevelTile: React.FC<{ label: string; value: number | null }> = ({ label, value }) => (
  <div className="rounded-xl border border-border/40 bg-elevated/60 px-3 py-2">
    <div className="text-xs text-secondary-text">{label}</div>
    <div className="mt-1 font-mono text-base text-foreground">{value ?? '—'}</div>
  </div>
);

const TieredAnalysisPage: React.FC = () => {
  const { t } = useUiLanguage();
  const [stockCode, setStockCode] = useState('');
  const [taskId, setTaskId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<TieredResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  useEffect(() => {
    if (!taskId || !running) {
      return;
    }
    pollRef.current = window.setInterval(async () => {
      try {
        const task = await tieredApi.getTask(taskId);
        if (task.status === 'done' && task.result) {
          stopPolling();
          setRunning(false);
          setResult(task.result);
        } else if (task.status === 'failed') {
          stopPolling();
          setRunning(false);
          setError(task.error || t('tiered.error.title'));
        }
      } catch {
        // transient poll failure — keep polling; the run continues server-side
      }
    }, POLL_INTERVAL_MS);
    return stopPolling;
  }, [taskId, running, stopPolling, t]);

  const handleRun = useCallback(async () => {
    const code = stockCode.trim();
    if (!code || running) {
      return;
    }
    setError(null);
    setResult(null);
    try {
      const task = await tieredApi.start(code);
      setTaskId(task.task_id);
      setRunning(true);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
    }
  }, [stockCode, running]);

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
              disabled={running}
              aria-label={t('tiered.inputPlaceholder')}
            />
          </div>
          <Button
            type="submit"
            variant="primary"
            isLoading={running}
            loadingText={t('tiered.run')}
            disabled={!stockCode.trim() || running}
          >
            <Search className="mr-1 h-4 w-4" />
            {t('tiered.run')}
          </Button>
        </form>
        {running ? (
          <p className="mt-3 text-sm text-secondary-text">{t('tiered.running')}</p>
        ) : null}
      </Card>

      {error ? (
        <div className="mt-4">
          <InlineAlert variant="danger" title={t('tiered.error.title')} message={error} />
        </div>
      ) : null}

      {!result && !running && !error ? (
        <div className="mt-6">
          <EmptyState icon={<Layers className="h-8 w-8" />} title={t('tiered.empty')} />
        </div>
      ) : null}

      {result ? (
        <div className="mt-4 space-y-4">
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
              <span className="text-sm text-secondary-text">
                {t('tiered.coverage')}:{' '}
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
              <ul className="mt-3 space-y-1">
                {result.warnings.map((warning, index) => (
                  <li key={index} className="text-xs text-warning">
                    {warning}
                  </li>
                ))}
              </ul>
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
      ) : null}
    </AppPage>
  );
};

export default TieredAnalysisPage;
