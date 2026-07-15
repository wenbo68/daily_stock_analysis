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

// v4 judge grade for one validity axis: the 0-5 score plus, below 5, the
// exact offending sentence and why it is wrong (both null at 5/5 → N/A).
export type TieredAxisGrade = {
  score: number;
  quote?: string | null;
  why?: string | null;
};

// One debater's numbers — its own 0-10 position score plus the judge's
// three 0-5 validity grades; weight = (sum of grades) / 15. v3 runs store
// the position score as `bullishness` and the axes as bare numbers; v4
// runs store `position_score` and axis objects with quote/why comments.
export type TieredDebaterScore = {
  position_score?: number;
  bullishness?: number;
  citation_validity: number | TieredAxisGrade;
  knowledge_validity: number | TieredAxisGrade;
  logical_validity: number | TieredAxisGrade;
  weight: number;
  notes?: string | null;
};

// Bull/bear debate audit trail (tier-2 section). Three generations coexist
// in stored runs: the v2 judged shape (confidence, reasons, would_change_
// mind), the v3 scored shape (final_score, scoring, corrected bull/bear
// summaries), and the v4 threaded shape (turn kinds, axis-grade comments)
// — every generation-specific field is optional.
export type TieredDebateDetail = {
  turns: {
    role: string;
    // v2/v3 runs number their rounds; v4 turns carry a kind instead.
    round?: number;
    kind?: string;
    argument: string;
    bullishness?: number | null;
    position_score?: number | null;
    citations?: string[];
  }[];
  verdict: {
    direction: string;
    summary: string;
    // v2 judged shape
    confidence?: number | null;
    reasons_for?: TieredAnchoredReason[];
    reasons_against?: TieredAnchoredReason[];
    would_change_mind?: string | null;
    // v3 scored shape
    final_score?: number | null;
    final_score_rounded?: number | null;
    bull_summary?: string | null;
    bear_summary?: string | null;
    scoring?: { bull: TieredDebaterScore; bear: TieredDebaterScore } | null;
  } | null;
  warnings: string[];
};

// v2 slice 5: risk stress audit trail (tier-3 section).
export type TieredRiskDetail = {
  takes: { persona: string; assessment: string }[];
  verdict: {
    stance: string;
    size_multiplier: number;
    // Absent on runs stored before the risk judge reported its own 0-1
    // sureness; the UI hides the score for those.
    confidence?: number | null;
    stop_advice: string;
    tightened_stop: number | null;
    summary: string;
    key_risks: TieredAnchoredReason[];
  } | null;
  warnings: string[];
};

export type TieredCoverage = 'full' | 'partial' | 'unavailable';

// The deepest tier's verdict in summary form — what the run ends on.
export type TieredFinal = {
  tier: number;
  direction: 'buy' | 'hold' | 'sell' | 'unknown';
  coverage: 'full' | 'partial' | 'unavailable';
  confidence: string | null;
  levels: TieredLevels;
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
  final?: TieredFinal | null;
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
  // Digest of the stored report for the history rows. Null while running,
  // after a failure, or on rows stored before the backend sent these.
  // shares mirrors the report card: 0 = sizing ran but bought nothing,
  // null = the run has no sizing block (shown as a dash).
  direction?: 'buy' | 'hold' | 'sell' | 'unknown' | null;
  shares?: number | null;
  // The tier the run went to (1-3); null while running/failed.
  tier?: number | null;
  // The sizing inputs the run used (capital in the ticker's own currency,
  // risk as a 0-1 fraction); null when the run had no sizing block.
  capital?: number | null;
  risk_fraction?: number | null;
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

  // 200 is the backend's cap; the page paginates client-side over this.
  listRuns: async (limit = 200): Promise<TieredRunSummary[]> => {
    const response = await apiClient.get<{ items: TieredRunSummary[] }>('/api/v1/tiered/runs', {
      params: { limit },
    });
    return response.data.items;
  },

  getRun: async (taskId: string): Promise<TieredRun> => {
    const response = await apiClient.get<TieredRun>(`/api/v1/tiered/runs/${taskId}`);
    return response.data;
  },

  // Saved sizing settings (.env-backed) — what a run uses when the form
  // sends nothing. Both null when no defaults are configured.
  sizingDefaults: async (): Promise<{ capital: number | null; risk_fraction: number | null }> => {
    const response = await apiClient.get<{ capital: number | null; risk_fraction: number | null }>(
      '/api/v1/tiered/sizing-defaults',
    );
    return response.data;
  },
};
