import { Fragment, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import type {
  TieredCitation,
  TieredResult,
  TieredSizing,
  TieredTierSection,
} from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { formatPrice, sentimentCitations } from '../tiered/termHelpers';
import { HelpTerm } from '../tiered/terms';
import { ALT_LINK, COVERAGE_TAG, DIRECTION_TAG } from './altStyles';
import { AltCard, AltEvidenceRefs, AltTag } from './AltUi';
import { AltDimensions } from './AltDimensions';
import { AltLevels } from './AltLevels';

// ---------- small shared pieces ----------

const AltSectionLabel = ({ children }: { children: ReactNode }) => (
  <div className="mb-1 text-xs font-semibold text-gray-500">{children}</div>
);

const AltWarnings = ({ warnings }: { warnings: string[] }) => {
  const { t } = useUiLanguage();
  if (warnings.length === 0) {
    return null;
  }
  return (
    <div className="mt-4">
      <AltSectionLabel>{t('tiered.dataNotes')}</AltSectionLabel>
      <ul className="flex flex-col gap-1">
        {warnings.map((warning, index) => (
          <li key={index} className="text-xs text-amber-300">
            {warning}
          </li>
        ))}
      </ul>
    </div>
  );
};

const AltFold = ({ title, children }: { title: string; children: ReactNode }) => (
  <details className="mt-4 rounded bg-gray-900/60 px-4 py-3">
    <summary className="cursor-pointer text-xs font-semibold text-gray-300">{title}</summary>
    <div className="mt-3 flex flex-col gap-3">{children}</div>
  </details>
);

// ---------- final verdict (hero, not a card) ----------

interface AltFinalVerdictProps {
  result: TieredResult;
}

const AltFinalVerdict = ({ result }: AltFinalVerdictProps) => {
  const { t } = useUiLanguage();
  const final = result.final ?? {
    tier: 1,
    direction: result.direction,
    coverage: result.coverage,
    confidence: null,
    levels: result.levels,
  };

  const trail: { tier: number; direction: TieredResult['direction'] }[] = [
    { tier: 1, direction: result.direction },
  ];
  if (result.tier2) {
    trail.push({ tier: 2, direction: result.tier2.direction });
  }
  if (result.tier3) {
    trail.push({ tier: 3, direction: result.tier3.direction });
  }

  return (
    <header data-testid="alt-final-verdict">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-3xl font-bold text-gray-300">{result.symbol}</h2>
        <HelpTerm
          underline={false}
          helpKey="tiered.help.finalVerdict"
          label={
            <span
              className={`inline-flex items-center rounded px-3 py-1 text-sm font-semibold ring-1 ring-inset ${DIRECTION_TAG[final.direction]}`}
            >
              {t(`tiered.direction.${final.direction}` as UiTextKey)}
            </span>
          }
        />
      </div>
      <p className="mt-1 text-xs text-gray-500">
        {final.tier === 1
          ? t('tiered.final.decidedBy1')
          : t('tiered.final.decidedBy', { tier: final.tier })}
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 text-xs">
        <span className="text-gray-500">
          <HelpTerm label={t('tiered.final.trail')} helpKey="tiered.help.finalTrail" />:
        </span>
        {trail.map((step, index) => (
          <Fragment key={step.tier}>
            {index > 0 ? <span className="text-gray-600">→</span> : null}
            <span className="flex items-center gap-1.5">
              <span className="text-gray-500">{t(`tiered.trail.${step.tier}` as UiTextKey)}</span>
              <AltTag tone={DIRECTION_TAG[step.direction]}>
                {t(`tiered.direction.${step.direction}` as UiTextKey)}
              </AltTag>
            </span>
          </Fragment>
        ))}
      </div>
    </header>
  );
};

// ---------- suggested order size ----------

const REASON_KEYS: Record<string, UiTextKey> = {
  sizing_off: 'tiered.sizing.reason.sizing_off',
  not_a_buy: 'tiered.sizing.reason.not_a_buy',
  no_entry: 'tiered.sizing.reason.no_entry',
  no_stop: 'tiered.sizing.reason.no_stop',
  stop_not_below_entry: 'tiered.sizing.reason.stop_not_below_entry',
  invalid_input: 'tiered.sizing.reason.invalid_input',
  too_small: 'tiered.sizing.reason.too_small',
};

interface AltOrderSizeProps {
  sizing: TieredSizing | null;
}

// Always rendered, whatever the depth or verdict: the share count is either
// a number, 0, or a dash with the reason — never silently absent.
const AltOrderSize = ({ sizing }: AltOrderSizeProps) => {
  const { t } = useUiLanguage();
  const isSized = sizing !== null && sizing.shares !== null;
  const isOff = sizing?.reason_code === 'sizing_off';
  const reasonKey = sizing?.reason_code ? REASON_KEYS[sizing.reason_code] : undefined;

  return (
    <AltCard testId="alt-order-size">
      <h3 className="font-semibold text-gray-300">
        <HelpTerm label={t('tiered.sizing.title')} helpKey="tiered.help.sizing" />
      </h3>
      <p className="mt-1 text-xs leading-relaxed text-gray-500">{t('tiered.sizing.subtitle')}</p>

      <div className="mt-4 flex items-baseline gap-2" data-testid="alt-order-size-shares">
        <span className="text-4xl font-bold tabular-nums text-gray-300">
          {isSized ? sizing.shares : '—'}
        </span>
        <span className="text-xs text-gray-500">
          <HelpTerm label={t('tiered.sizing.shares')} helpKey="tiered.help.shares" />
        </span>
      </div>

      {sizing === null ? (
        <p className="mt-3 text-sm">{t('tiered.sizing.notComputed')}</p>
      ) : isOff ? (
        <div className="mt-3 flex flex-col gap-2 text-sm">
          <p>{t('tiered.sizing.offExplainer')}</p>
          <p className="text-xs text-gray-500">{t('tiered.sizing.offHint')}</p>
        </div>
      ) : isSized ? (
        <div className="mt-3 flex flex-col gap-2">
          <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
            <span>
              <HelpTerm label={t('tiered.sizing.positionValue')} helpKey="tiered.help.positionValue" />
              {': '}
              <span className="tabular-nums text-gray-300">{formatPrice(sizing.position_value)}</span>
            </span>
            <span>
              <HelpTerm label={t('tiered.sizing.riskAmount')} helpKey="tiered.help.riskAmount" />
              {': '}
              <span className="tabular-nums text-gray-300">{formatPrice(sizing.risk_amount)}</span>
            </span>
            <span>
              <HelpTerm label={t('tiered.sizing.stopUsed')} helpKey="tiered.help.stopUsed" />
              {': '}
              <span className="tabular-nums text-gray-300">
                {formatPrice(sizing.inputs.stop_loss)}
              </span>
            </span>
          </div>
          {sizing.risk_multiplier !== null && sizing.shares_before_multiplier !== null ? (
            <p className="text-xs text-gray-500">
              {t('tiered.sizing.multiplierApplied', {
                before: sizing.shares_before_multiplier,
                multiplier: sizing.risk_multiplier,
                after: sizing.shares ?? 0,
              })}
            </p>
          ) : null}
          {sizing.shares === 0 ? (
            <p className="text-sm font-semibold text-amber-300">{t('tiered.sizing.zeroShares')}</p>
          ) : null}
          {sizing.cap_applied ? (
            <p className="text-xs text-gray-500">{t('tiered.sizing.capApplied')}</p>
          ) : null}
          <p className="text-xs text-gray-500">
            {t('tiered.sizing.inputsLine', {
              capital: formatPrice(sizing.inputs.capital),
              riskPct:
                sizing.inputs.risk_fraction !== null
                  ? (sizing.inputs.risk_fraction * 100).toFixed(1)
                  : '—',
              entry: formatPrice(sizing.inputs.entry),
            })}
          </p>
        </div>
      ) : (
        <div className="mt-3 flex flex-col gap-1">
          <p className="text-sm text-amber-300">
            {reasonKey ? t(reasonKey) : sizing.refusal_reason}
          </p>
          {reasonKey && sizing.refusal_reason ? (
            <p className="text-xs text-gray-500">{sizing.refusal_reason}</p>
          ) : null}
        </div>
      )}

      {sizing && sizing.notes.length > 0 ? (
        <ul className="mt-3 flex flex-col gap-1">
          {sizing.notes.map((note, index) => (
            <li key={index} className="text-xs text-gray-500">
              {note}
            </li>
          ))}
        </ul>
      ) : null}
    </AltCard>
  );
};

// ---------- tier cards ----------

interface TierHeaderProps {
  titleKey: UiTextKey;
  helpKey: UiTextKey;
  section: Pick<TieredTierSection, 'direction' | 'coverage'>;
  extra?: ReactNode;
}

const TierHeader = ({ titleKey, helpKey, section, extra }: TierHeaderProps) => {
  const { t } = useUiLanguage();
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      <h3 className="font-semibold text-gray-300">
        <HelpTerm label={t(titleKey)} helpKey={helpKey} />
      </h3>
      <AltTag tone={DIRECTION_TAG[section.direction]}>
        {t(`tiered.direction.${section.direction}` as UiTextKey)}
      </AltTag>
      <HelpTerm
        underline={false}
        helpKey="tiered.help.coverage"
        label={
          <AltTag tone={COVERAGE_TAG[section.coverage]}>
            {t(`tiered.coverage.${section.coverage}` as UiTextKey)}
          </AltTag>
        }
      />
      {extra}
    </div>
  );
};

interface AltTierOneProps {
  result: TieredResult;
  citations: TieredCitation[];
}

const AltTierOne = ({ result, citations }: AltTierOneProps) => {
  const { t } = useUiLanguage();
  const usage = result.llm_usage ?? null;

  return (
    <AltCard testId="alt-tier1">
      <TierHeader
        titleKey="tiered.tier1.title"
        helpKey="tiered.help.tier1"
        section={{ direction: result.direction, coverage: result.coverage }}
        extra={
          result.score !== null ? (
            <span className="text-xs text-gray-500">
              <HelpTerm label={t('tiered.score')} helpKey="tiered.help.score" />
              {': '}
              <span className="tabular-nums text-gray-300">{result.score}</span>
            </span>
          ) : null
        }
      />

      {result.narrative ? (
        <p className="mb-4 text-sm leading-relaxed">{result.narrative}</p>
      ) : null}

      <AltSectionLabel>{t('tiered.levels')}</AltSectionLabel>
      <AltLevels levels={result.levels} levelsDetail={result.levels_detail} citations={citations} />
      <p className="mt-2 text-xs text-gray-500">{t('tiered.levelsNote')}</p>

      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
        {result.signal?.logged ? (
          <>
            <span className="text-emerald-300">
              {t('tiered.signalSaved', { id: result.signal.signal_id ?? '—' })}
            </span>
            <Link to="/decision-signals" className={ALT_LINK}>
              {t('tiered.viewSignals')}
            </Link>
          </>
        ) : result.signal ? (
          <span className="text-amber-300">
            {t('tiered.signalSkipped', { reason: result.signal.reason ?? '' })}
          </span>
        ) : null}
        {usage && usage.total.calls > 0 ? (
          <span className="text-gray-500">
            <HelpTerm
              label={t('tiered.llmUsage', {
                calls: usage.total.calls,
                tokens: usage.total.prompt_tokens + usage.total.completion_tokens,
              })}
              helpKey="tiered.help.llmUsage"
            />
          </span>
        ) : null}
      </div>

      <AltWarnings warnings={result.warnings} />
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
        titleKey="tiered.debate.title"
        helpKey="tiered.help.debate"
        section={section}
        extra={
          section.confidence ? (
            <span className="text-xs text-gray-500">
              <HelpTerm label={t('tiered.debate.confidence')} helpKey="tiered.help.debateConfidence" />
              {': '}
              <span className="tabular-nums text-gray-300">{section.confidence}</span>
            </span>
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

      <AltWarnings warnings={section.warnings} />
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
      <TierHeader titleKey="tiered.risk.title" helpKey="tiered.help.risk" section={section} />

      {verdict ? (
        <div className="mb-4 flex flex-wrap gap-x-6 gap-y-2 text-sm">
          <span>
            <HelpTerm label={t('tiered.risk.multiplier')} helpKey="tiered.help.multiplier" />
            {': '}
            <span className="tabular-nums text-gray-300">{verdict.size_multiplier}×</span>{' '}
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

      <AltWarnings warnings={section.warnings} />
    </AltCard>
  );
};

// ---------- the whole result ----------

interface AltResultProps {
  result: TieredResult;
}

// The same fixed skeleton at every depth: final verdict → order size →
// tier 1 → tier 2 → tier 3 → the four dimension cards.
export const AltResult = ({ result }: AltResultProps) => {
  const citations = sentimentCitations(result.dimensions);

  return (
    <div className="flex flex-col gap-6">
      <AltFinalVerdict result={result} />
      <AltOrderSize sizing={result.sizing ?? null} />
      <AltTierOne result={result} citations={citations} />
      {result.tier2 ? <AltDebate section={result.tier2} citations={citations} /> : null}
      {result.tier3 ? <AltRisk section={result.tier3} citations={citations} /> : null}
      <AltDimensions dimensions={result.dimensions} />
    </div>
  );
};
