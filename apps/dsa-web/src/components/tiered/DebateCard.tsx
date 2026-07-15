import type { TieredCitation, TieredTierSection } from '../../api/tiered';
import { Badge, Card, Collapsible } from '../common';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { COVERAGE_BADGE, DIRECTION_BADGE } from './termHelpers';
import { EvidenceRefList, HelpTerm } from './terms';

interface DebateCardProps {
  section: TieredTierSection;
  citations: TieredCitation[];
}

// Tier 2: one AI argues for the stock, one argues against, a judge rules.
// Shows the ruling first (direction + confidence + summary), the anchored
// reasons on both sides, and the full transcript folded away.
export const DebateCard = ({ section, citations }: DebateCardProps) => {
  const { t } = useUiLanguage();
  const detail = section.debate_detail;
  const verdict = detail?.verdict ?? null;

  return (
    <Card className="p-4" data-testid="debate-card">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-foreground">
          <HelpTerm label={t('tiered.debate.title')} helpKey="tiered.help.debate" />
        </h3>
        <HelpTerm
          underline={false}
          helpKey="tiered.help.coverage"
          label={
            <Badge variant={COVERAGE_BADGE[section.coverage]}>
              {t(`tiered.coverage.${section.coverage}` as UiTextKey)}
            </Badge>
          }
        />
        <Badge variant={DIRECTION_BADGE[section.direction]} size="md" glow>
          {t(`tiered.direction.${section.direction}` as UiTextKey)}
        </Badge>
        {section.confidence ? (
          <span className="text-xs text-secondary-text">
            <HelpTerm label={t('tiered.debate.confidence')} helpKey="tiered.help.debateConfidence" />
            : <span className="font-mono text-foreground">{section.confidence}</span>
          </span>
        ) : null}
      </div>

      {section.narrative ? (
        <p className="mb-3 text-sm leading-relaxed text-secondary-text">{section.narrative}</p>
      ) : null}

      {verdict ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div>
            <div className="label-uppercase mb-1 text-success">{t('tiered.debate.reasonsFor')}</div>
            <ul className="space-y-2">
              {(verdict.reasons_for ?? []).map((reason, index) => (
                <li key={index} className="text-xs text-secondary-text">
                  {reason.claim}
                  {reason.evidence.length > 0 ? (
                    <span className="mt-0.5 block">
                      <EvidenceRefList refs={reason.evidence} citations={citations} />
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <div className="label-uppercase mb-1 text-danger">
              {t('tiered.debate.reasonsAgainst')}
            </div>
            <ul className="space-y-2">
              {(verdict.reasons_against ?? []).map((reason, index) => (
                <li key={index} className="text-xs text-secondary-text">
                  {reason.claim}
                  {reason.evidence.length > 0 ? (
                    <span className="mt-0.5 block">
                      <EvidenceRefList refs={reason.evidence} citations={citations} />
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        </div>
      ) : (
        <p className="text-sm text-warning">{t('tiered.debate.noVerdict')}</p>
      )}

      {verdict?.would_change_mind ? (
        <div className="mt-3">
          <div className="label-uppercase mb-1">
            <HelpTerm
              label={t('tiered.debate.wouldChangeMind')}
              helpKey="tiered.help.wouldChangeMind"
            />
          </div>
          <p className="text-xs text-secondary-text">{verdict.would_change_mind}</p>
        </div>
      ) : null}

      {detail && detail.turns.length > 0 ? (
        <div className="mt-3">
          <Collapsible title={t('tiered.debate.transcript')}>
            <div className="space-y-3 px-4 pb-4">
              {detail.turns.map((turn, index) => (
                <div key={index}>
                  <div className="mb-0.5 text-xs font-semibold text-foreground">
                    {t(
                      (turn.role === 'bull'
                        ? 'tiered.debate.bull'
                        : 'tiered.debate.bear') as UiTextKey,
                    )}{' '}
                    <span className="font-normal text-secondary-text">
                      {t('tiered.debate.round', { round: turn.round })}
                    </span>
                  </div>
                  <p className="whitespace-pre-wrap text-xs leading-relaxed text-secondary-text">
                    {turn.argument}
                  </p>
                </div>
              ))}
            </div>
          </Collapsible>
        </div>
      ) : null}

      {section.warnings.length > 0 ? (
        <div className="mt-3">
          <div className="label-uppercase mb-1">{t('tiered.dataNotes')}</div>
          <ul className="space-y-1">
            {section.warnings.map((warning, index) => (
              <li key={index} className="text-xs text-warning">
                {warning}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </Card>
  );
};
