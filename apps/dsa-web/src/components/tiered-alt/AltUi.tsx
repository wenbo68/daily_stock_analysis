import { useEffect, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { CircleAlert, CircleX, X } from 'lucide-react';
import type { TieredCitation, TieredCoverage } from '../../api/tiered';
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
  <section data-testid={testId} className={cn('rounded bg-gray-800 p-5', className)}>
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
        className="max-h-[80vh] w-full max-w-lg overflow-y-auto rounded bg-gray-800 p-5 text-sm text-gray-400"
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

interface AltNotesButtonProps {
  notes: string[];
  coverage?: TieredCoverage;
}

// The card's only data-quality signal. Full data and nothing to report →
// no mark at all. Something to report → a small amber exclamation mark
// (or a red X when the data was entirely unavailable) that opens a modal
// listing each note in plain English (altWarningText.ts) with the
// original technical message underneath. Notes whose shape we don't
// recognize render as-is rather than get a made-up gloss.
export const AltNotesButton = ({ notes, coverage = 'full' }: AltNotesButtonProps) => {
  const { t } = useUiLanguage();
  const [isOpen, setIsOpen] = useState(false);

  if (notes.length === 0 && coverage === 'full') {
    return null;
  }
  const isUnavailable = coverage === 'unavailable';
  const Icon = isUnavailable ? CircleX : CircleAlert;
  return (
    <>
      <button
        type="button"
        data-testid="alt-notes-button"
        aria-label={t('tiered.dataNotes')}
        onClick={() => setIsOpen(true)}
        className={cn(
          'inline-flex cursor-pointer items-center rounded',
          isUnavailable ? 'text-red-300 hover:text-red-200' : 'text-amber-300 hover:text-amber-200',
        )}
      >
        <Icon className="h-4 w-4" />
      </button>
      <AltModal isOpen={isOpen} title={t('tiered.dataNotes')} onClose={() => setIsOpen(false)}>
        <p className="mb-4 text-xs leading-relaxed text-gray-500">{t('tiered.dataNotesHint')}</p>
        {notes.length === 0 ? <p className="text-sm text-amber-300">{t('tiered.note.none')}</p> : null}
        <ul className="flex flex-col gap-4">
          {notes.map((raw, index) => {
            const friendly = friendlyWarning(raw, t);
            return (
              <li key={index} className="text-sm leading-relaxed">
                <span className="text-amber-300">{friendly ?? raw}</span>
                {friendly ? (
                  <span className="mt-1 block font-mono text-[11px] leading-relaxed text-gray-500">
                    {raw}
                  </span>
                ) : null}
              </li>
            );
          })}
        </ul>
      </AltModal>
    </>
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
