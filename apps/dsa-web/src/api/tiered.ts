import apiClient from './index';

// Types mirror the backend JSON verbatim (snake_case). Dimension payloads
// hold metric names like revenue_yoy_pct — do not camelize them.
export type TieredCitation = {
  source_name: string;
  url: string | null;
  title: string | null;
  snippet: string | null;
};

export type TieredDimension = {
  dimension: string;
  kind: 'numeric' | 'textual';
  coverage: 'full' | 'partial' | 'unavailable';
  is_actionable: boolean;
  payload: Record<string, unknown> | null;
  narrative: string | null;
  warnings: string[];
  citations: TieredCitation[];
};

export type TieredResult = {
  symbol: string;
  market: string;
  tier: number;
  direction: 'buy' | 'hold' | 'sell' | 'unknown';
  score: number | null;
  confidence: string | null;
  coverage: 'full' | 'partial' | 'unavailable';
  levels: {
    entry: number | null;
    secondary_entry: number | null;
    stop_loss: number | null;
    take_profit: number | null;
  };
  narrative: string | null;
  warnings: string[];
  dimensions: TieredDimension[];
  signal: {
    logged: boolean;
    signal_id: number | null;
    created: boolean | null;
    reason: string | null;
  } | null;
};

export type TieredRunStatus = 'running' | 'done' | 'failed';

export type TieredRunSummary = {
  task_id: string;
  stock_code: string;
  status: TieredRunStatus;
  error: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type TieredRun = TieredRunSummary & {
  result: TieredResult | null;
};

export const tieredApi = {
  start: async (stockCode: string): Promise<{ task_id: string }> => {
    const response = await apiClient.post<{ task_id: string }>('/api/v1/tiered/analyze', {
      stock_code: stockCode,
    });
    return response.data;
  },

  listRuns: async (limit = 50): Promise<TieredRunSummary[]> => {
    const response = await apiClient.get<{ items: TieredRunSummary[] }>('/api/v1/tiered/runs', {
      params: { limit },
    });
    return response.data.items;
  },

  getRun: async (taskId: string): Promise<TieredRun> => {
    const response = await apiClient.get<TieredRun>(`/api/v1/tiered/runs/${taskId}`);
    return response.data;
  },
};
