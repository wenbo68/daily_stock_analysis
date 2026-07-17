import { useState, type ReactNode } from 'react';
import type {
  TieredDebateCheck,
  TieredDebateDetail,
  TieredDebateItem,
  TieredDebateJudgeAxis,
  TieredDebateLink,
  TieredDebateResponse,
} from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { cn } from '../../utils/cn';
import { flashElement, jumpToMetric } from '../tiered/termHelpers';
import { ALT_LINK, FORMULA_LINE, FORMULA_RESULT, TAG_BASE } from './altStyles';
import { AltSectionLabel, FVar } from './AltUi';

// The v5/v6 debate tree: one tree, four steps. Step 1 shows the
// defender's evidence list; step 2 adds the attacker's checks and
// additions; step 3 adds the defender's responses; step 4 (the default)
// adds the judge's rulings and the scores block. v6 runs carry inline
// value-checked links and deterministic pool scores; stored v5 runs keep
// their citation chips and the weight formula. Color rules: defender text
// in the normal ink, attacker material tinted sky, judge rulings tinted
// violet, with green valid / red invalid verdicts throughout.

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
  code: 'text-amber-300',
} as const;

const DIRECTION_TEXT: Record<string, string> = {
  bullish: 'text-emerald-300',
  bearish: 'text-red-300',
};

const CITATION_REF_RE = /^citation:(\d+)$/;

const jumpToRef = (ref: string) => {
  const citationMatch = CITATION_REF_RE.exec(ref);
  if (citationMatch) {
    flashElement(`alt-src-sentiment-${citationMatch[1]}`);
  } else {
    jumpToMetric(ref);
  }
};

// v6 claims: the cited words themselves are underlined, tinted links —
// payload refs flash their metric row, sentiment refs jump to the
// sources list. Mismatched links (auto-failed by code) render red.
const LinkedClaim = ({ claim, links }: { claim: string; links: TieredDebateLink[] }) => {
  const markers = links
    .map((link) => {
      const start = claim.indexOf(link.text);
      return start >= 0 ? { start, end: start + link.text.length, link } : null;
    })
    .filter((m): m is { start: number; end: number; link: TieredDebateLink } => m !== null)
    .sort((a, b) => a.start - b.start);
  const segments: ReactNode[] = [];
  let cursor = 0;
  markers.forEach((marker, index) => {
    if (marker.start < cursor) {
      return; // overlapping link texts — keep the first
    }
    if (marker.start > cursor) {
      segments.push(<span key={`t${index}`}>{claim.slice(cursor, marker.start)}</span>);
    }
    segments.push(
      <button
        key={`l${index}`}
        type="button"
        className={cn(
          'cursor-pointer underline decoration-1 underline-offset-2',
          marker.link.mismatch
            ? 'text-red-300 decoration-red-400/60 hover:text-red-200'
            : 'text-blue-300 decoration-blue-400/60 hover:text-blue-200',
        )}
        onClick={() => jumpToRef(marker.link.ref)}
      >
        {claim.slice(marker.start, marker.end)}
      </button>,
    );
    cursor = marker.end;
  });
  if (cursor < claim.length) {
    segments.push(<span key="tail">{claim.slice(cursor)}</span>);
  }
  return <span className="text-gray-200">{segments}</span>;
};

// v5 claims keep their trailing citation chips.
const ChipRefs = ({ refs }: { refs: string[] }) => {
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
            onClick={() => jumpToRef(refPath)}
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

// One "role · check · verdict — reason [refs]" line.
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
      <span className={cn('font-semibold', ROLE_TINT[role])}>
        {t(`tiered.tree.${role}` as UiTextKey)}
      </span>
      {' · '}
      {label}
      {' · '}
      <VerdictWord ok={ok} label={verdictLabel} />
      {reason ? <span className="text-gray-500"> — {reason}</span> : null}
      {citations && citations.length > 0 ? (
        <>
          {' '}
          <ChipRefs refs={citations} />
        </>
      ) : null}
    </p>
  );
};

// The defender's response to one challenge: its two checks on the
// challenge itself, one line each — the valid/invalid words tell the
// accept/reject story on their own.
const ResponseChecks = ({ response }: { response: TieredDebateResponse }) => {
  const { t } = useUiLanguage();
  return (
    <div className="flex flex-col gap-0.5">
      {AXES.map((axis) => {
        const check: TieredDebateCheck = response[`${axis}_check`];
        const ok = check.verdict === 'valid';
        return (
          <CheckLine
            key={axis}
            role="defender"
            label={t(AXIS_LABEL_KEYS[axis])}
            ok={ok}
            verdictLabel={t(ok ? 'tiered.tree.valid' : 'tiered.tree.invalid')}
            reason={ok ? null : check.reason}
            citations={ok ? [] : check.citations}
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

// The code's own mechanical verdict on an item's numbers (v6).
const ValueCheckLine = ({ item }: { item: TieredDebateItem }) => {
  const { t } = useUiLanguage();
  if (!item.value_check || item.value_check.verdict !== 'invalid') {
    return null;
  }
  return (
    <CheckLine
      role="code"
      label={t('tiered.tree.citationCheck')}
      ok={false}
      verdictLabel={t('tiered.tree.invalid')}
      reason={(item.value_check.problems ?? []).join('; ')}
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
      {step >= 2 ? <ValueCheckLine item={item} /> : null}
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
                <ResponseChecks response={response} />
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
  const judge = item.judge ?? null;
  return (
    <div className="flex flex-col gap-1 border-l border-gray-700/60 pl-3">
      <p className="text-xs text-gray-400">
        <span className={cn('font-semibold', ROLE_TINT.attacker)}>
          {t('tiered.tree.attacker')}
        </span>
        {' · '}
        {t('tiered.tree.newlyAdded')}
      </p>
      {step >= 2 ? <ValueCheckLine item={item} /> : null}
      {step >= 3 && item.response ? (
        <div className="pl-3">
          <ResponseChecks response={item.response} />
        </div>
      ) : null}
      {step >= 4 && judge && !('kind' in judge) ? (
        // v6: the judge's own two checks, same shape as everywhere else.
        <div className="pl-6">
          {AXES.map((axis) => (
            <JudgeAxisLine key={axis} axis={axis} ruling={judge[axis]} />
          ))}
        </div>
      ) : null}
      {step >= 4 && judge && 'kind' in judge && judge.kind === 'addition_ruling' ? (
        // Stored v5 runs keep their real/bogus ruling.
        <div className="pl-6">
          <CheckLine
            role="judge"
            label={t('tiered.tree.addition')}
            ok={judge.verdict === 'real'}
            verdictLabel={t(judge.verdict === 'real' ? 'tiered.tree.real' : 'tiered.tree.bogus')}
            reason={judge.reason}
            citations={judge.citations}
          />
        </div>
      ) : null}
    </div>
  );
};

const TreeItem = ({ item, step }: { item: TieredDebateItem; step: number }) => {
  const { t } = useUiLanguage();
  const counted =
    item.final_status != null ? item.final_status === 'counted' : null;
  return (
    <li data-testid={`alt-tree-item-${item.id}`} className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-mono text-gray-500">{item.id}</span>
        <span className={cn('font-semibold', DIRECTION_TEXT[item.direction])}>
          {t(item.direction === 'bullish' ? 'tiered.tree.bullish' : 'tiered.tree.bearish')}
        </span>
        {item.links ? (
          <LinkedClaim claim={item.claim} links={item.links} />
        ) : (
          <span className="text-gray-200">{item.claim}</span>
        )}
        {!item.links && item.citations ? <ChipRefs refs={item.citations} /> : null}
        {step >= 4 && counted != null ? (
          <span
            className={cn(
              TAG_BASE,
              counted
                ? 'bg-emerald-500/20 text-emerald-300 ring-emerald-500/30'
                : 'bg-gray-500/20 text-gray-300 ring-gray-500/30',
            )}
          >
            {t(counted ? 'tiered.tree.countedWord' : 'tiered.tree.excludedWord')}
          </span>
        ) : null}
        {step >= 4 && item.count ? (
          // Stored v5 runs keep their ledger badge.
          <span
            className={cn(
              TAG_BASE,
              item.outcome === 'valid'
                ? 'bg-emerald-500/20 text-emerald-300 ring-emerald-500/30'
                : item.outcome === 'invalid'
                  ? 'bg-red-500/20 text-red-300 ring-red-500/30'
                  : 'bg-gray-500/20 text-gray-300 ring-gray-500/30',
            )}
          >
            {t('tiered.tree.counted', {
              num: item.count.numerator,
              den: item.count.denominator,
            })}
          </span>
        ) : null}
      </div>
      {item.added_by_attacker ? (
        step >= 2 ? (
          <AdditionThread item={item} step={step} />
        ) : null
      ) : step >= 2 ? (
        <DefenderItemThread item={item} step={step} />
      ) : null}
    </li>
  );
};

// One dimension row of the final-pool breakdown (v6 scores block).
const PoolDimensionLine = ({
  dimension,
  stats,
}: {
  dimension: string;
  stats: { bullish: number; bearish: number; score: number | null };
}) => {
  const { t } = useUiLanguage();
  return (
    <p className={FORMULA_LINE}>
      {DIMENSION_LABEL_KEYS[dimension] ? t(DIMENSION_LABEL_KEYS[dimension]) : dimension}
      {' · '}
      {stats.bullish} {t('tiered.tree.bullish')} / {stats.bearish} {t('tiered.tree.bearish')}
      {' → '}
      <span className="tabular-nums">{stats.score?.toFixed(2) ?? '—'}</span>
    </p>
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
  const pools = verdict?.pools ?? null;
  const weight = verdict?.weight ?? null;
  const adjusted = verdict?.adjusted_score ?? null;

  const visibleItems = step >= 2 ? items : items.filter((item) => !item.added_by_attacker);
  const groups = DIMENSION_ORDER.map((dimension) => ({
    dimension,
    items: visibleItems.filter((item) => item.dimension === dimension),
  })).filter((group) => group.items.length > 0);

  const finalDimensions = pools?.final?.dimensions ?? {};
  const finalScores = DIMENSION_ORDER.filter((d) => finalDimensions[d]).map(
    (d) => finalDimensions[d],
  );

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

      {verdict && pools ? (
        // v6: the deterministic pool scores.
        <div
          data-testid="alt-tree-scores"
          className="flex flex-col gap-1 border-t border-gray-700/60 pt-3"
        >
          <AltSectionLabel>{t('tiered.tree.scores')}</AltSectionLabel>
          <p className="text-xs text-gray-400">
            {t('tiered.tree.initialScore')}
            {' · '}
            <span className="tabular-nums text-gray-300">
              {verdict.initial_score?.toFixed(2)}
            </span>
            <span className="text-gray-600">
              {' '}
              ({pools.initial?.bullish} {t('tiered.tree.bullish')} /{' '}
              {pools.initial?.bearish} {t('tiered.tree.bearish')})
            </span>
          </p>
          {step >= 3 ? (
            <p className="text-xs text-gray-400">
              {t('tiered.tree.adjustedScore')}
              {' · '}
              <span className="tabular-nums text-gray-300">{adjusted?.toFixed(2)}</span>
              <span className="text-gray-600">
                {' '}
                ({pools.adjusted?.bullish} {t('tiered.tree.bullish')} /{' '}
                {pools.adjusted?.bearish} {t('tiered.tree.bearish')})
              </span>
            </p>
          ) : null}
          {step >= 4 ? (
            <>
              <div className="mt-2 flex flex-col gap-1 overflow-x-auto text-sm">
                <p className={FORMULA_LINE}>
                  {t('tiered.tree.finalScore')} · 10 × <FVar>{t('tiered.tree.bullish')}</FVar>{' '}
                  / <FVar>{t('tiered.tree.total')}</FVar>
                </p>
                {DIMENSION_ORDER.filter((d) => finalDimensions[d]).map((dimension) => (
                  <PoolDimensionLine
                    key={dimension}
                    dimension={dimension}
                    stats={finalDimensions[dimension]}
                  />
                ))}
                {finalScores.length > 0 ? (
                  <p className={FORMULA_LINE} data-testid="alt-tree-final-formula">
                    = ({finalScores.map((s) => s.score?.toFixed(2)).join(' + ')}) /{' '}
                    {finalScores.length}
                  </p>
                ) : null}
                <p className={FORMULA_RESULT}>= {verdict.final_score?.toFixed(2)}</p>
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

      {verdict && !pools ? (
        // Stored v5 runs: the weight-formula scores block.
        <div
          data-testid="alt-tree-scores"
          className="flex flex-col gap-1 border-t border-gray-700/60 pt-3"
        >
          <AltSectionLabel>{t('tiered.tree.scores')}</AltSectionLabel>
          <p className="text-xs text-gray-400">
            {t('tiered.tree.initialScore')}
            {' · '}
            <span className="tabular-nums text-gray-300">{verdict.initial_score}/10</span>
          </p>
          {step >= 3 && adjusted != null ? (
            <p className="text-xs text-gray-400">
              {t('tiered.tree.adjustedScore')}
              {' · '}
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
