import type { ReactNode } from 'react';
import type { TieredCoverage, TieredDimension } from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { dedupeCitations, formatValue, metricAnchorId } from '../tiered/termHelpers';
import { MetricTerm } from '../tiered/terms';
import { ALT_LINK } from './altStyles';
import { AltCard, AltNarrative, AltNotesButton } from './AltUi';

const DIMENSION_LABEL_KEYS: Record<string, UiTextKey> = {
  technicals: 'tiered.dimension.technicals',
  fundamentals: 'tiered.dimension.fundamentals',
  macro_econ: 'tiered.dimension.macro_econ',
  sentiment: 'tiered.dimension.sentiment',
};

// Named sections for payloads the backend sends (partly) flat, so every
// number sits under a heading. A payload key not listed here still shows —
// it lands in a trailing "Other" section, never disappears.
const DIMENSION_SECTIONS: Record<string, { titleKey: UiTextKey; keys: string[] }[]> = {
  technicals: [
    {
      titleKey: 'tiered.group.trend',
      keys: ['close', 'sma_20', 'sma_60', 'ema_12', 'ema_26', 'bias_20'],
    },
    { titleKey: 'tiered.group.momentum', keys: ['rsi_14', 'macd'] },
    { titleKey: 'tiered.group.volatility', keys: ['atr_14', 'swing_low_20'] },
    { titleKey: 'tiered.group.meta', keys: ['bars_count', 'score'] },
  ],
  macro_econ: [{ titleKey: 'tiered.group.reportInfo', keys: ['region', 'as_of'] }],
};

function isGroup(values: unknown): values is Record<string, unknown> {
  return values !== null && typeof values === 'object' && !Array.isArray(values);
}

interface PayloadSection {
  key: string;
  title: ReactNode;
  entries: [string, unknown][];
}

// Split a payload into titled sections: configured sections first (in their
// configured order), then any remaining nested group under its own name,
// then leftover flat keys under "Other".
function buildSections(
  dimension: string,
  payload: Record<string, unknown>,
  t: (key: UiTextKey) => string,
): PayloadSection[] {
  const remaining = new Map(Object.entries(payload));
  const sections: PayloadSection[] = [];

  for (const config of DIMENSION_SECTIONS[dimension] ?? []) {
    const entries: [string, unknown][] = [];
    for (const key of config.keys) {
      if (remaining.has(key)) {
        entries.push([key, remaining.get(key)]);
        remaining.delete(key);
      }
    }
    if (entries.length > 0) {
      sections.push({ key: config.titleKey, title: t(config.titleKey), entries });
    }
  }

  const leftoverFlat: [string, unknown][] = [];
  for (const [key, values] of remaining) {
    if (isGroup(values)) {
      sections.push({
        key,
        title: <MetricTerm term={key} underline={false} />,
        entries: [[key, values]],
      });
    } else {
      leftoverFlat.push([key, values]);
    }
  }
  if (leftoverFlat.length > 0) {
    sections.push({ key: 'other', title: t('tiered.group.other'), entries: leftoverFlat });
  }
  return sections;
}

interface MetricRowProps {
  anchorPath: string;
  term: string;
  value: unknown;
}

const MetricRow = ({ anchorPath, term, value }: MetricRowProps) => (
  <div
    id={metricAnchorId(anchorPath)}
    className="flex scroll-mt-24 items-baseline justify-between gap-3 py-1"
  >
    <dt className="text-xs">
      <MetricTerm term={term} underline={false} />
    </dt>
    <dd className="text-xs tabular-nums text-gray-300">{formatValue(value)}</dd>
  </div>
);

interface AltPayloadTableProps {
  dimension: string;
  payload: Record<string, unknown>;
}

// Every metric sits in a titled section; a hairline separates sections.
// Rows keep the same anchor ids as the main page so evidence links and
// formula inputs can scroll straight to their source here too.
const AltPayloadTable = ({ dimension, payload }: AltPayloadTableProps) => {
  const { t } = useUiLanguage();
  const sections = buildSections(dimension, payload, t);

  return (
    <div className="flex flex-col divide-y divide-gray-700/60">
      {sections.map((section) => (
        <div key={section.key} className="py-3 first:pt-0 last:pb-0">
          <div className="mb-1 text-[11px] font-bold uppercase tracking-wider text-gray-500">
            {section.title}
          </div>
          <dl className="grid grid-cols-1 gap-x-6 sm:grid-cols-2">
            {section.entries.map(([key, values]) =>
              isGroup(values) ? (
                Object.entries(values).map(([subKey, value]) => (
                  <MetricRow
                    key={`${key}.${subKey}`}
                    anchorPath={`${dimension}.${key}.${subKey}`}
                    term={subKey}
                    value={value}
                  />
                ))
              ) : (
                <MetricRow key={key} anchorPath={`${dimension}.${key}`} term={key} value={values} />
              ),
            )}
          </dl>
        </div>
      ))}
    </div>
  );
};

interface AltDimensionCardProps {
  dimension: TieredDimension;
}

const AltDimensionCard = ({ dimension }: AltDimensionCardProps) => {
  const { t } = useUiLanguage();
  const labelKey = DIMENSION_LABEL_KEYS[dimension.dimension];
  const uniqueCitations = dedupeCitations(dimension.citations);

  return (
    <AltCard testId={`alt-dimension-${dimension.dimension}`}>
      <div className="mb-3 flex items-center justify-between gap-2">
        <h3 className="font-semibold text-gray-300">
          {labelKey ? t(labelKey) : dimension.dimension}
        </h3>
        <AltNotesButton
          notes={dimension.warnings}
          coverage={dimension.coverage as TieredCoverage}
        />
      </div>

      {dimension.narrative ? (
        <div className="mb-3">
          <AltNarrative text={dimension.narrative} citations={uniqueCitations} />
        </div>
      ) : null}

      {dimension.payload ? (
        <AltPayloadTable dimension={dimension.dimension} payload={dimension.payload} />
      ) : null}

      {uniqueCitations.length > 0 ? (
        <div className="mt-3">
          <div className="mb-1 text-xs font-semibold text-gray-500">
            {dimension.narrative ? t('tiered.citations') : t('tiered.dataSources')}
          </div>
          <ul className="flex flex-col gap-1">
            {uniqueCitations.map((citation, index) => (
              <li key={index} className="flex gap-2 text-xs">
                {dimension.narrative ? (
                  <span className="shrink-0 text-gray-500">[{index + 1}]</span>
                ) : null}
                {citation.url ? (
                  <a
                    href={citation.url}
                    target="_blank"
                    rel="noreferrer"
                    className={`truncate ${ALT_LINK}`}
                  >
                    {citation.title || citation.url}
                  </a>
                ) : (
                  <span className="truncate">{citation.source_name}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </AltCard>
  );
};

interface AltDimensionsProps {
  dimensions: TieredDimension[];
}

export const AltDimensions = ({ dimensions }: AltDimensionsProps) => (
  <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
    {dimensions.map((dimension) => (
      <AltDimensionCard key={dimension.dimension} dimension={dimension} />
    ))}
  </div>
);
