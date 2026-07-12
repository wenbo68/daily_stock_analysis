import type { TieredDepth } from '../../api/tiered';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { cn } from '../../utils/cn';
import { HelpTerm } from './terms';

const DEPTHS: { value: TieredDepth; labelKey: UiTextKey }[] = [
  { value: 1, labelKey: 'tiered.depth.1' },
  { value: 2, labelKey: 'tiered.depth.2' },
  { value: 3, labelKey: 'tiered.depth.3' },
];

interface DepthSelectorProps {
  value: TieredDepth;
  onChange: (depth: TieredDepth) => void;
  disabled?: boolean;
}

// How deep the run goes: 1 = standard analysis, 2 = + bull/bear debate,
// 3 = + risk stress test. Deeper = more AI calls = slower and costlier —
// the help popup says exactly that in plain words.
export const DepthSelector = ({ value, onChange, disabled = false }: DepthSelectorProps) => {
  const { t } = useUiLanguage();

  return (
    <div data-testid="depth-selector" className="flex flex-wrap items-center gap-2">
      <span className="text-xs text-secondary-text">
        <HelpTerm label={t('tiered.depth.label')} helpKey="tiered.help.depth" />
      </span>
      <div role="radiogroup" aria-label={t('tiered.depth.label')} className="flex rounded-lg border border-border/60 p-0.5">
        {DEPTHS.map((depth) => (
          <button
            key={depth.value}
            type="button"
            role="radio"
            aria-checked={value === depth.value}
            disabled={disabled}
            onClick={() => onChange(depth.value)}
            className={cn(
              'rounded-md px-3 py-1 text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-60',
              value === depth.value
                ? 'bg-cyan/20 font-medium text-foreground'
                : 'text-secondary-text hover:bg-elevated hover:text-foreground',
            )}
          >
            {t(depth.labelKey)}
          </button>
        ))}
      </div>
    </div>
  );
};
