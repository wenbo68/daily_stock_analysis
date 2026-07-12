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

export type TieredLevels = {
  entry: number | null;
  secondary_entry: number | null;
  stop_loss: number | null;
  take_profit: number | null;
};

// v2 slice 3 audit trail: per-level formula base + validated AI adjustment.
export type TieredLevelDetail = {
  base: number | null;
  formula: string | null;
  inputs: Record<string, number> | null;
  adjusted: number | null;
  reason: string | null;
  evidence: string[];
  rejection: string | null;
  final: number | null;
};

export type TieredLevelsDetail = {
  levels: Record<string, TieredLevelDetail>;
  warnings: string[];
};

export type TieredAnchoredReason = {
  claim: string;
  evidence: string[];
};

// v2 slice 4: bull/bear debate audit trail (tier-2 section).
export type TieredDebateDetail = {
  turns: { role: string; round: number; argument: string }[];
  verdict: {
    direction: string;
    confidence: number | null;
    summary: string;
    reasons_for: TieredAnchoredReason[];
    reasons_against: TieredAnchoredReason[];
    would_change_mind: string | null;
  } | null;
  warnings: string[];
};

// v2 slice 5: risk stress audit trail (tier-3 section).
export type TieredRiskDetail = {
  takes: { persona: string; assessment: string }[];
  verdict: {
    stance: string;
    size_multiplier: number;
    stop_advice: string;
    tightened_stop: number | null;
    summary: string;
    key_risks: TieredAnchoredReason[];
  } | null;
  warnings: string[];
};

export type TieredTierSection = {
  tier: number;
  coverage: 'full' | 'partial' | 'unavailable';
  direction: 'buy' | 'hold' | 'sell' | 'unknown';
  confidence: string | null;
  score: number | null;
  levels: TieredLevels;
  narrative: string | null;
  warnings: string[];
  debate_detail?: TieredDebateDetail;
  risk_detail?: TieredRiskDetail;
};

// v2 slice 6: deterministic sizing block (share count or explicit refusal).
export type TieredSizing = {
  enabled: boolean;
  shares: number | null;
  shares_before_multiplier: number | null;
  risk_multiplier: number | null;
  position_value: number | null;
  risk_amount: number | null;
  loss_per_share: number | null;
  lot_size: number;
  cap_applied: boolean;
  reason_code: string | null;
  refusal_reason: string | null;
  notes: string[];
  inputs: {
    capital: number | null;
    risk_fraction: number | null;
    max_position_fraction: number | null;
    fee_fraction: number | null;
    entry: number | null;
    stop_loss: number | null;
  };
};

export type TieredLlmUsage = {
  stages: Record<string, { calls: number; prompt_tokens: number; completion_tokens: number }>;
  total: { calls: number; prompt_tokens: number; completion_tokens: number };
  scope: string;
};

export type TieredResult = {
  symbol: string;
  market: string;
  tier: number;
  direction: 'buy' | 'hold' | 'sell' | 'unknown';
  score: number | null;
  confidence: string | null;
  coverage: 'full' | 'partial' | 'unavailable';
  levels: TieredLevels;
  levels_detail?: TieredLevelsDetail | null;
  narrative: string | null;
  warnings: string[];
  dimensions: TieredDimension[];
  signal: {
    logged: boolean;
    signal_id: number | null;
    created: boolean | null;
    reason: string | null;
  } | null;
  // v2 slice 6 additions — absent on old stored runs, so all optional.
  depth?: number;
  final?: {
    tier: number;
    direction: 'buy' | 'hold' | 'sell' | 'unknown';
    coverage: 'full' | 'partial' | 'unavailable';
    confidence: string | null;
    levels: TieredLevels;
  } | null;
  tier2?: TieredTierSection | null;
  tier3?: TieredTierSection | null;
  sizing?: TieredSizing | null;
  llm_usage?: TieredLlmUsage | null;
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

export type TieredDepth = 1 | 2 | 3;

export type TieredSizingRequest = {
  capital?: number;
  risk_fraction?: number;
};

export const tieredApi = {
  start: async (
    stockCode: string,
    depth: TieredDepth = 1,
    sizing?: TieredSizingRequest,
  ): Promise<{ task_id: string }> => {
    const response = await apiClient.post<{ task_id: string }>('/api/v1/tiered/analyze', {
      stock_code: stockCode,
      depth,
      ...(sizing && Object.keys(sizing).length > 0 ? { sizing } : {}),
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
