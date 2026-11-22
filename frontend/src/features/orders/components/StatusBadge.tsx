import { useTranslation } from 'react-i18next';

const TONES: Record<string, string> = {
  pending: 'bg-cream-100 text-ink-900',
  confirmed: 'bg-accent-50 text-accent-800',
  preparing: 'bg-accent-50 text-accent-800',
  ready_for_pickup: 'bg-accent-100 text-accent-800',
  out_for_delivery: 'bg-accent-100 text-accent-800',
  completed: 'bg-success-50 text-success-700',
  rejected: 'bg-danger-50 text-danger-700',
  cancelled: 'bg-danger-50 text-danger-700',
};

/** Order status as words, never colour only (UI_UX_GUIDELINES §9). */
export function StatusBadge({ status }: { status: string }) {
  const { t } = useTranslation();
  return (
    <span
      className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${TONES[status] ?? 'bg-cream-100'}`}
    >
      {t(`orders.status.${status}`, { defaultValue: status })}
    </span>
  );
}
