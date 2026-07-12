import type { TieredDimension } from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { dedupeCitations, formatValue, metricAnchorId } from '../tiered/termHelpers';
import { HelpTerm, MetricTerm } from '../tiered/terms';
import { ALT_LINK, COVERAGE_TAG } from './altStyles';
import { AltCard, AltNarrative, AltTag } from './AltUi';

const DIMENSION_LABEL_KEYS: Record<string, UiTextKey> = {
  technicals: 'tiered.dimension.technicals',
  fundamentals: 'tiered.dimension.fundamentals',
  macro_econ: 'tiered.dimension.macro_econ',
  sentiment: 'tiered.dimension.sentiment',
};

interface AltPayloadTableProps {
  dimension: string;
  payload: Record<string, unknown>;
}

// Rows keep the same anchor ids as the main page so evidence links and
// formula inputs can scroll straight to their source here too.
const AltPayloadTable = ({ dimension, payload }: AltPayloadTableProps) => (
  <div className="flex flex-col gap-3">
    {Object.entries(payload).map(([group, values]) => {
      if (values !== null && typeof values === 'object' && !Array.isArray(values)) {
        return (
          <div key={group}>
            <div className="mb-1 text-xs font-semibold text-gray-500">
              <MetricTerm term={group} />
            </div>
            <dl className="grid grid-cols-1 gap-x-6 sm:grid-cols-2">
              {Object.entries(values as Record<string, unknown>).map(([key, value]) => (
                <div
                  key={key}
                  id={metricAnchorId(`${dimension}.${group}.${key}`)}
                  className="flex scroll-mt-24 items-baseline justify-between gap-3 py-1"
                >
                  <dt className="text-xs">
                    <MetricTerm term={key} />
                  </dt>
                  <dd className="text-xs tabular-nums text-gray-300">{formatValue(value)}</dd>
                </div>
              ))}
            </dl>
          </div>
        );
      }
      return (
        <div
          key={group}
          id={metricAnchorId(`${dimension}.${group}`)}
          className="flex scroll-mt-24 items-baseline justify-between gap-3 py-1"
        >
          <dt className="text-xs">
            <MetricTerm term={group} />
          </dt>
          <dd className="text-xs tabular-nums text-gray-300">{formatValue(values)}</dd>
        </div>
      );
    })}
  </div>
);

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
        <HelpTerm
          underline={false}
          helpKey="tiered.help.coverage"
          label={
            <AltTag tone={COVERAGE_TAG[dimension.coverage]}>
              {t(`tiered.coverage.${dimension.coverage}` as UiTextKey)}
            </AltTag>
          }
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
          <div className="mb-1 text-xs font-semibold text-gray-500">{t('tiered.citations')}</div>
          <ul className="flex flex-col gap-1">
            {uniqueCitations.map((citation, index) => (
              <li key={index} className="flex gap-2 text-xs">
                <span className="shrink-0 text-gray-500">[{index + 1}]</span>
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

      {dimension.warnings.length > 0 ? (
        <div className="mt-3">
          <div className="mb-1 text-xs font-semibold text-gray-500">{t('tiered.dataNotes')}</div>
          <ul className="flex flex-col gap-1">
            {dimension.warnings.map((warning, index) => (
              <li key={index} className="text-xs text-amber-300">
                {warning}
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
