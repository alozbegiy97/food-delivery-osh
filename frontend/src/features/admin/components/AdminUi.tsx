import type { SerializedError } from '@reduxjs/toolkit';
import type { FetchBaseQueryError } from '@reduxjs/toolkit/query';
import { useId, useState, type InputHTMLAttributes, type ReactNode, type Ref } from 'react';
import { useTranslation } from 'react-i18next';

import { apiErrorInfo } from '../../../shared/api/errors';

export function AdminSection({
  title,
  description,
  actions,
  children,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rounded-card border border-border bg-surface p-5 shadow-[var(--shadow-card)]">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold">{title}</h2>
          {description && <p className="mt-1 text-sm text-ink-600">{description}</p>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string;
  hint?: string;
  ref?: Ref<HTMLInputElement>;
}

export function Field({ label, error, hint, id, ref, className = '', ...props }: FieldProps) {
  const generated = useId();
  const inputId = id ?? generated;
  return (
    <div className={`flex flex-col gap-1 ${className}`}>
      <label htmlFor={inputId} className="text-sm font-medium">
        {label}
      </label>
      <input
        id={inputId}
        ref={ref}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${inputId}-error` : hint ? `${inputId}-hint` : undefined}
        className="min-h-11 rounded-lg border border-border bg-surface px-3 py-2 aria-[invalid=true]:border-danger-700"
        {...props}
      />
      {hint && !error && (
        <p id={`${inputId}-hint`} className="text-xs text-ink-600">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${inputId}-error`} className="text-sm text-danger-700">
          {error}
        </p>
      )}
    </div>
  );
}

interface ToggleProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> {
  label: string;
  hint?: string;
  ref?: Ref<HTMLInputElement>;
}

/** Switch-looking checkbox with a visible label (status is not colour only). */
export function Toggle({ label, hint, ref, ...props }: ToggleProps) {
  return (
    <label className="flex cursor-pointer items-start gap-3">
      <input type="checkbox" ref={ref} className="peer sr-only" {...props} />
      <span
        aria-hidden="true"
        className="relative mt-0.5 h-6 w-11 shrink-0 rounded-full bg-border transition peer-checked:bg-success-700 peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-accent-700 after:absolute after:left-0.5 after:top-0.5 after:h-5 after:w-5 after:rounded-full after:bg-white after:transition peer-checked:after:translate-x-5"
      />
      <span>
        <span className="text-sm font-medium">{label}</span>
        {hint && <span className="block text-xs text-ink-600">{hint}</span>}
      </span>
    </label>
  );
}

export function Badge({
  tone,
  children,
}: {
  tone: 'success' | 'muted' | 'danger' | 'accent';
  children: ReactNode;
}) {
  const tones = {
    success: 'bg-success-50 text-success-700',
    muted: 'bg-cream-100 text-ink-600',
    danger: 'bg-danger-50 text-danger-700',
    accent: 'bg-accent-100 text-accent-800',
  };
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${tones[tone]}`}
    >
      {children}
    </span>
  );
}

export const BUTTON_PRIMARY =
  'inline-flex min-h-11 items-center justify-center rounded-full bg-accent-700 px-5 font-semibold text-white hover:bg-accent-800 disabled:opacity-60';
export const BUTTON_SECONDARY =
  'inline-flex min-h-11 items-center justify-center rounded-full bg-surface px-5 font-semibold ring-1 ring-border hover:bg-cream-100 disabled:opacity-60';
export const BUTTON_DANGER =
  'inline-flex min-h-11 items-center justify-center rounded-full bg-danger-700 px-5 font-semibold text-white hover:opacity-90 disabled:opacity-60';

/** Two-step confirmation for dangerous actions (UI_UX_GUIDELINES §4). */
export function ConfirmAction({
  label,
  question,
  confirmLabel,
  onConfirm,
  pending = false,
}: {
  label: string;
  question: string;
  confirmLabel: string;
  onConfirm: () => void;
  pending?: boolean;
}) {
  const { t } = useTranslation();
  const [asking, setAsking] = useState(false);
  if (!asking) {
    return (
      <button
        type="button"
        className={BUTTON_SECONDARY}
        onClick={() => setAsking(true)}
        disabled={pending}
      >
        {label}
      </button>
    );
  }
  return (
    <div
      role="alertdialog"
      aria-label={question}
      className="flex flex-wrap items-center gap-2 rounded-xl bg-danger-50 p-3"
    >
      <span className="text-sm font-medium text-danger-700">{question}</span>
      <button
        type="button"
        className={BUTTON_DANGER}
        disabled={pending}
        onClick={() => {
          setAsking(false);
          onConfirm();
        }}
      >
        {confirmLabel}
      </button>
      <button type="button" className={BUTTON_SECONDARY} onClick={() => setAsking(false)}>
        {t('admin.cancel')}
      </button>
    </div>
  );
}

const KNOWN_DETAILS: Record<string, string> = {
  'this slug is already used': 'admin.errors.slugTaken',
  'this SKU is already used': 'admin.errors.skuTaken',
  'a single-choice group allows exactly one option': 'admin.errors.singleMax',
  'minimum must not exceed maximum': 'admin.errors.minMax',
  "the modifier's group is not linked to this product": 'admin.errors.groupNotLinked',
  'category does not exist': 'admin.errors.categoryMissing',
  'the Russian (ru) name is required': 'admin.validation.ruRequired',
};

/** Localized API error with known field problems spelled out. */
export function AdminError({
  error,
}: {
  error: FetchBaseQueryError | SerializedError | undefined;
}) {
  const { t } = useTranslation();
  const info = apiErrorInfo(error);
  if (!info) {
    return null;
  }
  const details = info.fields.map((field) => {
    const known = Object.entries(KNOWN_DETAILS).find(([text]) => field.message.includes(text));
    return known ? t(known[1]) : null;
  });
  const unique = [...new Set(details.filter((d): d is string => d !== null))];
  return (
    <div
      role="alert"
      className="rounded-xl border border-danger-700/30 bg-danger-50 px-4 py-3 text-sm text-danger-700"
    >
      <p className="font-semibold">
        {info.code === 'INVALID_FILE'
          ? t('admin.errors.file')
          : t(`errors.codes.${info.code}`, { defaultValue: t('errors.codes.default') })}
      </p>
      {unique.length > 0 && (
        <ul className="mt-1 list-disc pl-5">
          {unique.map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function SavedNote({ show }: { show: boolean }) {
  const { t } = useTranslation();
  if (!show) {
    return null;
  }
  return (
    <p role="status" className="text-sm font-medium text-success-700">
      {t('admin.saved')}
    </p>
  );
}
