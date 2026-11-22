import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';

import { Badge } from '../../features/admin/components/AdminUi';
import { STAFF_POLLING_MS, useAdminOrdersQuery } from '../../features/admin/opsApi';
import { Price } from '../../features/catalog/components/Price';
import { formatDateTime } from '../../features/checkout/messages';
import { StatusBadge } from '../../features/orders/components/StatusBadge';
import { EmptyState, ErrorState } from '../../shared/components/StateViews';
import { useLanguage } from '../../shared/i18n/useLanguage';

const STATUSES = [
  'pending',
  'confirmed',
  'preparing',
  'ready_for_pickup',
  'out_for_delivery',
  'completed',
  'rejected',
  'cancelled',
];

/** Work queue of orders (API §9): unpaid mock_card orders only with the
 * explicit "awaiting payment" filter, without actions (DEC-97). */
export function AdminOrdersPage() {
  const { t } = useTranslation();
  const language = useLanguage();
  const [status, setStatus] = useState('');
  const [deliveryType, setDeliveryType] = useState('');
  const [number, setNumber] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [awaiting, setAwaiting] = useState(false);
  const [page, setPage] = useState(1);
  const orders = useAdminOrdersQuery(
    {
      status: status || undefined,
      deliveryType: deliveryType || undefined,
      number: number.trim() || undefined,
      dateFrom: dateFrom || undefined,
      dateTo: dateTo || undefined,
      awaitingPayment: awaiting,
      page,
    },
    { pollingInterval: STAFF_POLLING_MS },
  );
  const field = 'min-h-11 rounded-lg border border-border bg-surface px-3';
  const reset = (fn: () => void) => {
    fn();
    setPage(1);
  };

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-2xl font-extrabold">{t('admin.sections.orders')}</h1>
        <p className="text-sm text-ink-600">{t('admin.orders.intro')}</p>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <label className="flex flex-col gap-1 text-sm font-medium">
          {t('admin.orders.status')}
          <select
            className={field}
            value={status}
            onChange={(e) => reset(() => setStatus(e.target.value))}
          >
            <option value="">{t('admin.orders.allStatuses')}</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {t(`orders.status.${s}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm font-medium">
          {t('admin.orders.type')}
          <select
            className={field}
            value={deliveryType}
            onChange={(e) => reset(() => setDeliveryType(e.target.value))}
          >
            <option value="">{t('admin.orders.allTypes')}</option>
            <option value="delivery">{t('orders.deliveryType.delivery')}</option>
            <option value="pickup">{t('orders.deliveryType.pickup')}</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm font-medium">
          {t('admin.orders.number')}
          <input
            type="search"
            className={field}
            value={number}
            placeholder="OSH-000123"
            onChange={(e) => reset(() => setNumber(e.target.value))}
          />
        </label>
        <label className="flex flex-col gap-1 text-sm font-medium">
          {t('admin.dashboard.dateFrom')}
          <input
            type="date"
            className={field}
            value={dateFrom}
            onChange={(e) => reset(() => setDateFrom(e.target.value))}
          />
        </label>
        <label className="flex flex-col gap-1 text-sm font-medium">
          {t('admin.dashboard.dateTo')}
          <input
            type="date"
            className={field}
            value={dateTo}
            onChange={(e) => reset(() => setDateTo(e.target.value))}
          />
        </label>
        <label className="flex items-center gap-2 self-end text-sm font-medium">
          <input
            type="checkbox"
            className="h-4 w-4 accent-accent-700"
            checked={awaiting}
            onChange={(e) => reset(() => setAwaiting(e.target.checked))}
          />
          {t('admin.orders.awaitingFilter')}
        </label>
      </div>
      {awaiting && (
        <p className="rounded-xl bg-cream-100 px-4 py-2 text-sm">
          {t('admin.orders.awaitingNote')}
        </p>
      )}

      {orders.isError ? (
        <ErrorState
          title={t('admin.loadError')}
          text={t('menu.errorText')}
          onRetry={() => void orders.refetch()}
        />
      ) : orders.isLoading ? (
        <p role="status" className="text-ink-600">
          {t('admin.loading')}
        </p>
      ) : !orders.data || orders.data.items.length === 0 ? (
        <EmptyState title={t('admin.orders.emptyTitle')} text={t('admin.orders.emptyText')} />
      ) : (
        <>
          <ul className="flex flex-col gap-3" aria-label={t('admin.sections.orders')}>
            {orders.data.items.map((order) => (
              <li key={order.id}>
                <Link
                  to={`/admin/orders/${order.id}`}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-border bg-surface p-4 transition hover:border-accent-600"
                >
                  <div className="min-w-0">
                    <p className="font-bold">{order.order_number}</p>
                    <p className="text-sm text-ink-600">
                      {formatDateTime(order.created_at, language)} ·{' '}
                      {t(`orders.deliveryType.${order.delivery_type}`)} · {order.customer_name}
                      {order.courier_name &&
                        ` · ${t('admin.orders.courierOf', { name: order.courier_name })}`}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {order.needs_courier && (
                      <Badge tone="danger">{t('admin.orders.needsCourier')}</Badge>
                    )}
                    {order.has_pending_cancellation && (
                      <Badge tone="danger">{t('admin.orders.cancellationPending')}</Badge>
                    )}
                    {order.awaiting_payment && (
                      <Badge tone="muted">{t('admin.orders.awaitingBadge')}</Badge>
                    )}
                    <StatusBadge status={order.status} />
                    <span className="font-semibold">
                      <Price amount={order.total_amount} />
                    </span>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
          {orders.data.pagination.pages > 1 && (
            <nav
              aria-label={t('orders.pagesLabel')}
              className="flex items-center justify-center gap-3"
            >
              <button
                type="button"
                className="min-h-11 rounded-full px-4 ring-1 ring-border disabled:opacity-50"
                disabled={page <= 1}
                onClick={() => setPage(page - 1)}
              >
                {t('orders.prev')}
              </button>
              <span className="text-sm">
                {t('orders.page', { page, pages: orders.data.pagination.pages })}
              </span>
              <button
                type="button"
                className="min-h-11 rounded-full px-4 ring-1 ring-border disabled:opacity-50"
                disabled={page >= orders.data.pagination.pages}
                onClick={() => setPage(page + 1)}
              >
                {t('orders.next')}
              </button>
            </nav>
          )}
        </>
      )}
    </div>
  );
}
