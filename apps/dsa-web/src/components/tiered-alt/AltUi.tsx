import { useEffect, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import type { TieredCitation } from '../../api/tiered';
import { Tooltip } from '../common';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { cn } from '../../utils/cn';
import { jumpToMetric } from '../tiered/termHelpers';
import { ALT_LINK, TAG_BASE } from './altStyles';
import { friendlyWarning } from './altWarningText';

interface AltTagProps {
  tone: string;
  children: ReactNode;
}

export const AltTag = ({ tone, children }: AltTagProps) => (
  <span className={cn(TAG_BASE, tone)}>{children}</span>
);

interface AltCardProps {
  children: ReactNode;
  className?: string;
  testId?: string;
}

// The only surface on the alt page: flat gray-800, small radius, no border,
// no shadow — separation comes from the gray-900 canvas and whitespace.
export const AltCard = ({ children, className, testId }: AltCardProps) => (
  <section data-testid={testId} className={cn('rounded-lg bg-gray-800 p-5', className)}>
    {children}
  </section>
);

interface AltModalProps {
  isOpen: boolean;
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
}

// showplayer-style popup: black/50 backdrop, flat gray-800 panel.
export const AltModal = ({ isOpen, title, onClose, children }: AltModalProps) => {
  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) {
    return null;
  }

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        className="max-h-[80vh] w-full max-w-lg overflow-y-auto rounded-lg bg-gray-800 p-5 text-sm text-gray-400"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <h3 className="font-semibold text-gray-300">{title}</h3>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="cursor-pointer rounded p-1 text-gray-500 hover:bg-gray-700 hover:text-gray-300"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
};

interface AltNotesProps {
  notes: string[];
}

// Backend data notes, rewritten in plain English (altWarningText.ts).
// Hover or tap a note to see the original technical message; notes whose
// shape we don't recognize render as-is rather than get a made-up gloss.
export const AltNotes = ({ notes }: AltNotesProps) => {
  const { t } = useUiLanguage();

  if (notes.length === 0) {
    return null;
  }
  return (
    <ul className="flex flex-col gap-1">
      {notes.map((raw, index) => {
        const friendly = friendlyWarning(raw, t);
        return (
          <li key={index} className="text-xs leading-relaxed text-amber-300">
            {friendly ? (
              <Tooltip
                focusable
                content={
                  <span className="block max-w-[20rem] whitespace-normal">
                    <span className="block font-semibold text-foreground">
                      {t('tiered.note.rawLabel')}
                    </span>
                    <span className="mt-0.5 block font-mono text-[11px] text-secondary-text">
                      {raw}
                    </span>
                  </span>
                }
              >
                <span className="cursor-help">{friendly}</span>
              </Tooltip>
            ) : (
              raw
            )}
          </li>
        );
      })}
    </ul>
  );
};

const CITATION_MARKER_SPLIT_RE = /(\[\d+\])/g;
const CITATION_MARKER_RE = /^\[(\d+)\]$/;

interface AltNarrativeProps {
  text: string;
  citations: TieredCitation[];
}

// Narrative text with [n] markers linked to their numbered sources —
// same behavior as the main page, alt colors.
export const AltNarrative = ({ text, citations }: AltNarrativeProps) => (
  <p className="text-sm leading-relaxed">
    {text.split(CITATION_MARKER_SPLIT_RE).map((part, index) => {
      const match = CITATION_MARKER_RE.exec(part);
      const citation = match ? citations[Number(match[1]) - 1] : undefined;
      if (citation?.url) {
        return (
          <a
            key={index}
            href={citation.url}
            target="_blank"
            rel="noreferrer"
            aria-label={citation.title ?? citation.url}
            className={ALT_LINK}
          >
            {part}
          </a>
        );
      }
      return <span key={index}>{part}</span>;
    })}
  </p>
);

const CITATION_REF_RE = /^citation:(\d+)$/;

interface AltEvidenceRefsProps {
  refs: string[];
  citations: TieredCitation[];
  onNavigate?: () => void;
}

// Evidence references as links: "citation:N" opens the news source, a
// payload path scrolls to that metric row. Unresolvable refs stay text.
export const AltEvidenceRefs = ({ refs, citations, onNavigate }: AltEvidenceRefsProps) => (
  <span className="inline-flex flex-wrap gap-x-2 text-[11px]">
    {refs.map((refPath, index) => {
      const citationMatch = CITATION_REF_RE.exec(refPath);
      if (citationMatch) {
        const citation = citations[Number(citationMatch[1]) - 1];
        if (citation?.url) {
          return (
            <a
              key={index}
              href={citation.url}
              target="_blank"
              rel="noreferrer"
              aria-label={citation.title ?? citation.url}
              className={ALT_LINK}
            >
              {refPath}
            </a>
          );
        }
        return <span key={index}>{refPath}</span>;
      }
      return (
        <button
          key={index}
          type="button"
          className={cn('cursor-pointer', ALT_LINK)}
          onClick={() => {
            onNavigate?.();
            // Let any open modal unmount before scrolling to the row behind it.
            window.setTimeout(() => jumpToMetric(refPath), 50);
          }}
        >
          {refPath}
        </button>
      );
    })}
  </span>
);
