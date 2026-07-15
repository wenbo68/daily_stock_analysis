import type { TieredDebateDetail, TieredDebaterScore } from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { FORMULA_LINE, FORMULA_RESULT } from './altStyles';
import { AltFold, AltSectionLabel, FVar } from './AltUi';

// The "Scoring and calculation" foldable of a scored (v3) tier-2 run: the
// judge's validity grades per debater, then the fixed formulas — each in
// the same three-line words/plugged/result shape as the levels and shares
// formulas. Every plugged number appears in the lines above it (the
// bullishness scores also sit on the transcript turns).

const SIDES = ['bull', 'bear'] as const;
type Side = (typeof SIDES)[number];

const SIDE_LABEL_KEY: Record<Side, UiTextKey> = {
  bull: 'tiered.debate.bull',
  bear: 'tiered.debate.bear',
};

const SIDE_COLOR: Record<Side, string> = {
  bull: 'text-emerald-300',
  bear: 'text-red-300',
};

const weightText = (score: TieredDebaterScore) => score.weight.toFixed(2);

const DebaterBlock = ({ side, score }: { side: Side; score: TieredDebaterScore }) => {
  const { t } = useUiLanguage();
  return (
    <div data-testid={`alt-scoring-${side}`}>
      <div className={`mb-1 text-xs font-semibold ${SIDE_COLOR[side]}`}>
        {t(SIDE_LABEL_KEY[side])}
      </div>
      <p className="text-xs text-gray-400">
        {t('tiered.debate.bullishness')}: <span className="tabular-nums">{score.bullishness}/10</span>
        {' · '}
        {t('tiered.debate.citationValidity')}:{' '}
        <span className="tabular-nums">{score.citation_validity}/5</span>
        {' · '}
        {t('tiered.debate.knowledgeValidity')}:{' '}
        <span className="tabular-nums">{score.knowledge_validity}/5</span>
        {' · '}
        {t('tiered.debate.logicValidity')}:{' '}
        <span className="tabular-nums">{score.logical_validity}/5</span>
      </p>
      {score.notes ? <p className="mt-0.5 text-xs text-gray-500">{score.notes}</p> : null}
      <div className="mt-2 flex flex-col gap-1 overflow-x-auto text-sm">
        <p className={FORMULA_LINE}>
          (<FVar>{t('tiered.debate.citationValidity')}</FVar> +{' '}
          <FVar>{t('tiered.debate.knowledgeValidity')}</FVar> +{' '}
          <FVar>{t('tiered.debate.logicValidity')}</FVar>) / 15
        </p>
        <p className={FORMULA_LINE}>
          = ({score.citation_validity} + {score.knowledge_validity} + {score.logical_validity}) /
          15
        </p>
        <p className={FORMULA_RESULT}>
          = {weightText(score)} ({t('tiered.debate.weight')})
        </p>
      </div>
    </div>
  );
};

interface AltDebateScoringProps {
  verdict: NonNullable<TieredDebateDetail['verdict']>;
}

export const AltDebateScoring = ({ verdict }: AltDebateScoringProps) => {
  const { t } = useUiLanguage();
  const scoring = verdict.scoring;
  const finalScore = verdict.final_score;
  const rounded = verdict.final_score_rounded;
  if (!scoring || finalScore == null || rounded == null) {
    return null;
  }
  const { bull, bear } = scoring;

  return (
    <AltFold title={t('tiered.debate.scoringTitle')}>
      {SIDES.map((side) => (
        <DebaterBlock key={side} side={side} score={scoring[side]} />
      ))}

      <div>
        <AltSectionLabel>{t('tiered.debate.finalScore')}</AltSectionLabel>
        <div className="flex flex-col gap-1 overflow-x-auto text-sm">
          <p className={FORMULA_LINE}>
            (<FVar>{t('tiered.alt.f.bullWeight')}</FVar> ×{' '}
            <FVar>{t('tiered.alt.f.bullScore')}</FVar> +{' '}
            <FVar>{t('tiered.alt.f.bearWeight')}</FVar> ×{' '}
            <FVar>{t('tiered.alt.f.bearScore')}</FVar>) / (
            <FVar>{t('tiered.alt.f.bullWeight')}</FVar> +{' '}
            <FVar>{t('tiered.alt.f.bearWeight')}</FVar>)
          </p>
          <p className={FORMULA_LINE} data-testid="alt-scoring-final-formula">
            = ({weightText(bull)} × {bull.bullishness} + {weightText(bear)} ×{' '}
            {bear.bullishness}) / ({weightText(bull)} + {weightText(bear)})
          </p>
          <p className={FORMULA_RESULT}>= {finalScore.toFixed(1)}</p>
        </div>
      </div>

      <div>
        <AltSectionLabel>{t('tiered.alt.verdict')}</AltSectionLabel>
        <div className="flex flex-col gap-1 overflow-x-auto text-sm">
          <p className={FORMULA_LINE}>
            {t('tiered.debate.roundsTo', { raw: finalScore.toFixed(1), rounded })}
          </p>
          <p className={FORMULA_LINE}>{t('tiered.debate.ranges')}</p>
          <p className={FORMULA_RESULT} data-testid="alt-scoring-verdict">
            = {t(`tiered.direction.${verdict.direction}` as UiTextKey)}
          </p>
        </div>
      </div>
    </AltFold>
  );
};
