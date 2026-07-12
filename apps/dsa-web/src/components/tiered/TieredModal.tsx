import { useEffect, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';

interface TieredModalProps {
  isOpen: boolean;
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
}

// Lightweight content modal (formula / AI-reasoning popups on the level
// tiles). Backdrop click, the X button, and Escape all close it.
export const TieredModal = ({ isOpen, title, onClose, children }: TieredModalProps) => {
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

  const modal = (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        className="max-h-[80vh] w-full max-w-lg overflow-y-auto rounded-xl border border-border/70 bg-elevated p-5 shadow-2xl animate-in fade-in zoom-in duration-200"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-3 flex items-start justify-between gap-3">
          <h3 className="text-base font-semibold text-foreground">{title}</h3>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="rounded-md p-1 text-secondary-text transition-colors hover:bg-hover hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );

  return createPortal(modal, document.body);
};
