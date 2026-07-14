import { type ComponentProps, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import type {
  TieredCitation,
  TieredResult,
  TieredSizing,
  TieredTierSection,
} from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { cn } from '../../utils/cn';
import { flashElement, formatPrice, sentimentCitations } from '../tiered/termHelpers';
import { HelpTerm as BaseHelpTerm } from '../tiered/terms';
import { plainNumber, riskPctText } from './altFormat';
import { ALT_LINK, DIRECTION_TAG } from './altStyles';
import { AltCard, AltEvidenceRefs, AltNotesButton, AltTag } from './AltUi';
import { AltDimensions } from './AltDimensions';
import { AltLevels } from './AltLevels';

// ---------- small shared pieces ----------

// Alt skin rule: help popups everywhere, dotted underlines nowhere.
const HelpTerm = (props: ComponentProps<typeof BaseHelpTerm>) => (
  <BaseHelpTerm underline={false} {...props} />
);

const AltSectionLabel = ({ children }: { children: ReactNode }) => (
  <div className="mb-1 text-xs font-semibold text-gray-500">{children}</div>
);

const AltFold = ({ title, children }: { title: string; children: ReactNode }) => (
  <details className="mt-4 rounded bg-gray-900/60 px-4 py-3">
    <summary className="cursor-pointer text-xs font-semibold text-gray-300">{title}</summary>
    <div className="mt-3 flex flex-col gap-3">{children}</div>
  </details>
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
}

// Just the arithmetic, three lines: the formula in words, the same formula
// with this run's numbers (each number links to where it came from), and
// the share count it produces. Runs where no count could be computed show
// the refusal reason instead.
const AltSharesComputation = ({ sizing, taskId }: AltSharesComputationProps) => {
  const { t } = useUiLanguage();

  const capital = sizing.inputs.capital;
  const riskFraction = sizing.inputs.risk_fraction;
  const lossPerShare = sizing.loss_per_share;
  const multiplier = sizing.risk_multiplier;

  if (sizing.shares === null || capital === null || riskFraction === null || lossPerShare === null) {
    const reasonKey = sizing.reason_code ? REASON_KEYS[sizing.reason_code] : undefined;
    return (
      <AltCard testId="alt-shares-computation">
        <p className="text-sm text-amber-300">
          {reasonKey ? t(reasonKey) : (sizing.refusal_reason ?? t('tiered.sizing.notComputed'))}
        </p>
      </AltCard>
    );
  }

  return (
    <AltCard testId="alt-shares-computation">
      <div className="flex flex-col gap-2 text-sm">
        <p className="text-gray-400">
          ({t('tiered.alt.f.capital')}) × ({t('tiered.alt.f.risk')})
          {multiplier !== null ? <> × ({t('tiered.alt.f.multiplier')})</> : null} / (
          {t('tiered.alt.f.loss')})
        </p>
        <p className="text-gray-400" data-testid="alt-shares-formula">
          {'= ('}
          <FormulaLink targetId={taskId ? `alt-run-${taskId}-capital` : null}>
            {plainNumber(capital)}
          </FormulaLink>
          {') × ('}
          <FormulaLink targetId={taskId ? `alt-run-${taskId}-risk` : null}>
            {riskPctText(riskFraction)}%
          </FormulaLink>
          {')'}
          {multiplier !== null ? (
            <>
              {' × ('}
              <FormulaLink targetId="alt-risk-multiplier">{multiplier}</FormulaLink>
              {')'}
            </>
          ) : null}
          {' / ('}
          <FormulaLink targetId="alt-tier1-levels">{formatPrice(lossPerShare)}</FormulaLink>
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

// The unified per-tier "Score" chip: always 0-100, whatever scale the
// backend spoke (tier 1 is already 0-100; the tier-2/3 judges report 0-1).
const TierScore = ({ value, helpKey }: { value: number; helpKey: UiTextKey }) => {
  const { t } = useUiLanguage();
  return (
    <span className="text-xs text-gray-500">
      <HelpTerm label={t('tiered.score')} helpKey={helpKey} />
      {': '}
      <span className="tabular-nums text-gray-300">{Math.round(value)}</span>
    </span>
  );
};

interface TierHeaderProps {
  section: Pick<TieredTierSection, 'direction' | 'coverage'>;
  notes?: string[];
  extra?: ReactNode;
}

// The card's title lives above the card (AltBlock); inside, the header row
// is just the verdict tag, any extra chip, and the data-notes mark pinned
// top-right: nothing when the data was complete, ⚠ when partial, a red X
// when unavailable.
const TierHeader = ({ section, notes, extra }: TierHeaderProps) => {
  const { t } = useUiLanguage();
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      <AltTag tone={DIRECTION_TAG[section.direction]}>
        {t(`tiered.direction.${section.direction}` as UiTextKey)}
      </AltTag>
      {extra}
      <span className="ml-auto">
        <AltNotesButton notes={notes ?? []} coverage={section.coverage} />
      </span>
    </div>
  );
};

interface AltTierOneProps {
  result: TieredResult;
  citations: TieredCitation[];
}

const AltTierOne = ({ result, citations }: AltTierOneProps) => {
  const { t } = useUiLanguage();

  return (
    <AltCard testId="alt-tier1">
      <TierHeader
        section={{ direction: result.direction, coverage: result.coverage }}
        notes={result.warnings}
        extra={
          result.score !== null ? (
            <TierScore value={result.score} helpKey="tiered.help.score" />
          ) : null
        }
      />

      <AltSectionLabel>{t('tiered.levels')}</AltSectionLabel>
      {/* id: the shares-computation formula links its loss-per-share here */}
      <div id="alt-tier1-levels">
        <AltLevels levels={result.levels} levelsDetail={result.levels_detail} citations={citations} />
      </div>
      <p className="mt-2 text-xs text-gray-500">{t('tiered.levelsNote')}</p>
    </AltCard>
  );
};

interface AltTierSectionProps {
  section: TieredTierSection;
  citations: TieredCitation[];
}

const AltDebate = ({ section, citations }: AltTierSectionProps) => {
  const { t } = useUiLanguage();
  const detail = section.debate_detail;
  const verdict = detail?.verdict ?? null;

  return (
    <AltCard testId="alt-tier2">
      <TierHeader
        section={section}
        notes={section.warnings}
        extra={
          verdict?.confidence != null ? (
            <TierScore value={verdict.confidence * 100} helpKey="tiered.help.judgeScore" />
          ) : null
        }
      />

      {section.narrative ? (
        <p className="mb-4 text-sm leading-relaxed">{section.narrative}</p>
      ) : null}

      {verdict ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <div className="mb-1 text-xs font-semibold text-emerald-300">
              {t('tiered.debate.reasonsFor')}
            </div>
            <ul className="flex flex-col gap-2">
              {verdict.reasons_for.map((reason, index) => (
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
          </div>
          <div>
            <div className="mb-1 text-xs font-semibold text-red-300">
              {t('tiered.debate.reasonsAgainst')}
            </div>
            <ul className="flex flex-col gap-2">
              {verdict.reasons_against.map((reason, index) => (
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
          </div>
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
          {detail.turns.map((turn, index) => (
            <div key={index}>
              <div className="mb-0.5 text-xs font-semibold text-gray-300">
                {t((turn.role === 'bull' ? 'tiered.debate.bull' : 'tiered.debate.bear') as UiTextKey)}{' '}
                <span className="font-normal text-gray-500">
                  {t('tiered.debate.round', { round: turn.round })}
                </span>
              </div>
              <p className="whitespace-pre-wrap text-xs leading-relaxed">{turn.argument}</p>
            </div>
          ))}
        </AltFold>
      ) : null}
    </AltCard>
  );
};

const PERSONA_LABEL_KEYS: Record<string, UiTextKey> = {
  conservative: 'tiered.risk.persona.conservative',
  aggressive: 'tiered.risk.persona.aggressive',
  neutral: 'tiered.risk.persona.neutral',
};

function multiplierLabelKey(multiplier: number): UiTextKey {
  if (multiplier === 0) {
    return 'tiered.risk.multiplier.zero';
  }
  if (multiplier === 0.5) {
    return 'tiered.risk.multiplier.half';
  }
  return 'tiered.risk.multiplier.full';
}

const AltRisk = ({ section, citations }: AltTierSectionProps) => {
  const { t } = useUiLanguage();
  const detail = section.risk_detail;
  const verdict = detail?.verdict ?? null;

  return (
    <AltCard testId="alt-tier3">
      <TierHeader
        section={section}
        notes={section.warnings}
        extra={
          verdict?.confidence != null ? (
            <TierScore value={verdict.confidence * 100} helpKey="tiered.help.riskScore" />
          ) : null
        }
      />

      {verdict ? (
        <div className="mb-4 flex flex-wrap gap-x-6 gap-y-2 text-sm">
          <span>
            <HelpTerm label={t('tiered.risk.multiplier')} helpKey="tiered.help.multiplier" />
            {': '}
            {/* id: the shares-computation formula links its multiplier here */}
            <span id="alt-risk-multiplier" className="tabular-nums text-gray-300">
              {verdict.size_multiplier}×
            </span>{' '}
            <span className="text-gray-500">({t(multiplierLabelKey(verdict.size_multiplier))})</span>
          </span>
          <span>
            <HelpTerm label={t('tiered.risk.stopAdvice')} helpKey="tiered.help.stopAdvice" />
            {': '}
            <span className="text-gray-300">
              {t(
                (verdict.stop_advice === 'tighten'
                  ? 'tiered.risk.stopAdvice.tighten'
                  : 'tiered.risk.stopAdvice.keep') as UiTextKey,
              )}
            </span>
            {verdict.tightened_stop !== null ? (
              <span className="ml-1 tabular-nums text-gray-300">
                → {formatPrice(verdict.tightened_stop)}
              </span>
            ) : null}
          </span>
        </div>
      ) : (
        <p className="mb-4 text-sm text-amber-300">{t('tiered.risk.noVerdict')}</p>
      )}

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
        <AltFold title={t('tiered.risk.personas')}>
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
}

// The same fixed skeleton at every depth, each block titled above its
// card: the four dimension reports (the raw material) → tier 1 → tier 2 →
// tier 3 → the shares computation, so the reading order matches the order
// things actually happened in.
export const AltResult = ({ result, taskId }: AltResultProps) => {
  const { t } = useUiLanguage();
  const citations = sentimentCitations(result.dimensions);
  const usage = result.llm_usage ?? null;

  return (
    <div className="flex flex-col gap-6">
      <AltBlock title={t('tiered.alt.dimensionsTitle')}>
        <AltDimensions dimensions={result.dimensions} />
      </AltBlock>
      <AltBlock title={t('tiered.alt.tier1Title')} helpKey="tiered.help.tier1">
        <AltTierOne result={result} citations={citations} />
      </AltBlock>
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
          <AltSharesComputation sizing={result.sizing} taskId={taskId} />
        </AltBlock>
      ) : null}
      <div className="flex flex-col gap-1 text-xs">
        {result.signal?.logged ? (
          <p className="flex flex-wrap items-center gap-x-3">
            <span className="text-emerald-300">
              {t('tiered.signalSaved', { id: result.signal.signal_id ?? '—' })}
            </span>
            <Link to="/decision-signals" className={ALT_LINK}>
              {t('tiered.viewSignals')}
            </Link>
          </p>
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
