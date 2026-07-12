import type { TieredCitation, TieredTierSection } from '../../api/tiered';
import { Badge, Card, Collapsible } from '../common';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { COVERAGE_BADGE, DIRECTION_BADGE, formatPrice } from './termHelpers';
import { EvidenceRefList, HelpTerm } from './terms';

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

interface RiskCardProps {
  section: TieredTierSection;
  citations: TieredCitation[];
}

// Tier 3: three AI risk reviewers (cautious / bold / balanced) poke at the
// debate verdict; a risk judge merges them into a final stance, a position
// size multiplier, and stop-loss advice. The multiplier is applied by
// code in the sizing card — this card explains the ruling.
export const RiskCard = ({ section, citations }: RiskCardProps) => {
  const { t } = useUiLanguage();
  const detail = section.risk_detail;
  const verdict = detail?.verdict ?? null;

  return (
    <Card className="p-4" data-testid="risk-card">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-foreground">
          <HelpTerm label={t('tiered.risk.title')} helpKey="tiered.help.risk" />
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
      </div>

      {verdict ? (
        <div className="mb-3 flex flex-wrap gap-2 text-xs">
          <span className="rounded-lg border border-border/50 bg-elevated/60 px-2 py-1">
            <HelpTerm label={t('tiered.risk.multiplier')} helpKey="tiered.help.multiplier" />
            {': '}
            <span className="font-mono text-foreground">{verdict.size_multiplier}×</span>{' '}
            <span className="text-secondary-text">
              ({t(multiplierLabelKey(verdict.size_multiplier))})
            </span>
          </span>
          <span className="rounded-lg border border-border/50 bg-elevated/60 px-2 py-1">
            <HelpTerm label={t('tiered.risk.stopAdvice')} helpKey="tiered.help.stopAdvice" />
            {': '}
            <span className="text-foreground">
              {t(
                (verdict.stop_advice === 'tighten'
                  ? 'tiered.risk.stopAdvice.tighten'
                  : 'tiered.risk.stopAdvice.keep') as UiTextKey,
              )}
            </span>
            {verdict.tightened_stop !== null ? (
              <span className="ml-1 font-mono text-foreground">
                → {formatPrice(verdict.tightened_stop)}
              </span>
            ) : null}
          </span>
        </div>
      ) : (
        <p className="mb-3 text-sm text-warning">{t('tiered.risk.noVerdict')}</p>
      )}

      {section.narrative ? (
        <p className="mb-3 text-sm leading-relaxed text-secondary-text">{section.narrative}</p>
      ) : null}

      {verdict && verdict.key_risks.length > 0 ? (
        <div>
          <div className="label-uppercase mb-1">{t('tiered.risk.keyRisks')}</div>
          <ul className="space-y-2">
            {verdict.key_risks.map((risk, index) => (
              <li key={index} className="text-xs text-secondary-text">
                {risk.claim}
                {risk.evidence.length > 0 ? (
                  <span className="mt-0.5 block">
                    <EvidenceRefList refs={risk.evidence} citations={citations} />
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {detail && detail.takes.length > 0 ? (
        <div className="mt-3">
          <Collapsible title={t('tiered.risk.personas')}>
            <div className="space-y-3 px-4 pb-4">
              {detail.takes.map((take, index) => (
                <div key={index}>
                  <div className="mb-0.5 text-xs font-semibold text-foreground">
                    {PERSONA_LABEL_KEYS[take.persona]
                      ? t(PERSONA_LABEL_KEYS[take.persona])
                      : take.persona}
                  </div>
                  <p className="whitespace-pre-wrap text-xs leading-relaxed text-secondary-text">
                    {take.assessment}
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
