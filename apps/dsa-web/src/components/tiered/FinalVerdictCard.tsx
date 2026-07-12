import { Fragment } from 'react';
import type { TieredFinal, TieredResult, TieredTierSection } from '../../api/tiered';
import { Badge, Card } from '../common';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { DIRECTION_BADGE } from './termHelpers';
import { HelpTerm } from './terms';

interface FinalVerdictCardProps {
  symbol: string;
  final: TieredFinal;
  tier1Direction: TieredResult['direction'];
  tier2: TieredTierSection | null;
  tier3: TieredTierSection | null;
}

// The one call the run ends on, in its own card — separate from the tier-1
// analysis below it. The trail shows how each tier's review moved (or kept)
// the direction, so "final" is never confused with "tier 1".
export const FinalVerdictCard = ({
  symbol,
  final,
  tier1Direction,
  tier2,
  tier3,
}: FinalVerdictCardProps) => {
  const { t } = useUiLanguage();

  const trail: { tier: number; direction: TieredResult['direction'] }[] = [
    { tier: 1, direction: tier1Direction },
  ];
  if (tier2) {
    trail.push({ tier: 2, direction: tier2.direction });
  }
  if (tier3) {
    trail.push({ tier: 3, direction: tier3.direction });
  }

  return (
    <Card className="p-4">
      {/* testid sits on an inner div — the shared Card does not forward extra props */}
      <div data-testid="final-verdict-card">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-semibold text-foreground">{symbol}</h2>
        <span className="label-uppercase">
          <HelpTerm label={t('tiered.final.title')} helpKey="tiered.help.finalVerdict" />
        </span>
        <Badge variant={DIRECTION_BADGE[final.direction]} size="md" glow>
          {t(`tiered.direction.${final.direction}` as UiTextKey)}
        </Badge>
        <span className="text-xs text-secondary-text">
          {t('tiered.final.decidedBy', { tier: final.tier })}
        </span>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 text-xs">
        <span className="text-secondary-text">
          <HelpTerm label={t('tiered.final.trail')} helpKey="tiered.help.finalTrail" />:
        </span>
        {trail.map((step, index) => (
          <Fragment key={step.tier}>
            {index > 0 ? <span className="text-secondary-text">→</span> : null}
            <span className="flex items-center gap-1.5">
              <span className="text-secondary-text">
                {t(`tiered.trail.${step.tier}` as UiTextKey)}
              </span>
              <Badge variant={DIRECTION_BADGE[step.direction]}>
                {t(`tiered.direction.${step.direction}` as UiTextKey)}
              </Badge>
            </span>
          </Fragment>
        ))}
      </div>
      </div>
    </Card>
  );
};
