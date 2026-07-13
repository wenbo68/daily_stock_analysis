import { useEffect, useRef, useState, type ReactNode } from 'react';
import { ChevronDown } from 'lucide-react';
import { cn } from '../../utils/cn';
import { TAG_BASE } from './altStyles';

// Write-only form controls in the showplayer style: what the user picks or
// types never stays in the field — it becomes a removable pill below the
// form (AltPill), and the field clears for the next entry.

export interface AltSelectOption {
  value: string;
  label: string;
  node?: ReactNode;
}

interface AltFieldShellProps {
  label: ReactNode;
  children: ReactNode;
}

// A labeled form column, showplayer-style: bold label above the control.
const AltFieldShell = ({ label, children }: AltFieldShellProps) => (
  <div className="flex w-full flex-col gap-2">
    <span className="font-semibold text-gray-300">{label}</span>
    {children}
  </div>
);

interface AltSelectProps {
  label: ReactNode;
  options: AltSelectOption[];
  /** Committed value — only used to highlight the matching option. */
  value?: string;
  placeholder?: string;
  inputMode?: 'decimal';
  /**
   * false (default): only listed options commit; typing filters them.
   * true: Enter commits whatever was typed; options are suggestions.
   */
  freeText?: boolean;
  validate?: (raw: string) => boolean;
  onCommit: (value: string) => void;
}

// The showplayer.net filter control: a flat gray-800 text row with a
// chevron, opening a flat dropdown panel underneath.
export const AltSelect = ({
  label,
  options,
  value,
  placeholder,
  inputMode,
  freeText = false,
  validate,
  onCommit,
}: AltSelectProps) => {
  const [written, setWritten] = useState('');
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
        setWritten('');
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const shown = freeText
    ? options
    : options.filter((option) => option.label.toLowerCase().includes(written.toLowerCase()));
  const cleaned = written.trim();
  const isInvalid = freeText && cleaned !== '' && validate ? !validate(cleaned) : false;

  const commit = (raw: string) => {
    onCommit(raw);
    setWritten('');
    window.setTimeout(() => setIsOpen(false), 50);
  };

  const handleEnter = () => {
    if (freeText) {
      if (cleaned && !isInvalid) {
        commit(cleaned);
      }
    } else if (shown.length === 1) {
      commit(shown[0].value);
    }
  };

  return (
    <AltFieldShell label={label}>
      <div ref={containerRef} className="relative">
        <div className="flex w-full items-center rounded bg-gray-800">
          <input
            type="text"
            value={written}
            inputMode={inputMode}
            onFocus={() => setIsOpen(true)}
            onChange={(event) => {
              setWritten(event.target.value);
              setIsOpen(true);
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                handleEnter();
              }
            }}
            placeholder={placeholder}
            aria-label={typeof label === 'string' ? label : undefined}
            className={cn(
              'w-full bg-transparent pl-3 placeholder-gray-500 outline-none',
              isInvalid ? 'text-red-300' : 'text-gray-300',
            )}
          />
          <button
            type="button"
            aria-label="Toggle options"
            onClick={() => setIsOpen(!isOpen)}
            className="cursor-pointer p-2 text-gray-500 hover:text-gray-300"
          >
            <ChevronDown className="h-5 w-5" />
          </button>
        </div>
        {isOpen && shown.length > 0 ? (
          <div className="absolute top-full z-10 mt-2 flex max-h-96 w-full flex-col overflow-y-auto rounded bg-gray-800 p-2 text-xs font-semibold">
            {shown.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => commit(option.value)}
                className={cn(
                  'w-full cursor-pointer rounded p-2 text-start hover:bg-gray-900 hover:text-blue-400',
                  option.value === value ? 'text-blue-400' : '',
                )}
              >
                {option.node ?? option.label}
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </AltFieldShell>
  );
};

interface AltCommitInputProps {
  placeholder: string;
  inputMode?: 'decimal';
  validate?: (raw: string) => boolean;
  onCommit: (value: string) => void;
}

// A bare write-only text box: Enter commits the trimmed text and clears.
// Invalid text (per validate) turns red and refuses to commit.
export const AltCommitInput = ({
  placeholder,
  inputMode,
  validate,
  onCommit,
}: AltCommitInputProps) => {
  const [written, setWritten] = useState('');
  const cleaned = written.trim();
  const isInvalid = cleaned !== '' && validate ? !validate(cleaned) : false;

  return (
    <input
      type="text"
      value={written}
      inputMode={inputMode}
      placeholder={placeholder}
      aria-label={placeholder}
      onChange={(event) => setWritten(event.target.value)}
      onKeyDown={(event) => {
        if (event.key !== 'Enter') {
          return;
        }
        event.preventDefault();
        if (!cleaned || isInvalid) {
          return;
        }
        onCommit(cleaned);
        setWritten('');
      }}
      className={cn(
        'w-full min-w-0 rounded bg-gray-800 px-3 py-2 placeholder-gray-500 outline-none',
        isInvalid ? 'text-red-300' : 'text-gray-300',
      )}
    />
  );
};

interface AltPairFieldProps {
  label: ReactNode;
  start: AltCommitInputProps;
  end: AltCommitInputProps;
}

// A labeled min/max (or start/end) pair — two commit boxes on one row.
export const AltPairField = ({ label, start, end }: AltPairFieldProps) => (
  <AltFieldShell label={label}>
    <div className="flex w-full items-center gap-2">
      <AltCommitInput {...start} />
      <AltCommitInput {...end} />
    </div>
  </AltFieldShell>
);

interface AltTextFieldProps extends AltCommitInputProps {
  label: ReactNode;
}

// A single labeled commit box (no dropdown).
export const AltTextField = ({ label, ...input }: AltTextFieldProps) => (
  <AltFieldShell label={label}>
    <AltCommitInput {...input} />
  </AltFieldShell>
);

interface AltPillProps {
  tone: string;
  onRemove: () => void;
  children: ReactNode;
}

// A committed selection, shown below the form; clicking it removes it.
export const AltPill = ({ tone, onRemove, children }: AltPillProps) => (
  <button
    type="button"
    onClick={onRemove}
    className={cn(TAG_BASE, tone, 'cursor-pointer transition hover:opacity-80')}
  >
    {children}
  </button>
);

interface AltPillRowProps {
  children: ReactNode;
}

// The pill strip under a form — wraps, keeps pill heights aligned.
export const AltPillRow = ({ children }: AltPillRowProps) => (
  <div className="flex flex-wrap items-center gap-2 text-xs font-semibold">{children}</div>
);
