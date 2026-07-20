import { type ComponentProps, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import type {
  TieredAction,
  TieredAnchoredReason,
  TieredCitation,
  TieredEarnings,
  TieredResult,
  TieredSizing,
  TieredTierSection,
} from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { cn } from '../../utils/cn';
import { flashElement, formatPrice, sentimentCitations } from '../tiered/termHelpers';
import { HelpTerm as BaseHelpTerm } from '../tiered/terms';
import {
  adjustedCellId,
  computedCellId,
  directionOutlook,
  plainNumber,
  riskPctText,
} from './altFormat';
import { ALT_LINK, OUTLOOK_TEXT } from './altStyles';
import { AltRiskCard } from './AltRiskCard';
import {
  AltCard,
  AltEvidenceRefs,
  AltFold,
  AltNotesButton,
  AltSectionLabel,
  FVar,
} from './AltUi';
import { AltDebateScoring } from './AltDebateScoring';
import { AltDebateTree } from './AltDebateTree';
import { AltRiskTree } from './AltRiskTree';
import { AltDimensions } from './AltDimensions';
import { AltLevels } from './AltLevels';

// ---------- small shared pieces ----------

// Alt skin rule: help popups everywhere, dotted underlines nowhere.
const HelpTerm = (props: ComponentProps<typeof BaseHelpTerm>) => (
  <BaseHelpTerm underline={false} {...props} />
);

// An UPPERCASE title sitting above its card, like the page's section titles.
const AltBlock = ({
  title,
  helpKey,
  children,
}: {
  title: string;
  helpKey?: UiTextKey;
  children: ReactNode;
}) => (
  <section className="flex flex-col gap-2">
    <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500">
      {helpKey ? <HelpTerm label={title} helpKey={helpKey} /> : title}
    </h3>
    {children}
  </section>
);

// ---------- shares computation ----------

const REASON_KEYS: Record<string, UiTextKey> = {
  sizing_off: 'tiered.sizing.reason.sizing_off',
  not_a_buy: 'tiered.sizing.reason.not_a_buy',
  no_entry: 'tiered.sizing.reason.no_entry',
  no_stop: 'tiered.sizing.reason.no_stop',
  stop_not_below_entry: 'tiered.sizing.reason.stop_not_below_entry',
  invalid_input: 'tiered.sizing.reason.invalid_input',
  too_small: 'tiered.sizing.reason.too_small',
};

// A formula number that scroll-flashes the element it came from; plain
// text when the source isn't on screen (no task row to point at).
const FormulaLink = ({ targetId, children }: { targetId: string | null; children: ReactNode }) =>
  targetId ? (
    <button
      type="button"
      className={cn('cursor-pointer tabular-nums', ALT_LINK)}
      onClick={() => flashElement(targetId)}
    >
      {children}
    </button>
  ) : (
    <span className="tabular-nums text-gray-300">{children}</span>
  );

interface AltSharesComputationProps {
  sizing: TieredSizing;
  taskId?: string;
  /** Where the entry / stop-loss numbers already appear in this report. */
  entryTargetId: string | null;
  stopTargetId: string | null;
}

// Just the arithmetic, three lines: the formula in words, the same formula
// with this run's numbers (each number links to where it came from), and
// the share count it produces. The denominator is spelled out as
// (entry) − (stop loss) so every number in it already exists somewhere in
// this report. Runs where no count could be computed show the refusal
// reason instead.
const AltSharesComputation = ({
  sizing,
  taskId,
  entryTargetId,
  stopTargetId,
}: AltSharesComputationProps) => {
  const { t } = useUiLanguage();

  const capital = sizing.inputs.capital;
  const riskFraction = sizing.inputs.risk_fraction;
  const entry = sizing.inputs.entry;
  const stopLoss = sizing.inputs.stop_loss;
  // Multiplier died with tier 3 — new runs don't store the key at all.
  const multiplier = sizing.risk_multiplier ?? null;
  const feeFraction = sizing.inputs.fee_fraction ?? 0;

  // A sell verdict on a held position prints the exit size instead of a
  // buy refusal: held shares × the tier-3 multiplier (no multiplier —
  // depth < 3 — means the full holding goes).
  if (sizing.sell_shares != null && sizing.ownership) {
    return (
      <AltCard testId="alt-shares-computation">
        <div className="flex flex-col gap-2 text-sm">
          <p className="text-gray-400">
            <FVar>{t('tiered.alt.f.owned')}</FVar>
            {multiplier !== null ? (
              <>
                {' × '}
                <FVar>{t('tiered.alt.f.multiplier')}</FVar>
              </>
            ) : null}
          </p>
          <p className="text-gray-400" data-testid="alt-sell-formula">
            {'= '}
            <span className="tabular-nums text-gray-300">{sizing.ownership}</span>
            {multiplier !== null ? (
              <>
                {' × '}
                <FormulaLink targetId="alt-risk-multiplier">{multiplier}</FormulaLink>
              </>
            ) : null}
          </p>
          <p className="font-semibold text-gray-300">
            = {t('tiered.sizing.sellShares', { value: sizing.sell_shares })}
          </p>
        </div>
      </AltCard>
    );
  }

  if (
    sizing.shares === null ||
    capital === null ||
    riskFraction === null ||
    entry === null ||
    stopLoss === null
  ) {
    // "Sizing is off" must name only the input that is actually missing —
    // a run can carry capital but no risk per trade (or the reverse).
    const reasonKey =
      sizing.reason_code === 'sizing_off' && capital !== null
        ? 'tiered.sizing.reason.sizing_off_risk'
        : sizing.reason_code === 'sizing_off' && riskFraction !== null
          ? 'tiered.sizing.reason.sizing_off_capital'
          : sizing.reason_code
            ? REASON_KEYS[sizing.reason_code]
            : undefined;
    return (
      <AltCard testId="alt-shares-computation">
        <p className="text-sm text-amber-300">
          {reasonKey ? t(reasonKey) : (sizing.refusal_reason ?? t('tiered.sizing.notComputed'))}
        </p>
      </AltCard>
    );
  }

  // Round-trip fee rate; 0 for this user's runs, but when set it is part
  // of the loss per share, so the formula must show it.
  const feeTerm =
    feeFraction > 0 ? (
      <>
        {' + '}
        <FormulaLink targetId={entryTargetId}>{formatPrice(entry)}</FormulaLink>
        {' × '}
        <span className="tabular-nums text-gray-300">{riskPctText(feeFraction)}%</span>
      </>
    ) : null;

  return (
    <AltCard testId="alt-shares-computation">
      <div className="flex flex-col gap-2 text-sm">
        {/* Variables are italic words; parentheses only where the math
            needs them (grouping the loss per share). */}
        <p className="text-gray-400">
          <FVar>{t('tiered.alt.f.capital')}</FVar> × <FVar>{t('tiered.alt.f.risk')}</FVar>
          {multiplier !== null ? (
            <>
              {' × '}
              <FVar>{t('tiered.alt.f.multiplier')}</FVar>
            </>
          ) : null}
          {' / ('}
          <FVar>{t('tiered.alt.f.entry')}</FVar> − <FVar>{t('tiered.alt.f.stop')}</FVar>
          {feeFraction > 0 ? (
            <>
              {' + '}
              <FVar>{t('tiered.alt.f.entry')}</FVar> × <FVar>{t('tiered.alt.f.fee')}</FVar>
            </>
          ) : null}
          {')'}
        </p>
        <p className="text-gray-400" data-testid="alt-shares-formula">
          {'= '}
          <FormulaLink targetId={taskId ? `alt-run-${taskId}-capital` : null}>
            {plainNumber(capital)}
          </FormulaLink>
          {' × '}
          <FormulaLink targetId={taskId ? `alt-run-${taskId}-risk` : null}>
            {riskPctText(riskFraction)}%
          </FormulaLink>
          {multiplier !== null ? (
            <>
              {' × '}
              <FormulaLink targetId="alt-risk-multiplier">{multiplier}</FormulaLink>
            </>
          ) : null}
          {' / ('}
          <FormulaLink targetId={entryTargetId}>{formatPrice(entry)}</FormulaLink>
          {' − '}
          <FormulaLink targetId={stopTargetId}>{formatPrice(stopLoss)}</FormulaLink>
          {feeTerm}
          {')'}
        </p>
        <p className="font-semibold text-gray-300">
          = {t('tiered.altHistory.shares', { value: sizing.shares })}
        </p>
      </div>
    </AltCard>
  );
};

// ---------- tier cards ----------

// One header fact — quiet label, prominent value; the same styling for
// verdict, size, stop loss and score alike (children may recolor the
// value, e.g. the verdict's buy/hold/sell tint).
const AltFact = ({
  label,
  helpKey,
  children,
}: {
  label: string;
  helpKey?: UiTextKey;
  children: ReactNode;
}) => (
  <span className="text-xs text-gray-500">
    {helpKey ? <HelpTerm label={label} helpKey={helpKey} /> : label}
    {': '}
    <span className="text-sm font-semibold text-gray-200">{children}</span>
  </span>
);

// The unified per-tier "Score", shown out of 10. The tier-2/3 judges
// report 0-1 confidence; callers pass it as 0-100 and it rounds to /10.
const TierScore = ({ value, helpKey }: { value: number; helpKey: UiTextKey }) => {
  const { t } = useUiLanguage();
  return (
    <AltFact label={t('tiered.score')} helpKey={helpKey}>
      <span className="tabular-nums">{Math.round(value / 10)}/10</span>
    </AltFact>
  );
};

interface TierHeaderProps {
  section: Pick<TieredTierSection, 'direction' | 'coverage'>;
  notes?: string[];
  score?: number | null;
  scoreHelpKey?: UiTextKey;
  side?: ReactNode;
}

// The card's title lives above the card (AltBlock); inside, the header is
// one row of `Label: value` facts — Outlook first, any side facts (tier 3
// puts Size and Stop loss there), Score last — and the data-notes mark
// pinned top-right: nothing when the data was complete, ⚠ when partial, a
// red X when unavailable. The stored verdict is still buy/hold/sell; the
// outlook rename maps it to bullish/neutral/bearish for display.
const TierHeader = ({ section, notes, score, scoreHelpKey, side }: TierHeaderProps) => {
  const { t } = useUiLanguage();
  const outlook = directionOutlook(section.direction);
  return (
    <div className="mb-3 flex flex-wrap items-center gap-x-6 gap-y-1">
      <AltFact label={t('tiered.alt.outlook')}>
        {/* Same bullish/neutral/bearish tint as the run-history rows. */}
        <span className={OUTLOOK_TEXT[outlook]}>
          {t(`tiered.outlook.${outlook}` as UiTextKey)}
        </span>
      </AltFact>
      {side}
      {score != null && scoreHelpKey ? <TierScore value={score} helpKey={scoreHelpKey} /> : null}
      <span className="ml-auto">
        <AltNotesButton notes={notes ?? []} coverage={section.coverage} />
      </span>
    </div>
  );
};

// ---------- the conclusion (outlook redesign) ----------

// True when the run's local calendar day is before today's — a plan from
// a previous trading day should be re-run, not traded (owner decision:
// no expiry mechanism, just this note).
const isFromPreviousDay = (runDate: Date): boolean => {
  const now = new Date();
  return (
    new Date(runDate.getFullYear(), runDate.getMonth(), runDate.getDate()).getTime() <
    new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  );
};

interface AltConclusionProps {
  result: TieredResult;
  runDate?: Date | null;
}

// The run's bottom line, above everything else: the impersonal outlook,
// the personal action code derived from outlook × your ownership, the
// warning-only earnings note, and the previous-day staleness note.
const AltConclusion = ({ result, runDate }: AltConclusionProps) => {
  const { t } = useUiLanguage();
  const outlook = result.outlook ?? 'unknown';
  const action = result.action ?? 'unknown';
  const earnings: TieredEarnings | null = result.earnings ?? null;
  const stale = runDate ? isFromPreviousDay(runDate) : false;
  return (
    <AltCard testId="alt-conclusion">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-1">
        <AltFact label={t('tiered.alt.outlook')} helpKey="tiered.help.outlook">
          <span className={OUTLOOK_TEXT[outlook]}>
            {t(`tiered.outlook.${outlook}` as UiTextKey)}
          </span>
        </AltFact>
        <AltFact label={t('tiered.alt.action')} helpKey="tiered.help.action">
          {t(`tiered.action.${action}` as UiTextKey)}
        </AltFact>
      </div>
      {earnings?.is_near && earnings.days_until != null ? (
        <p className="mt-2 text-xs text-amber-300" data-testid="alt-earnings-warning">
          {t('tiered.alt.earningsWarning', {
            days: earnings.days_until,
            date: earnings.next_date ?? '—',
          })}
        </p>
      ) : null}
      {stale ? (
        <p className="mt-2 text-xs text-amber-300" data-testid="alt-stale-note">
          {t('tiered.alt.staleNote')}
        </p>
      ) : null}
    </AltCard>
  );
};

interface AltTierOneProps {
  result: TieredResult;
  citations: TieredCitation[];
  /** Undefined on old stored runs → the full levels table (legacy). */
  action?: TieredAction;
}

// A resistance-capped target that misses the user's chosen reward-to-risk
// ratio arrives as a backend warning; surface it ON the plan, not only in
// the notes popup.
const REWARD_BELOW_GOAL =
  /^reward below goal: .*reward-to-risk at ([\d.]+), below your ([\d.]+)/;

// The conditional plan display (owner decision): which levels show
// depends on the action. Old runs (no action) keep the full table.
const PlanBody = ({ result, citations, action }: AltTierOneProps) => {
  const { t } = useUiLanguage();
  const plan =
    action === undefined || action === 'enter' || action === 'unknown'
      ? 'full'
      : action;
  if (plan === 'full') {
    const rewardMiss = (result.warnings ?? [])
      .map((warning) => REWARD_BELOW_GOAL.exec(warning))
      .find((match) => match !== null);
    return (
      <div className="flex flex-col gap-2">
        {rewardMiss ? (
          <p className="text-xs text-amber-300" data-testid="alt-reward-warning">
            {t('tiered.alt.rewardBelowGoal', {
              ratio: rewardMiss[1],
              goal: rewardMiss[2],
            })}
          </p>
        ) : null}
        <AltLevels
          levels={result.levels}
          levelsDetail={result.levels_detail}
          citations={citations}
        />
      </div>
    );
  }
  if (plan === 'keep_holding') {
    // Holders get the one number that still matters: the structural
    // exit level. Entries and targets are entry-plan material and a
    // bullish-while-holding run deliberately does not say "buy more".
    return (
      <p className="text-sm" data-testid="alt-structural-stop">
        <span className="text-xs text-gray-500">
          <HelpTerm
            label={t('tiered.alt.structuralStop')}
            helpKey="tiered.help.structuralStop"
          />
          {': '}
        </span>
        <span className="font-semibold tabular-nums text-gray-200">
          {result.levels.stop_loss != null ? formatPrice(result.levels.stop_loss) : '—'}
        </span>
      </p>
    );
  }
  // no_trade / sell_all: no plan levels at all — the action line
  // already said what to do (sell counts live in the shares block).
  return (
    <p className="text-sm text-gray-500" data-testid="alt-no-plan">
      {t('tiered.alt.noPlan')}
    </p>
  );
};

const AltTierOne = ({ result, citations, action }: AltTierOneProps) => (
  <AltCard testId="alt-tier1">
    {/* No score here: tier 1's stored score is the analyzer's bullishness
        composite, not a judge confidence — showing it under the same
        "Score" label would mean two different things. */}
    <TierHeader
      section={{ direction: result.direction, coverage: result.coverage }}
      notes={result.warnings}
    />
    <PlanBody result={result} citations={citations} action={action} />
  </AltCard>
);

// Depth-2 runs skip the tier-1 one-blob verdict entirely, so the tier-1
// card is not shown — but the formula-computed plan still exists (and
// the shares arithmetic links into its numbers), so it gets a card of
// its own, with the run's data notes pinned top-right like a tier
// header would.
const AltPlanCard = ({ result, citations, action }: AltTierOneProps) => (
  <AltCard testId="alt-plan">
    <div className="mb-3 flex items-center justify-end">
      <AltNotesButton notes={result.warnings ?? []} coverage={result.coverage} />
    </div>
    <PlanBody result={result} citations={citations} action={action} />
  </AltCard>
);

interface AltTierSectionProps {
  section: TieredTierSection;
  citations: TieredCitation[];
}

// One side of the debate card: the judged (v2) shape shows anchored
// reasons; the scored (v3) shape shows the judge's corrected case summary.
const AltDebateColumn = ({
  labelKey,
  color,
  reasons,
  summary,
  citations,
}: {
  labelKey: UiTextKey;
  color: string;
  reasons: TieredAnchoredReason[];
  summary: string | null;
  citations: TieredCitation[];
}) => {
  const { t } = useUiLanguage();
  return (
    <div>
      <div className={cn('mb-1 text-xs font-semibold', color)}>{t(labelKey)}</div>
      {summary !== null ? (
        <p className="text-xs leading-relaxed">{summary}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {reasons.map((reason, index) => (
            <li key={index} className="text-xs">
              {reason.claim}
              {reason.evidence.length > 0 ? (
                <span className="mt-0.5 block">
                  <AltEvidenceRefs refs={reason.evidence} citations={citations} />
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

// v4 transcript turn kinds → their display labels.
const TURN_KIND_KEYS: Record<string, UiTextKey> = {
  argument: 'tiered.debate.kind.argument',
  attack: 'tiered.debate.kind.attack',
  response: 'tiered.debate.kind.response',
};

const AltDebate = ({ section, citations }: AltTierSectionProps) => {
  const { t } = useUiLanguage();
  const detail = section.debate_detail;
  const verdict = detail?.verdict ?? null;
  // v5/v6 runs carry the defender/attacker/judge tree and render it
  // whole — no scoring foldable, no bull/bear columns; the arithmetic
  // lives in the tree's own scores block.
  if (
    detail?.format != null &&
    detail.format >= 5 &&
    detail.format <= 11 &&
    Array.isArray(detail.items)
  ) {
    return (
      <AltCard testId="alt-tier2">
        <TierHeader
          section={section}
          notes={section.warnings}
          side={
            verdict?.final_score != null ? (
              <AltFact label={t('tiered.score')} helpKey="tiered.help.debateScore">
                <span className="tabular-nums">{verdict.final_score.toFixed(2)}/10</span>
              </AltFact>
            ) : null
          }
        />
        {section.narrative ? (
          <p className="mb-2 text-sm leading-relaxed">{section.narrative}</p>
        ) : null}
        {!verdict ? (
          <p className="text-sm text-amber-300">{t('tiered.debate.noVerdict')}</p>
        ) : null}
        <AltDebateTree detail={detail} />
      </AltCard>
    );
  }
  // Scored (v3) runs carry the formula's audit trail; older stored runs
  // carry the judged shape and keep their original layout. TierScore
  // expects 0-100, so both generations scale up to it.
  const isScored = verdict?.scoring != null;
  const score = isScored
    ? verdict?.final_score_rounded != null
      ? verdict.final_score_rounded * 10
      : null
    : verdict?.confidence != null
      ? verdict.confidence * 100
      : null;

  return (
    <AltCard testId="alt-tier2">
      <TierHeader
        section={section}
        notes={section.warnings}
        score={score}
        scoreHelpKey={isScored ? 'tiered.help.debateScore' : 'tiered.help.judgeScore'}
      />

      {section.narrative ? (
        <p className="mb-4 text-sm leading-relaxed">{section.narrative}</p>
      ) : null}

      {verdict ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <AltDebateColumn
            labelKey={isScored ? 'tiered.debate.bullCase' : 'tiered.debate.reasonsFor'}
            color="text-emerald-300"
            reasons={verdict.reasons_for ?? []}
            summary={isScored ? (verdict.bull_summary ?? null) : null}
            citations={citations}
          />
          <AltDebateColumn
            labelKey={isScored ? 'tiered.debate.bearCase' : 'tiered.debate.reasonsAgainst'}
            color="text-red-300"
            reasons={verdict.reasons_against ?? []}
            summary={isScored ? (verdict.bear_summary ?? null) : null}
            citations={citations}
          />
        </div>
      ) : (
        <p className="text-sm text-amber-300">{t('tiered.debate.noVerdict')}</p>
      )}

      {verdict?.would_change_mind ? (
        <div className="mt-4">
          <AltSectionLabel>
            <HelpTerm
              label={t('tiered.debate.wouldChangeMind')}
              helpKey="tiered.help.wouldChangeMind"
            />
          </AltSectionLabel>
          <p className="text-xs">{verdict.would_change_mind}</p>
        </div>
      ) : null}

      {detail && detail.turns.length > 0 ? (
        <AltFold title={t('tiered.debate.transcript')}>
          {detail.turns.map((turn, index) => {
            // v4 turns carry a kind (argument/attack/response); older runs
            // numbered their rounds instead.
            const kindKey = turn.kind ? TURN_KIND_KEYS[turn.kind] : undefined;
            const positionScore = turn.position_score ?? turn.bullishness;
            return (
            <div key={index}>
              <div className="mb-0.5 text-xs font-semibold text-gray-300">
                {t((turn.role === 'bull' ? 'tiered.debate.bull' : 'tiered.debate.bear') as UiTextKey)}{' '}
                <span className="font-normal text-gray-500">
                  {kindKey
                    ? t(kindKey)
                    : (turn.kind ?? t('tiered.debate.round', { round: turn.round ?? 1 }))}
                  {positionScore != null ? (
                    <>
                      {' · '}
                      {t('tiered.debate.positionScore')}{' '}
                      <span className="tabular-nums">{positionScore}/10</span>
                    </>
                  ) : null}
                </span>
              </div>
              <p className="whitespace-pre-wrap text-xs leading-relaxed">{turn.argument}</p>
              {turn.citations && turn.citations.length > 0 ? (
                <span className="mt-0.5 block">
                  <AltEvidenceRefs refs={turn.citations} citations={citations} />
                </span>
              ) : null}
            </div>
            );
          })}
        </AltFold>
      ) : null}

      {verdict && isScored ? <AltDebateScoring verdict={verdict} /> : null}
    </AltCard>
  );
};

const PERSONA_LABEL_KEYS: Record<string, UiTextKey> = {
  conservative: 'tiered.risk.persona.conservative',
  aggressive: 'tiered.risk.persona.aggressive',
  neutral: 'tiered.risk.persona.neutral',
};

const AltRisk = ({ section, citations }: AltTierSectionProps) => {
  const { t } = useUiLanguage();
  const detail = section.risk_detail;
  const verdict = detail?.verdict ?? null;

  // Format-2 runs carry the risk vote: same transcript treatment as the
  // tier-2 evidence vote. The stance is tier 2's own (already in the
  // header) and the levels stand, so the header facts are just the
  // verdict and the code-derived size multiplier — no score, no stop.
  if (detail?.format === 2 && Array.isArray(detail.items)) {
    return (
      <AltCard testId="alt-tier3">
        <TierHeader
          section={section}
          notes={section.warnings}
          side={
            verdict ? (
              <AltFact label={t('tiered.alt.size')} helpKey="tiered.help.multiplier">
                {/* id: the shares-computation formula links its multiplier here */}
                <span id="alt-risk-multiplier" className="tabular-nums">
                  {verdict.size_multiplier}x
                </span>
              </AltFact>
            ) : null
          }
        />
        {!verdict ? (
          <p className="mb-4 text-sm text-amber-300">{t('tiered.risk.noVerdict')}</p>
        ) : null}
        {section.narrative ? (
          <p className="mb-2 text-sm leading-relaxed">{section.narrative}</p>
        ) : null}
        <AltRiskTree detail={detail} />
      </AltCard>
    );
  }

  return (
    <AltCard testId="alt-tier3">
      <TierHeader
        section={section}
        notes={section.warnings}
        score={verdict?.confidence != null ? verdict.confidence * 100 : null}
        scoreHelpKey="tiered.help.riskScore"
        side={
          verdict ? (
            <>
              <AltFact label={t('tiered.alt.size')} helpKey="tiered.help.multiplier">
                {/* id: the shares-computation formula links its multiplier here */}
                <span id="alt-risk-multiplier" className="tabular-nums">
                  {verdict.size_multiplier}x
                </span>
              </AltFact>
              <AltFact label={t('tiered.levels.stopLoss')} helpKey="tiered.help.stopAdvice">
                {verdict.tightened_stop !== null ? (
                  // id: when the stop was tightened, this is the number the
                  // shares-computation formula actually used — it links here.
                  <span id="alt-tightened-stop" className="tabular-nums">
                    {formatPrice(verdict.tightened_stop)}
                  </span>
                ) : (
                  t('tiered.risk.stopAdvice.keep')
                )}
              </AltFact>
            </>
          ) : null
        }
      />

      {!verdict ? <p className="mb-4 text-sm text-amber-300">{t('tiered.risk.noVerdict')}</p> : null}

      {section.narrative ? (
        <p className="mb-4 text-sm leading-relaxed">{section.narrative}</p>
      ) : null}

      {verdict && verdict.key_risks.length > 0 ? (
        <div>
          <AltSectionLabel>{t('tiered.risk.keyRisks')}</AltSectionLabel>
          <ul className="flex flex-col gap-2">
            {verdict.key_risks.map((risk, index) => (
              <li key={index} className="text-xs">
                {risk.claim}
                {risk.evidence.length > 0 ? (
                  <span className="mt-0.5 block">
                    <AltEvidenceRefs refs={risk.evidence} citations={citations} />
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {detail && detail.takes.length > 0 ? (
        <AltFold title={t('tiered.debate.transcript')}>
          {detail.takes.map((take, index) => (
            <div key={index}>
              <div className="mb-0.5 text-xs font-semibold text-gray-300">
                {PERSONA_LABEL_KEYS[take.persona] ? t(PERSONA_LABEL_KEYS[take.persona]) : take.persona}
              </div>
              <p className="whitespace-pre-wrap text-xs leading-relaxed">{take.assessment}</p>
            </div>
          ))}
        </AltFold>
      ) : null}
    </AltCard>
  );
};

// ---------- the whole result ----------

interface AltResultProps {
  result: TieredResult;
  /** The run's task id — lets formula numbers link back to the run row. */
  taskId?: string;
  /** When the run happened — drives the previous-day staleness note. */
  runDate?: Date | null;
}

// The same fixed skeleton at every depth, each block titled above its
// card: the four dimension reports (the raw material) → tier 1 → tier 2 →
// tier 3 → the shares computation, so the reading order matches the order
// things actually happened in.
export const AltResult = ({ result, taskId, runDate }: AltResultProps) => {
  const { t } = useUiLanguage();
  const citations = sentimentCitations(result.dimensions);
  const usage = result.llm_usage ?? null;

  // Where the sizing formula's entry / stop-loss numbers already appear:
  // the levels table's adjusted cell when the AI moved the level, its
  // computed cell otherwise — except a tier-3 tightened stop, which is the
  // number next to the tier-3 stop advice.
  const levelTargetId = (key: 'entry' | 'stop_loss'): string | null => {
    const detail = result.levels_detail?.levels?.[key];
    if (!detail || detail.base === null) {
      return null;
    }
    return detail.adjusted !== null ? adjustedCellId(key) : computedCellId(key);
  };
  const tightenedStop = result.tier3?.risk_detail?.verdict?.tightened_stop ?? null;
  const entryTargetId = levelTargetId('entry');
  const stopTargetId = tightenedStop !== null ? 'alt-tightened-stop' : levelTargetId('stop_loss');

  return (
    <div className="flex flex-col gap-6">
      {result.outlook ? (
        // Outlook-redesign runs lead with the bottom line; old stored
        // runs never carried it and keep their legacy layout.
        <AltBlock title={t('tiered.alt.conclusionTitle')} helpKey="tiered.help.outlook">
          <AltConclusion result={result} runDate={runDate} />
        </AltBlock>
      ) : null}
      <AltBlock title={t('tiered.alt.dimensionsTitle')}>
        <AltDimensions dimensions={result.dimensions} />
      </AltBlock>
      {result.tier2 && result.outlook ? (
        // Deep-analysis (depth 2) runs skip the tier-1 verdict, so no
        // tier-1 card at all — just the formula plan in its place. Old
        // stored depth-2 runs (no outlook) had a real tier-1 verdict and
        // keep their card.
        <AltBlock title={t('tiered.alt.planTitle')} helpKey="tiered.help.plan">
          <AltPlanCard result={result} citations={citations} action={result.action} />
        </AltBlock>
      ) : (
        <AltBlock title={t('tiered.alt.tier1Title')} helpKey="tiered.help.tier1">
          <AltTierOne result={result} citations={citations} action={result.action} />
        </AltBlock>
      )}
      {result.tier2 ? (
        <AltBlock title={t('tiered.alt.tier2Title')} helpKey="tiered.help.debate">
          <AltDebate section={result.tier2} citations={citations} />
        </AltBlock>
      ) : null}
      {result.tier3 ? (
        <AltBlock title={t('tiered.alt.tier3Title')} helpKey="tiered.help.risk">
          <AltRisk section={result.tier3} citations={citations} />
        </AltBlock>
      ) : null}
      {result.sizing ? (
        <AltBlock title={t('tiered.alt.sharesTitle')} helpKey="tiered.help.sizing">
          <AltSharesComputation
            sizing={result.sizing}
            taskId={taskId}
            entryTargetId={entryTargetId}
            stopTargetId={stopTargetId}
          />
        </AltBlock>
      ) : null}
      {result.risk_card && result.risk_card.length > 0 ? (
        <AltBlock title={t('tiered.alt.riskCardTitle')} helpKey="tiered.help.riskCard">
          <AltRiskCard entries={result.risk_card} />
        </AltBlock>
      ) : null}
      <div className="flex flex-col gap-1 text-xs">
        {result.signal?.logged && result.signal.signal_id != null ? (
          <p>
            <Link
              to={`/decision-signals?signal=${result.signal.signal_id}`}
              className={ALT_LINK}
            >
              {t('tiered.alt.signalSaved', { id: result.signal.signal_id })}
            </Link>
          </p>
        ) : result.signal?.logged ? (
          <p className="text-emerald-300">{t('tiered.alt.signalSaved', { id: '—' })}</p>
        ) : result.signal ? (
          <p className="text-amber-300">
            {t('tiered.signalSkipped', { reason: result.signal.reason ?? '' })}
          </p>
        ) : null}
        {usage && usage.total.calls > 0 ? (
          <p className="text-gray-600">
            <HelpTerm
              underline={false}
              label={t('tiered.llmUsage', {
                calls: usage.total.calls,
                tokens: usage.total.prompt_tokens + usage.total.completion_tokens,
              })}
              helpKey="tiered.help.llmUsage"
            />
          </p>
        ) : null}
      </div>
    </div>
  );
};
