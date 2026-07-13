import type { UiTextKey } from '../../i18n/uiText';

// The backend records its data notes as engineer-speak ("unparseable sniper
// level ideal_buy=…"). Each known shape is matched here and rewritten as a
// plain-English sentence via an i18n key; the raw message stays available
// in a popup for anyone who wants the exact detail. Unknown shapes fall
// back to the raw text — never invent a friendly sentence we can't back up.

type Translate = (key: UiTextKey, params?: Record<string, string | number>) => string;

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
  toText: (match: RegExpMatchArray, t: Translate) => string;
}

const NOTE_RULES: NoteRule[] = [
  {
    pattern: /^unparseable sniper level (\w+)='?(.*?)'?$/,
    toText: (m, t) =>
      t('tiered.note.textLevel', {
        level: SNIPER_SOURCE_LABEL_KEYS[m[1]] ? t(SNIPER_SOURCE_LABEL_KEYS[m[1]]) : m[1],
        text: m[2],
      }),
  },
  {
    pattern: /^sniper points missing from tier-1 result$/,
    toText: (_m, t) => t('tiered.note.levelsMissing'),
  },
  {
    pattern: /^page fetch blocked for (\S+); using shorter search extract instead$/,
    toText: (m, t) => t('tiered.note.pageBlocked', { domain: hostOf(m[1]) }),
  },
  {
    pattern: /^fetch (?:failed for|returned no content for) (\S+?):?(?:\s|$)/,
    toText: (m, t) => t('tiered.note.fetchFailed', { domain: hostOf(m[1]) }),
  },
  {
    pattern: /^EDGAR (?:fundamentals failed|returned no usable annual facts)/,
    toText: (_m, t) => t('tiered.note.fundamentalsUnavailable'),
  },
  {
    pattern: /^Yahoo (?:valuation failed|returned no valuation ratios)/,
    toText: (_m, t) => t('tiered.note.valuationUnavailable'),
  },
  {
    pattern: /^FRED series (\S+) (?:failed|returned no data)/,
    toText: (m, t) => t('tiered.note.macroUnavailable', { series: m[1] }),
  },
  {
    pattern: /^LLM sentiment output unparseable or empty$/,
    toText: (_m, t) => t('tiered.note.sentimentUnreadable'),
  },
  {
    pattern: /^no verifiable citations survive — discarding narrative$/,
    toText: (_m, t) => t('tiered.note.citationsDiscarded'),
  },
  {
    pattern: /^citation dropped: quote not found in (\S+?):?\s/,
    toText: (m, t) => t('tiered.note.citationQuoteMissing', { domain: hostOf(m[1]) }),
  },
  {
    pattern: /^citation dropped: invalid source index/,
    toText: (_m, t) => t('tiered.note.citationBadIndex'),
  },
  {
    pattern: /^malformed adjustment entry ignored$/,
    toText: (_m, t) => t('tiered.note.adjustmentMalformed'),
  },
  {
    pattern: /^adjustment for '?(\w+)'?\b/,
    toText: (m, t) =>
      t('tiered.note.adjustmentRejected', {
        level: LEVEL_LABEL_KEYS[m[1]] ? t(LEVEL_LABEL_KEYS[m[1]]) : m[1],
      }),
  },
  {
    pattern: / — falling back to the ATR stop$/,
    toText: (_m, t) => t('tiered.note.stopFallback'),
  },
  {
    pattern: /^no ATR available to derive a volatility stop$/,
    toText: (_m, t) => t('tiered.note.noAtrStop'),
  },
  {
    pattern: /^no usable ATR — no volatility stop, and no target without a stop$/,
    toText: (_m, t) => t('tiered.note.noAtrStopTarget'),
  },
  {
    pattern: /^no deeper support strictly below the ideal entry — no backup entry$/,
    toText: (_m, t) => t('tiered.note.noBackupEntry'),
  },
  {
    pattern: /^no usable entry price — cannot place a stop$/,
    toText: (_m, t) => t('tiered.note.noEntryNoStop'),
  },
  {
    pattern: /^(?:risk )?judge confidence .* unusable — dropped$/,
    toText: (_m, t) => t('tiered.note.judgeConfidenceDropped'),
  },
  {
    pattern: /^judge gave no summary$/,
    toText: (_m, t) => t('tiered.note.judgeNoSummary'),
  },
  {
    pattern: /^risk judge gave no summary$/,
    toText: (_m, t) => t('tiered.note.riskNoSummary'),
  },
  {
    pattern: /^(?:judge|risk) claim not anchored to evidence \(kept, flagged\)/,
    toText: (_m, t) => t('tiered.note.claimNoEvidence'),
  },
  {
    pattern: /^risk judge stop advice .* unusable/,
    toText: (_m, t) => t('tiered.note.stopAdviceUnusable'),
  },
  {
    pattern: /^tightened stop .* — dropped$/,
    toText: (_m, t) => t('tiered.note.tightenedStopDropped'),
  },
  {
    pattern: / is not a number — ignored$/,
    toText: (_m, t) => t('tiered.note.badSetting'),
  },
];

// Plain-English rewrite of one backend data note, or null when the shape
// is unknown (caller shows the raw text as-is).
export function friendlyWarning(raw: string, t: Translate): string | null {
  for (const rule of NOTE_RULES) {
    const match = raw.match(rule.pattern);
    if (match) {
      return rule.toText(match, t);
    }
  }
  return null;
}
