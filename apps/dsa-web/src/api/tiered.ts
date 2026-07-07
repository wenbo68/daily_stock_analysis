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

export type TieredTask = {
  task_id: string;
  stock_code: string;
  status: 'running' | 'done' | 'failed';
  result?: TieredResult;
  error?: string;
};

export const tieredApi = {
  start: async (stockCode: string): Promise<TieredTask> => {
    const response = await apiClient.post<TieredTask>('/api/v1/tiered/analyze', {
      stock_code: stockCode,
    });
    return response.data;
  },

  getTask: async (taskId: string): Promise<TieredTask> => {
    const response = await apiClient.get<TieredTask>(`/api/v1/tiered/tasks/${taskId}`);
    return response.data;
  },
};
