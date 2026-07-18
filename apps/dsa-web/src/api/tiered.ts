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

// --- v5/v6/v7 debate tree (defender/attacker/judge) ---

// Inline citation. v6: text = the words underlined in the claim, value =
// the claimed number (mismatch marks a code-detected contradiction).
// v7: payload links carry value (the report's display string; the claim
// contains it verbatim) with text null; sentiment links carry text (the
// words resting on that news source) with value null.
export type TieredDebateLink = {
  text?: string | null;
  ref: string;
  value: number | string | null;
  mismatch?: boolean;
};

// One citation-or-logic check; 'invalid' carries the reason + citations.
export type TieredDebateCheck = {
  verdict: 'valid' | 'invalid';
  reason: string | null;
  citations: string[];
};

// The defender's response to one challenge: its own checks ON the
// attack/addition. v6 stores the citation/logic pair (both valid →
// accepted); v7 stores the single `check` (valid → accepted). All three
// fields optional so both generations type-check.
export type TieredDebateResponse = {
  accepted: boolean;
  citation_check?: TieredDebateCheck;
  logic_check?: TieredDebateCheck;
  check?: TieredDebateCheck;
};

// The judge's word on one axis of a defender item: its own check when the
// axis was unattacked, a ruling on the attack when it was.
export type TieredDebateJudgeAxis = {
  kind: 'reason_check' | 'attack_ruling';
  verdict: 'valid' | 'invalid' | 'attack_right' | 'attack_wrong';
  reason: string | null;
  citations: string[];
};

export type TieredDebateJudgeAddition = {
  kind: 'addition_ruling';
  verdict: 'real' | 'bogus';
  reason: string | null;
  citations: string[];
};

// One v8 vote on a bullet: the check round's second vote or the
// deciding round's tiebreaker. Reasons carry the same code-verified
// links the bullets use.
export type TieredDebateVote = {
  role: 'checker' | 'decider';
  verdict: 'valid' | 'invalid';
  reason: string | null;
  links: TieredDebateLink[];
};

// One evidence item of the tree with everything that happened to it.
// v5 runs store citations + the count/outcome ledger; v6 runs store
// links + value_check + the per-axis checks; v7 runs store single-axis
// fields (attacker_check, one response, one judge line) plus struck +
// problems for bullets whose citations code could not fix; v8 runs
// store authors (how many analysts listed it independently) + votes —
// all optional so every generation renders.
export type TieredDebateItem = {
  id: string;
  dimension: string;
  direction: 'bullish' | 'bearish';
  claim: string;
  citations?: string[];
  links?: TieredDebateLink[];
  value_check?: { verdict: 'valid' | 'invalid'; problems: string[] } | null;
  struck?: boolean;
  problems?: string[];
  authors?: number;
  votes?: TieredDebateVote[];
  added_by_attacker?: boolean;
  attacker_checks?: { citation: TieredDebateCheck; logic: TieredDebateCheck } | null;
  attacker_check?: TieredDebateCheck | null;
  responses?: {
    citation: TieredDebateResponse | null;
    logic: TieredDebateResponse | null;
  };
  response: TieredDebateResponse | null;
  judge:
    | { citation: TieredDebateJudgeAxis; logic: TieredDebateJudgeAxis }
    | TieredDebateJudgeAddition
    | TieredDebateJudgeAxis
    | null;
  count?: { numerator: number; denominator: number } | null;
  outcome?: 'valid' | 'invalid' | 'neutral' | null;
  final_status?: 'counted' | 'excluded' | null;
  exclusion_reason?: string | null;
};

// Pool snapshot: per-dimension bullish/bearish counts plus the
// pool-wide totals and score. v6-v8 store a per-dimension score and an
// averaged overall score; v9 stores flat counting (10 × bullish/total)
// and no per-dimension score.
export type TieredDebatePool = {
  dimensions: Record<
    string,
    { bullish: number; bearish: number; total: number; score?: number | null }
  >;
  bullish: number;
  bearish: number;
  total: number;
  score: number | null;
};

// Bull/bear debate audit trail (tier-2 section). Four generations coexist
// in stored runs: the v2 judged shape (confidence, reasons, would_change_
// mind), the v3 scored shape (final_score, scoring, corrected bull/bear
// summaries), the v4 threaded shape (turn kinds, axis-grade comments),
// and the v5 tree (format: 5, items, weight ledger) — every
// generation-specific field is optional.
export type TieredDebateDetail = {
  // 5/6/7 on tree-format runs; absent on everything stored before.
  format?: number;
  items?: TieredDebateItem[];
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
    // v5/v6 tree shape (v5 scores are whole numbers + weight; v6 scores
    // are 2-decimal pool counts + pools)
    initial_score?: number | null;
    adjusted_score?: number | null;
    adjusted_kept?: boolean | null;
    weight?: { numerator: number; denominator: number; value: number } | null;
    // v8 pools drop the adjusted snapshot (no concede/adopt step).
    pools?: {
      initial: TieredDebatePool;
      adjusted?: TieredDebatePool;
      final: TieredDebatePool;
    } | null;
  } | null;
  warnings: string[];
};

// One tier-3 risk bullet (risk_detail format 2): the tier-2 vote-item
// shape minus the direction tag — every bullet is a risk, and code maps
// the confirmed count to the size multiplier.
export type TieredRiskItem = {
  id: string;
  dimension: string;
  claim: string;
  links?: TieredDebateLink[];
  struck?: boolean;
  problems?: string[];
  authors?: number;
  votes?: TieredDebateVote[];
  final_status?: 'counted' | 'excluded' | null;
  exclusion_reason?: string | null;
};

// Per-group and total risk counts for one pool snapshot.
export type TieredRiskCounts = {
  groups: Record<string, number>;
  total: number;
};

// Risk stress audit trail (tier-3 section). Two generations coexist in
// stored runs: the persona/judge shape (takes + stance/stop advice) and
// the format-2 risk vote (items + count-derived multiplier) — every
// generation-specific field is optional.
export type TieredRiskDetail = {
  // 2 on risk-vote runs; absent on the stored persona/judge runs.
  format?: number;
  takes: { persona: string; assessment: string }[];
  items?: TieredRiskItem[];
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
    // format 2: the code-owned count → multiplier arithmetic.
    confirmed_risks?: number;
    total_risks?: number;
    counts?: { initial: TieredRiskCounts; final: TieredRiskCounts } | null;
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
  // Ownership block (absent on runs stored before the ownership input):
  // held shares, and the exit size a sell verdict prints from them.
  ownership?: number | null;
  sell_shares?: number | null;
  sell_shares_before_multiplier?: number | null;
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
  ownership?: number;
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
