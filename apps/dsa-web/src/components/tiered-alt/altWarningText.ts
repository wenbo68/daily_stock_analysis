import type { UiTextKey } from '../../i18n/uiText';

// The backend records its data notes as engineer-speak ("unparseable sniper
// level ideal_buy=…"). Each known shape is matched here and rewritten as a
// plain-English sentence via an i18n key, led by a fixed keyword — chosen
// per rule from the closed list below (owner decision 2026-07-24), never
// generated, mirroring the plan-warnings modal's id → keyword map. Unknown
// shapes fall back to the raw text with no keyword — never invent a
// friendly sentence we can't back up.

type Translate = (key: UiTextKey, params?: Record<string, string | number>) => string;

// The closed keyword list. Every note leads with one of these.
const KEY = {
  missingData: 'tiered.note.key.missingData',
  fetchFailed: 'tiered.note.key.fetchFailed',
  citations: 'tiered.note.key.citations',
  aiReply: 'tiered.note.key.aiReply',
  levels: 'tiered.note.key.levels',
  verdict: 'tiered.note.key.verdict',
  vote: 'tiered.note.key.vote',
  debate: 'tiered.note.key.debate',
  riskCheck: 'tiered.note.key.riskCheck',
  settings: 'tiered.note.key.settings',
  // The plan card's warnings row shows these same facts under these same
  // keywords — the notes list must not word them differently.
  rewardRatio: 'tiered.alt.warnKey.reward_below_goal',
  downtrend: 'tiered.alt.warnKey.downtrend',
} as const satisfies Record<string, UiTextKey>;

// Backend sniper-level source names → the level labels users already know.
const SNIPER_SOURCE_LABEL_KEYS: Record<string, UiTextKey> = {
  ideal_buy: 'tiered.levels.entry',
  secondary_buy: 'tiered.levels.secondaryEntry',
  stop_loss: 'tiered.levels.stopLoss',
  take_profit: 'tiered.levels.takeProfit',
};

// Level keys as they appear in adjustment warnings ("adjustment for entry …").
const LEVEL_LABEL_KEYS: Record<string, UiTextKey> = {
  entry: 'tiered.levels.entry',
  secondary_entry: 'tiered.levels.secondaryEntry',
  stop_loss: 'tiered.levels.stopLoss',
  take_profit: 'tiered.levels.takeProfit',
};

function hostOf(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

interface NoteRule {
  pattern: RegExp;
  keywordKey: UiTextKey;
  toText: (match: RegExpMatchArray, t: Translate) => string;
}

const NOTE_RULES: NoteRule[] = [
  {
    pattern: /^reward below goal: .*reward-to-risk at ([\d.]+), below your ([\d.]+)/,
    keywordKey: KEY.rewardRatio,
    toText: (m, t) =>
      t('tiered.alt.rewardBelowGoal', { ratio: m[1], goal: m[2] }),
  },
  {
    pattern: /^trend warning: close .* is at or below the 60-day average/,
    keywordKey: KEY.downtrend,
    toText: (_m, t) => t('tiered.note.downtrend'),
  },
  {
    pattern: /^sma_60 unavailable — trend check skipped$/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.trendCheckSkipped'),
  },
  {
    pattern: /^unparseable sniper level (\w+)='?(.*?)'?$/,
    keywordKey: KEY.levels,
    toText: (m, t) =>
      t('tiered.note.textLevel', {
        level: SNIPER_SOURCE_LABEL_KEYS[m[1]] ? t(SNIPER_SOURCE_LABEL_KEYS[m[1]]) : m[1],
        text: m[2],
      }),
  },
  {
    pattern: /^sniper points missing from tier-1 result$/,
    keywordKey: KEY.levels,
    toText: (_m, t) => t('tiered.note.levelsMissing'),
  },
  {
    pattern: /^page fetch blocked for (\S+); using shorter search extract instead$/,
    keywordKey: KEY.fetchFailed,
    toText: (m, t) => t('tiered.note.pageBlocked', { domain: hostOf(m[1]) }),
  },
  {
    pattern: /^fetch (?:failed for|returned no content for) (\S+?):?(?:\s|$)/,
    keywordKey: KEY.fetchFailed,
    toText: (m, t) => t('tiered.note.fetchFailed', { domain: hostOf(m[1]) }),
  },
  {
    pattern: /^EDGAR (?:fundamentals failed|returned no usable (?:annual|statement) facts)/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.fundamentalsUnavailable'),
  },
  {
    pattern: /^Yahoo (?:valuation failed|returned no valuation ratios)/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.valuationUnavailable'),
  },
  {
    pattern: /^FRED series (\S+) (?:failed|returned no data)/,
    keywordKey: KEY.missingData,
    toText: (m, t) => t('tiered.note.macroUnavailable', { series: m[1] }),
  },
  {
    // Both the retired "from Yahoo" wording and the source-neutral one.
    pattern: /^options open interest (?:from Yahoo is )?missing or zero/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.optionsOiMissing'),
  },
  {
    pattern: /^options volume (?:from Yahoo is )?missing or zero/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.optionsVolumeMissing'),
  },
  {
    pattern: /^Yahoo returned no insider transaction rows/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.insiderRowsMissing'),
  },
  {
    pattern: /^LLM sentiment output unparseable or empty$/,
    keywordKey: KEY.aiReply,
    toText: (_m, t) => t('tiered.note.sentimentUnreadable'),
  },
  {
    pattern: /^no verifiable citations survive — discarding narrative$/,
    keywordKey: KEY.citations,
    toText: (_m, t) => t('tiered.note.citationsDiscarded'),
  },
  {
    pattern: /^citation dropped: quote not found in (\S+?):?\s/,
    keywordKey: KEY.citations,
    toText: (m, t) => t('tiered.note.citationQuoteMissing', { domain: hostOf(m[1]) }),
  },
  {
    pattern: /^citation dropped: invalid source index/,
    keywordKey: KEY.citations,
    toText: (_m, t) => t('tiered.note.citationBadIndex'),
  },
  {
    pattern: /^malformed adjustment entry ignored$/,
    keywordKey: KEY.levels,
    toText: (_m, t) => t('tiered.note.adjustmentMalformed'),
  },
  {
    pattern: /^adjustment for '?(\w+)'?\b/,
    keywordKey: KEY.levels,
    toText: (m, t) =>
      t('tiered.note.adjustmentRejected', {
        level: LEVEL_LABEL_KEYS[m[1]] ? t(LEVEL_LABEL_KEYS[m[1]]) : m[1],
      }),
  },
  {
    pattern: / — falling back to the ATR stop$/,
    keywordKey: KEY.levels,
    toText: (_m, t) => t('tiered.note.stopFallback'),
  },
  {
    pattern: /^no ATR available to derive a volatility stop$/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.noAtrStop'),
  },
  {
    pattern: /^no usable ATR — no volatility stop, and no target without a stop$/,
    keywordKey: KEY.missingData,
    toText: (_m, t) => t('tiered.note.noAtrStopTarget'),
  },
  {
    pattern: /^no deeper support strictly below the ideal entry — no backup entry$/,
    keywordKey: KEY.levels,
    toText: (_m, t) => t('tiered.note.noBackupEntry'),
  },
  {
    pattern: /^no usable entry price — cannot place a stop$/,
    keywordKey: KEY.levels,
    toText: (_m, t) => t('tiered.note.noEntryNoStop'),
  },
  // --- v8 evidence-vote notes (tier 2) + format-2 risk-vote notes
  // (tier 3): the two engines share their phrasing, differing only in
  // bullet/risk wording ---
  {
    pattern: /^(?:first|second) analyst list invalid after retry — proceeding with/,
    keywordKey: KEY.vote,
    toText: (_m, t) => t('tiered.note.listerDegraded'),
  },
  {
    pattern: /^both analyst lists invalid after retry — tier-2 verdict voided$/,
    keywordKey: KEY.verdict,
    toText: (_m, t) => t('tiered.note.stageInvalid'),
  },
  {
    pattern: /^both analyst lists invalid after retry — tier-3 risk verdict voided$/,
    keywordKey: KEY.verdict,
    toText: (_m, t) => t('tiered.note.riskVoided'),
  },
  {
    pattern: /^risk stress produced no verdict — direction falls back to tier 2$/,
    keywordKey: KEY.verdict,
    toText: (_m, t) => t('tiered.note.riskFellBack'),
  },
  {
    pattern: /^merge invalid after retry — second list dropped$/,
    keywordKey: KEY.vote,
    toText: (_m, t) => t('tiered.note.mergeDegraded'),
  },
  {
    pattern: /^check round invalid after retry — (?:bullets|risks) counted on/,
    keywordKey: KEY.vote,
    toText: (_m, t) => t('tiered.note.checkDegraded'),
  },
  {
    pattern: /^deciding round invalid after retry — tied (?:bullets|risks) excluded/,
    keywordKey: KEY.vote,
    toText: (_m, t) => t('tiered.note.tiebreakDegraded'),
  },
  {
    pattern: /^analyst \S+: citations unfixable .* — struck from the list$/,
    keywordKey: KEY.citations,
    toText: (_m, t) => t('tiered.note.struckBullet'),
  },
  {
    pattern: /^vote on \S+ discarded — citations unfixable/,
    keywordKey: KEY.citations,
    toText: (_m, t) => t('tiered.note.voteDiscarded'),
  },
  {
    pattern: /^no deciding vote for \S+ — excluded as unresolved$/,
    keywordKey: KEY.vote,
    toText: (_m, t) => t('tiered.note.unresolved'),
  },
  {
    pattern: /^every (?:bullet|risk) was listed by both analysts — check round skipped$/,
    keywordKey: KEY.vote,
    toText: (_m, t) => t('tiered.note.allConfirmed'),
  },
  {
    pattern: / — the final score rests on a thin base$/,
    keywordKey: KEY.vote,
    toText: (_m, t) => t('tiered.note.thinBase'),
  },
  // --- v7 tree-debate notes ---
  {
    pattern: /^defender \S+: citations unfixable .* — struck from the debate$/,
    keywordKey: KEY.citations,
    toText: (_m, t) => t('tiered.note.struckBullet'),
  },
  {
    pattern: /^attacker \S+: citations unfixable .* — bullet dropped$/,
    keywordKey: KEY.citations,
    toText: (_m, t) => t('tiered.note.attackerBulletDropped'),
  },
  {
    pattern: /citation-fix reply invalid — fix round lost$/,
    keywordKey: KEY.citations,
    toText: (_m, t) => t('tiered.note.fixRoundLost'),
  },
  {
    pattern: /^summary citations unfixable — those values are shown without links$/,
    keywordKey: KEY.citations,
    toText: (_m, t) => t('tiered.note.summaryLinksDropped'),
  },
  // --- v6 tree-debate notes ---
  {
    pattern: /citation check failed mechanically$/,
    keywordKey: KEY.citations,
    toText: (_m, t) => t('tiered.note.valueMismatch'),
  },
  {
    pattern: / — link dropped$/,
    keywordKey: KEY.citations,
    toText: (_m, t) => t('tiered.note.linkDropped'),
  },
  {
    pattern: /evidence restored to the final pool$/,
    keywordKey: KEY.debate,
    toText: (_m, t) => t('tiered.note.restoredEvidence'),
  },
  {
    pattern: /included in the final pool$/,
    keywordKey: KEY.debate,
    toText: (_m, t) => t('tiered.note.includedAddition'),
  },
  // --- v5 tree-debate notes ---
  {
    pattern: /^(?:defender opening|defender reply|judge rulings) invalid after retry — tier-2 verdict voided$/,
    keywordKey: KEY.verdict,
    toText: (_m, t) => t('tiered.note.stageInvalid'),
  },
  {
    pattern: /^attacker (?:opening|review) invalid after retry — proceeding without/,
    keywordKey: KEY.debate,
    toText: (_m, t) => t('tiered.note.attackerDegraded'),
  },
  {
    pattern: / needed a retry — first reply was invalid$/,
    keywordKey: KEY.aiReply,
    toText: (_m, t) => t('tiered.note.stageRetried'),
  },
  {
    pattern: /(?: was not JSON even after a retry| invalid after retry: )/,
    keywordKey: KEY.aiReply,
    toText: (_m, t) => t('tiered.note.stageInvalid'),
  },
  {
    pattern: /^defender accepted an attack the judge ruled wrong/,
    keywordKey: KEY.debate,
    toText: (_m, t) => t('tiered.note.concededFlawedAttack'),
  },
  {
    pattern: /^attacker raised no challenges — defender response skipped/,
    keywordKey: KEY.debate,
    toText: (_m, t) => t('tiered.note.noChallenges'),
  },
  {
    pattern: /^no surviving evidence to weigh/,
    keywordKey: KEY.debate,
    toText: (_m, t) => t('tiered.note.emptyLedger'),
  },
  {
    pattern: / — the weight rests on a thin base$/,
    keywordKey: KEY.debate,
    toText: (_m, t) => t('tiered.note.thinBase'),
  },
  {
    pattern: /^(defender|attacker|judge) cited evidence that does not resolve to a single value/,
    keywordKey: KEY.citations,
    toText: (m, t) =>
      t('tiered.note.treeBadRefs', { side: t(`tiered.tree.${m[1]}` as UiTextKey) }),
  },
  // --- pre-v5 debate notes (old stored runs) ---
  {
    // v3: "bull reply was not JSON — argument kept as plain text, no score"
    // v4: "bull argument|attack|response was not JSON — kept as plain text[, no score]"
    pattern: /^(bull|bear) (?:reply|argument|attack|response) was not JSON — .*kept as plain text/,
    keywordKey: KEY.aiReply,
    toText: (m, t) =>
      t('tiered.note.debaterNotJson', {
        side: t(m[1] === 'bull' ? 'tiered.debate.bull' : 'tiered.debate.bear'),
      }),
  },
  {
    pattern: /^(bull|bear) (?:bullishness|position score) .* is not a whole number 0-10 — dropped$/,
    keywordKey: KEY.aiReply,
    toText: (m, t) =>
      t('tiered.note.debaterScoreDropped', {
        side: t(m[1] === 'bull' ? 'tiered.debate.bull' : 'tiered.debate.bear'),
      }),
  },
  {
    pattern: /^no usable (?:bullishness|position) score from .* — tier-2 verdict voided$/,
    keywordKey: KEY.verdict,
    toText: (_m, t) => t('tiered.note.debateVoided'),
  },
  {
    pattern: /^(bull|bear) cited evidence that does not resolve — invalid refs dropped$/,
    keywordKey: KEY.citations,
    toText: (m, t) =>
      t('tiered.note.debaterBadRefs', {
        side: t(m[1] === 'bull' ? 'tiered.debate.bull' : 'tiered.debate.bear'),
      }),
  },
  {
    pattern: /^grading judge gave no quote for .* — kept, flagged$/,
    keywordKey: KEY.debate,
    toText: (_m, t) => t('tiered.note.gradingNoQuote'),
  },
  {
    pattern: /^grading judge quote for .* not found verbatim in the transcript — kept, flagged$/,
    keywordKey: KEY.debate,
    toText: (_m, t) => t('tiered.note.gradingQuoteMismatch'),
  },
  {
    pattern: /^grading judge .* voided$/,
    keywordKey: KEY.verdict,
    toText: (_m, t) => t('tiered.note.gradingVoided'),
  },
  {
    pattern: /^both debaters graded zero validity/,
    keywordKey: KEY.debate,
    toText: (_m, t) => t('tiered.note.zeroValidity'),
  },
  {
    pattern: /^(?:judge summary unparseable|summary LLM call failed: .*) — computed verdict stands$/,
    keywordKey: KEY.aiReply,
    toText: (_m, t) => t('tiered.note.summaryFailed'),
  },
  {
    pattern: /^(?:risk )?judge confidence .* unusable — dropped$/,
    keywordKey: KEY.aiReply,
    toText: (_m, t) => t('tiered.note.judgeConfidenceDropped'),
  },
  {
    pattern: /^judge gave no summary$/,
    keywordKey: KEY.aiReply,
    toText: (_m, t) => t('tiered.note.judgeNoSummary'),
  },
  {
    pattern: /^risk judge gave no summary$/,
    keywordKey: KEY.aiReply,
    toText: (_m, t) => t('tiered.note.riskNoSummary'),
  },
  {
    pattern: /^(?:judge|risk) claim not anchored to evidence \(kept, flagged\)/,
    keywordKey: KEY.debate,
    toText: (_m, t) => t('tiered.note.claimNoEvidence'),
  },
  {
    pattern: /^risk judge stop advice .* unusable/,
    keywordKey: KEY.riskCheck,
    toText: (_m, t) => t('tiered.note.stopAdviceUnusable'),
  },
  {
    pattern: /^tightened stop .* — dropped$/,
    keywordKey: KEY.riskCheck,
    toText: (_m, t) => t('tiered.note.tightenedStopDropped'),
  },
  {
    pattern: / is not a number — ignored$/,
    keywordKey: KEY.settings,
    toText: (_m, t) => t('tiered.note.badSetting'),
  },
];

export interface FriendlyNote {
  /** The fixed keyword the note leads with (already translated). */
  keyword: string;
  /** The plain-English sentence (already translated). */
  text: string;
}

// Keyword + plain-English rewrite of one backend data note, or null when
// the shape is unknown (caller shows the raw text as-is, no keyword).
export function friendlyWarning(raw: string, t: Translate): FriendlyNote | null {
  for (const rule of NOTE_RULES) {
    const match = raw.match(rule.pattern);
    if (match) {
      return { keyword: t(rule.keywordKey), text: rule.toText(match, t) };
    }
  }
  return null;
}
