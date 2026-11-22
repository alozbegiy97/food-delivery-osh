import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

interface EmptyStateProps {
  title: string;
  text?: string;
  action?: ReactNode;
}

export function EmptyState({ title, text, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-card border border-dashed border-border bg-surface px-6 py-12 text-center">
      <p className="text-lg font-semibold text-ink-900">{title}</p>
      {text && <p className="max-w-md text-ink-600">{text}</p>}
      {action}
    </div>
  );
}

interface ErrorStateProps {
  title: string;
  text: string;
  onRetry?: () => void;
  retrying?: boolean;
}

export function ErrorState({ title, text, onRetry, retrying = false }: ErrorStateProps) {
  const { t } = useTranslation();
  return (
    <div
      role="alert"
      className="flex flex-col items-center gap-3 rounded-card border border-danger-700/30 bg-danger-50 px-6 py-10 text-center"
    >
      <p className="text-lg font-semibold text-danger-700">{title}</p>
      <p className="max-w-md text-ink-600">{text}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          disabled={retrying}
          className="min-h-11 rounded-full bg-accent-700 px-5 font-semibold text-on-accent hover:bg-accent-strong disabled:opacity-60"
        >
          {t('common.retry')}
        </button>
      )}
    </div>
  );
}
