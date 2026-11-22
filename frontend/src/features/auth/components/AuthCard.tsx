import type { ReactNode } from 'react';

interface AuthCardProps {
  title: string;
  children: ReactNode;
}

export function AuthCard({ title, children }: AuthCardProps) {
  return (
    <section className="mx-auto w-full max-w-md rounded-[var(--radius-card)] border border-border bg-surface p-6 shadow-sm">
      <h1 className="mb-4 text-2xl font-bold text-ink-900">{title}</h1>
      {children}
    </section>
  );
}

export function FormAlert({
  children,
  tone = 'danger',
}: {
  children: ReactNode;
  tone?: 'danger' | 'success';
}) {
  const color =
    tone === 'danger' ? 'text-danger-700 border-danger-700' : 'text-success-700 border-success-700';
  return (
    <div
      role={tone === 'danger' ? 'alert' : 'status'}
      className={`rounded-md border px-3 py-2 text-sm ${color}`}
    >
      {children}
    </div>
  );
}

export function SubmitButton({ pending, children }: { pending: boolean; children: ReactNode }) {
  return (
    <button
      type="submit"
      disabled={pending}
      aria-busy={pending || undefined}
      className="rounded-md bg-accent-700 px-4 py-2 font-semibold text-on-accent hover:bg-accent-strong focus:outline-2 focus:outline-offset-2 focus:outline-accent-600 disabled:opacity-60"
    >
      {children}
    </button>
  );
}
