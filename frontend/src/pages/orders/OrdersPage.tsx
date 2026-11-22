import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';

import { Price } from '../../features/catalog/components/Price';
import { formatDateTime } from '../../features/checkout/messages';
import { StatusBadge } from '../../features/orders/components/StatusBadge';
import { ORDER_POLLING_MS, useGetOrdersQuery } from '../../features/orders/ordersApi';
import { EmptyState, ErrorState } from '../../shared/components/StateViews';
import { useLanguage } from '../../shared/i18n/useLanguage';

/** `/orders`: the customer's orders, newest first (API §6.3, DEC-148). */
export function OrdersPage() {
  const { t } = useTranslation();
  const language = useLanguage();
  const [page, setPage] = useState(1);
  const orders = useGetOrdersQuery({ page }, { pollingInterval: ORDER_POLLING_MS });
  const heading = <h1 className="text-3xl font-extrabold tracking-tight">{t('orders.title')}</h1>;

  if (orders.isLoading) {
    return (
      <div className="flex flex-col gap-6" aria-busy="true">
        {heading}
        <p role="status" className="text-ink-600">
          {t('orders.loading')}
        </p>
      </div>
    );
  }
  if (orders.isError || !orders.data) {
    return (
      <div className="flex flex-col gap-6">
        {heading}
        <ErrorState
          title={t('orders.errorTitle')}
          text={t('menu.errorText')}
          onRetry={() => void orders.refetch()}
          retrying={orders.isFetching}
        />
      </div>
    );
  }
  const { items, pagination } = orders.data;
  if (items.length === 0) {
    return (
      <div className="flex flex-col gap-6">
        {heading}
        <EmptyState
          title={t('orders.emptyTitle')}
          text={t('orders.emptyText')}
          action={
            <Link
              to="/menu"
              className="inline-flex min-h-11 items-center rounded-full bg-accent-700 px-6 font-semibold text-white"
            >
              {t('cart.toMenu')}
            </Link>
          }
        />
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-6">
      {heading}
      <ul className="flex flex-col gap-3" aria-label={t('orders.listLabel')}>
        {items.map((order) => (
          <li key={order.id}>
            <Link
              to={`/orders/${order.id}`}
              className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-border bg-surface p-4 transition hover:border-accent-600"
            >
              <div>
                <p className="font-bold">{order.order_number}</p>
                <p className="text-sm text-ink-600">
                  {formatDateTime(order.created_at, language)} ·{' '}
                  {t(`orders.deliveryType.${order.delivery_type}`)} ·{' '}
                  {t('orders.itemsCount', { count: order.items_count })}
                </p>
              </div>
              <div className="flex items-center gap-3">
                <StatusBadge status={order.status} />
                <span className="font-semibold">
                  <Price amount={order.total_amount} />
                </span>
              </div>
            </Link>
          </li>
        ))}
      </ul>
      {pagination.pages > 1 && (
        <nav aria-label={t('orders.pagesLabel')} className="flex items-center justify-center gap-3">
          <button
            type="button"
            className="min-h-11 rounded-full px-4 font-semibold ring-1 ring-border disabled:opacity-50"
            disabled={page <= 1}
            onClick={() => setPage(page - 1)}
          >
            {t('orders.prev')}
          </button>
          <span className="text-sm">{t('orders.page', { page, pages: pagination.pages })}</span>
          <button
            type="button"
            className="min-h-11 rounded-full px-4 font-semibold ring-1 ring-border disabled:opacity-50"
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
