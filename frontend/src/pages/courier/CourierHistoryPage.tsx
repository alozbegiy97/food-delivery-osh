import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Badge } from '../../features/admin/components/AdminUi';
import { Price } from '../../features/catalog/components/Price';
import { formatDateTime } from '../../features/checkout/messages';
import { useCourierHistoryQuery } from '../../features/courier/courierApi';
import { EmptyState, ErrorState } from '../../shared/components/StateViews';
import { useLanguage } from '../../shared/i18n/useLanguage';

/** Completed and declined assignments: number, date, amount and payment
 * method only — no address or contacts (DEC-106). */
export function CourierHistoryPage() {
  const { t } = useTranslation();
  const language = useLanguage();
  const [page, setPage] = useState(1);
  const history = useCourierHistoryQuery(page);

  if (history.isError) {
    return (
      <ErrorState
        title={t('admin.loadError')}
        text={t('menu.errorText')}
        onRetry={() => void history.refetch()}
      />
    );
  }
  if (history.isLoading || !history.data) {
    return (
      <p role="status" className="text-ink-600">
        {t('admin.loading')}
      </p>
    );
  }
  const { items, pagination } = history.data;
  if (items.length === 0) {
    return (
      <EmptyState title={t('courier.historyEmptyTitle')} text={t('courier.historyEmptyText')} />
    );
  }
  return (
    <div className="flex flex-col gap-4">
      <ul className="flex flex-col gap-2" aria-label={t('courier.tabs.history')}>
        {items.map((item) => (
          <li
            key={item.assignment_id}
            className="flex flex-wrap items-center justify-between gap-2 rounded-card border border-border bg-surface p-4"
          >
            <div>
              <p className="font-bold">{item.order_number}</p>
              <p className="text-sm text-ink-600">
                {item.finished_at ? formatDateTime(item.finished_at, language) : '—'} ·{' '}
                {t(`courier.method.${item.payment_method_code}`, {
                  defaultValue: item.payment_method_code,
                })}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Badge tone={item.assignment_status === 'completed' ? 'success' : 'muted'}>
                {t(`courier.assignment.${item.assignment_status}`)}
              </Badge>
              <span className="font-semibold">
                <Price amount={item.total_amount} />
              </span>
            </div>
          </li>
        ))}
      </ul>
      {pagination.pages > 1 && (
        <nav aria-label={t('orders.pagesLabel')} className="flex items-center justify-center gap-3">
          <button
            type="button"
            className="min-h-11 rounded-full px-4 ring-1 ring-border disabled:opacity-50"
            disabled={page <= 1}
            onClick={() => setPage(page - 1)}
          >
            {t('orders.prev')}
          </button>
          <span className="text-sm">{t('orders.page', { page, pages: pagination.pages })}</span>
          <button
            type="button"
            className="min-h-11 rounded-full px-4 ring-1 ring-border disabled:opacity-50"
            disabled={page >= pagination.pages}
            onClick={() => setPage(page + 1)}
          >
            {t('orders.next')}
          </button>
        </nav>
      )}
    </div>
  );
}
