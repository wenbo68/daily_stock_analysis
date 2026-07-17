import { useState } from 'react';
import type {
  TieredDebateCheck,
  TieredDebateDetail,
  TieredDebateItem,
  TieredDebateJudgeAxis,
  TieredDebateResponse,
} from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { cn } from '../../utils/cn';
import { flashElement, jumpToMetric } from '../tiered/termHelpers';
import { ALT_LINK, FORMULA_LINE, FORMULA_RESULT, TAG_BASE } from './altStyles';
import { AltSectionLabel, FVar } from './AltUi';

// The v5 debate tree: one tree, four steps. Step 1 shows the defender's
// evidence list and initial score; step 2 adds the attacker's checks and
// additions; step 3 adds the defender's responses and the adjusted score;
// step 4 (the default) adds the judge's rulings, the weight ledger and the
// final-score formula. Color rules: defender text in the normal ink,
// attacker material tinted sky, judge rulings tinted violet, with green
// valid / red invalid verdicts throughout.

const STEPS = [
  { n: 1, labelKey: 'tiered.tree.step.argument' },
  { n: 2, labelKey: 'tiered.tree.step.attack' },
  { n: 3, labelKey: 'tiered.tree.step.response' },
  { n: 4, labelKey: 'tiered.tree.step.judge' },
] as const;

const DIMENSION_ORDER = ['technicals', 'fundamentals', 'macro_econ', 'sentiment'];

const DIMENSION_LABEL_KEYS: Record<string, UiTextKey> = {
  technicals: 'tiered.dimension.technicals',
  fundamentals: 'tiered.dimension.fundamentals',
  macro_econ: 'tiered.dimension.macro_econ',
  sentiment: 'tiered.dimension.sentiment',
};

const AXES = ['citation', 'logic'] as const;
type Axis = (typeof AXES)[number];

const AXIS_LABEL_KEYS: Record<Axis, UiTextKey> = {
  citation: 'tiered.tree.citationCheck',
  logic: 'tiered.tree.logicCheck',
};

const ROLE_TINT = {
  attacker: 'text-sky-300',
  judge: 'text-violet-300',
  defender: 'text-gray-300',
} as const;

const OUTCOME_TAG: Record<string, string> = {
  valid: 'bg-emerald-500/20 text-emerald-300 ring-emerald-500/30',
  invalid: 'bg-red-500/20 text-red-300 ring-red-500/30',
  neutral: 'bg-gray-500/20 text-gray-300 ring-gray-500/30',
};

const DIRECTION_TAG: Record<string, string> = {
  bullish: 'bg-emerald-500/20 text-emerald-300 ring-emerald-500/30',
  bearish: 'bg-red-500/20 text-red-300 ring-red-500/30',
};

const CITATION_REF_RE = /^citation:(\d+)$/;

// Evidence chips: a payload path scrolls to its metric row in the
// dimension reports; "citation:N" scrolls to source N in the sentiment
// report's own sources section (the external link lives there).
const TreeRefs = ({ refs }: { refs: string[] }) => {
  if (refs.length === 0) {
    return null;
  }
  return (
    <span className="inline-flex flex-wrap gap-x-2 text-[11px]">
      {refs.map((refPath, index) => {
        const citationMatch = CITATION_REF_RE.exec(refPath);
        return (
          <button
            key={index}
            type="button"
            className={cn('cursor-pointer', ALT_LINK)}
            onClick={() =>
              citationMatch
                ? flashElement(`alt-src-sentiment-${citationMatch[1]}`)
                : jumpToMetric(refPath)
            }
          >
            {citationMatch ? `sentiment.${refPath}` : refPath}
          </button>
        );
      })}
    </span>
  );
};

const VerdictWord = ({ ok, label }: { ok: boolean; label: string }) => (
  <span className={ok ? 'text-emerald-300' : 'text-red-300'}>{label}</span>
);

// One "role · check: verdict — reason [refs]" line.
const CheckLine = ({
  role,
  label,
  ok,
  verdictLabel,
  reason,
  citations,
}: {
  role: keyof typeof ROLE_TINT;
  label: string;
  ok: boolean;
  verdictLabel: string;
  reason?: string | null;
  citations?: string[];
}) => {
  const { t } = useUiLanguage();
  return (
    <p className="text-xs text-gray-400">
      <span className={cn('font-semibold', ROLE_TINT[role])}>{t(`tiered.tree.${role}` as UiTextKey)}</span>
      {' · '}
      {label}: <VerdictWord ok={ok} label={verdictLabel} />
      {reason ? <span className="text-gray-500"> — {reason}</span> : null}
      {citations && citations.length > 0 ? (
        <>
          {' '}
          <TreeRefs refs={citations} />
        </>
      ) : null}
    </p>
  );
};

// The defender's response to one challenge: accepted, or rejected with the
// failing check(s) spelled out.
const ResponseLine = ({ response }: { response: TieredDebateResponse }) => {
  const { t } = useUiLanguage();
  if (response.accepted) {
    return (
      <CheckLine
        role="defender"
        label={t('tiered.tree.response')}
        ok
        verdictLabel={t('tiered.tree.accepted')}
      />
    );
  }
  const failing = AXES.filter(
    (axis) => response[`${axis}_check`].verdict === 'invalid',
  );
  return (
    <div className="flex flex-col gap-0.5">
      {failing.map((axis) => {
        const check: TieredDebateCheck = response[`${axis}_check`];
        return (
          <CheckLine
            key={axis}
            role="defender"
            label={`${t('tiered.tree.response')} · ${t(AXIS_LABEL_KEYS[axis])}`}
            ok={false}
            verdictLabel={t('tiered.tree.rejected')}
            reason={check.reason}
            citations={check.citations}
          />
        );
      })}
    </div>
  );
};

const JudgeAxisLine = ({ axis, ruling }: { axis: Axis; ruling: TieredDebateJudgeAxis }) => {
  const { t } = useUiLanguage();
  if (ruling.kind === 'attack_ruling') {
    const ok = ruling.verdict === 'attack_wrong'; // wrong attack → item survives
    return (
      <CheckLine
        role="judge"
        label={t(AXIS_LABEL_KEYS[axis])}
        ok={ok}
        verdictLabel={t(ok ? 'tiered.tree.attackWrong' : 'tiered.tree.attackRight')}
        reason={ruling.reason}
        citations={ruling.citations}
      />
    );
  }
  const ok = ruling.verdict === 'valid';
  return (
    <CheckLine
      role="judge"
      label={t(AXIS_LABEL_KEYS[axis])}
      ok={ok}
      verdictLabel={t(ok ? 'tiered.tree.valid' : 'tiered.tree.invalid')}
      reason={ruling.reason}
      citations={ruling.citations}
    />
  );
};

// Everything under one defender item: per-axis attacker check → defender
// response → judge word, indentation mirroring the debate's structure.
const DefenderItemThread = ({ item, step }: { item: TieredDebateItem; step: number }) => {
  const { t } = useUiLanguage();
  const judge = item.judge && !('kind' in item.judge) ? item.judge : null;
  return (
    <div className="flex flex-col gap-1 border-l border-gray-700/60 pl-3">
      {AXES.map((axis) => {
        const check = item.attacker_checks?.[axis];
        if (!check) {
          return null;
        }
        const attacked = check.verdict === 'invalid';
        const response = item.responses?.[axis] ?? null;
        return (
          <div key={axis} className="flex flex-col gap-0.5">
            {step >= 2 ? (
              <CheckLine
                role="attacker"
                label={t(AXIS_LABEL_KEYS[axis])}
                ok={!attacked}
                verdictLabel={t(attacked ? 'tiered.tree.invalid' : 'tiered.tree.valid')}
                reason={attacked ? check.reason : null}
                citations={attacked ? check.citations : []}
              />
            ) : null}
            {step >= 3 && response ? (
              <div className="pl-3">
                <ResponseLine response={response} />
              </div>
            ) : null}
            {step >= 4 && judge ? (
              <div className={attacked ? 'pl-6' : 'pl-3'}>
                <JudgeAxisLine axis={axis} ruling={judge[axis]} />
              </div>
            ) : null}
          </div>
        );
      })}
      {/* Attacker review degraded (no checks): the judge still ruled. */}
      {!item.attacker_checks && step >= 4 && judge ? (
        <div className="flex flex-col gap-0.5">
          {AXES.map((axis) => (
            <JudgeAxisLine key={axis} axis={axis} ruling={judge[axis]} />
          ))}
        </div>
      ) : null}
    </div>
  );
};

const AdditionThread = ({ item, step }: { item: TieredDebateItem; step: number }) => {
  const { t } = useUiLanguage();
  const judge = item.judge && 'kind' in item.judge ? item.judge : null;
  return (
    <div className="flex flex-col gap-1 border-l border-gray-700/60 pl-3">
      {step >= 3 && item.response ? <ResponseLine response={item.response} /> : null}
      {step >= 4 && judge ? (
        <CheckLine
          role="judge"
          label={t('tiered.tree.addition')}
          ok={judge.verdict === 'real'}
          verdictLabel={t(judge.verdict === 'real' ? 'tiered.tree.real' : 'tiered.tree.bogus')}
          reason={judge.reason}
          citations={judge.citations}
        />
      ) : null}
    </div>
  );
};

const TreeItem = ({ item, step }: { item: TieredDebateItem; step: number }) => {
  const { t } = useUiLanguage();
  return (
    <li data-testid={`alt-tree-item-${item.id}`} className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-mono text-gray-500">{item.id}</span>
        <span className={cn(TAG_BASE, DIRECTION_TAG[item.direction])}>
          {t(item.direction === 'bullish' ? 'tiered.tree.bullish' : 'tiered.tree.bearish')}
        </span>
        {item.added_by_attacker ? (
          <span className={cn(TAG_BASE, 'bg-sky-500/20 text-sky-300 ring-sky-500/30')}>
            {t('tiered.tree.addedByAttacker')}
          </span>
        ) : null}
        <span className="text-gray-200">{item.claim}</span>
        <TreeRefs refs={item.citations} />
        {step >= 4 && item.count ? (
          <span className={cn(TAG_BASE, OUTCOME_TAG[item.outcome ?? 'neutral'])}>
            {t('tiered.tree.counted', {
              num: item.count.numerator,
              den: item.count.denominator,
            })}
          </span>
        ) : null}
      </div>
      {item.added_by_attacker ? (
        step >= 3 ? (
          <AdditionThread item={item} step={step} />
        ) : null
      ) : step >= 2 ? (
        <DefenderItemThread item={item} step={step} />
      ) : null}
    </li>
  );
};

interface AltDebateTreeProps {
  detail: TieredDebateDetail;
}

export const AltDebateTree = ({ detail }: AltDebateTreeProps) => {
  const { t } = useUiLanguage();
  const [step, setStep] = useState(4);
  const items = detail.items ?? [];
  const verdict = detail.verdict;
  const weight = verdict?.weight ?? null;
  const adjusted = verdict?.adjusted_score ?? null;

  const visibleItems = step >= 2 ? items : items.filter((item) => !item.added_by_attacker);
  const groups = DIMENSION_ORDER.map((dimension) => ({
    dimension,
    items: visibleItems.filter((item) => item.dimension === dimension),
  })).filter((group) => group.items.length > 0);

  return (
    <div data-testid="alt-debate-tree" className="mt-4 flex flex-col gap-3">
      {/* The four-step selector; the complete tree is the default view. */}
      <div className="flex flex-wrap gap-1 text-xs">
        {STEPS.map(({ n, labelKey }) => (
          <button
            key={n}
            type="button"
            data-testid={`alt-tree-step-${n}`}
            onClick={() => setStep(n)}
            className={cn(
              'cursor-pointer rounded px-2 py-1',
              step === n
                ? 'bg-gray-700 font-semibold text-gray-200'
                : 'text-gray-500 hover:text-gray-300',
            )}
          >
            {n} · {t(labelKey)}
          </button>
        ))}
      </div>

      <div className="flex flex-col gap-3">
        {groups.map((group) => (
          <div key={group.dimension}>
            <AltSectionLabel>
              {DIMENSION_LABEL_KEYS[group.dimension]
                ? t(DIMENSION_LABEL_KEYS[group.dimension])
                : group.dimension}
            </AltSectionLabel>
            <ul className="flex flex-col gap-2">
              {group.items.map((item) => (
                <TreeItem key={item.id} item={item} step={step} />
              ))}
            </ul>
          </div>
        ))}
      </div>

      {verdict ? (
        <div
          data-testid="alt-tree-scores"
          className="flex flex-col gap-1 border-t border-gray-700/60 pt-3"
        >
          <AltSectionLabel>{t('tiered.tree.scores')}</AltSectionLabel>
          <p className="text-xs text-gray-400">
            {t('tiered.tree.initialScore')}:{' '}
            <span className="tabular-nums text-gray-300">{verdict.initial_score}/10</span>
          </p>
          {step >= 3 && adjusted != null ? (
            <p className="text-xs text-gray-400">
              {t('tiered.tree.adjustedScore')}:{' '}
              <span className="tabular-nums text-gray-300">{adjusted}/10</span>
              {verdict.adjusted_kept ? ` ${t('tiered.tree.kept')}` : ''}
            </p>
          ) : null}
          {step >= 4 && weight ? (
            <div className="mt-2 flex flex-col gap-1 overflow-x-auto text-sm">
              <p className={FORMULA_LINE}>{t('tiered.tree.weightWords')}</p>
              <p className={FORMULA_LINE}>
                = {weight.numerator}/{weight.denominator}
              </p>
              <p className={FORMULA_RESULT}>
                = {weight.value} ({t('tiered.debate.weight')})
              </p>
            </div>
          ) : null}
          {step >= 4 && weight && adjusted != null && verdict.final_score != null ? (
            <>
              <div className="mt-2 flex flex-col gap-1 overflow-x-auto text-sm">
                <p className={FORMULA_LINE}>
                  5 + <FVar>{t('tiered.debate.weight')}</FVar> × (
                  <FVar>{t('tiered.tree.adjustedScore')}</FVar> − 5)
                </p>
                <p className={FORMULA_LINE} data-testid="alt-tree-final-formula">
                  = 5 + {weight.value} × ({adjusted} − 5)
                </p>
                <p className={FORMULA_RESULT}>= {verdict.final_score.toFixed(2)}</p>
              </div>
              <div className="mt-2 flex flex-col gap-1 overflow-x-auto text-sm">
                <p className={FORMULA_LINE}>{t('tiered.tree.ranges')}</p>
                <p className={FORMULA_RESULT} data-testid="alt-tree-verdict">
                  = {t(`tiered.direction.${verdict.direction}` as UiTextKey)}
                </p>
              </div>
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
};
