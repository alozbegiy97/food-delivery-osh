import { useTranslation } from 'react-i18next';
import { Link, useLocation } from 'react-router';

import { AdminError, Toggle } from '../../features/admin/components/AdminUi';
import { Price } from '../../features/catalog/components/Price';
import {
  COURIER_POLLING_MS,
  useCourierMeQuery,
  useCourierOrdersQuery,
  useSetAvailabilityMutation,
} from '../../features/courier/courierApi';
import { StatusBadge } from '../../features/orders/components/StatusBadge';
import { EmptyState, ErrorState } from '../../shared/components/StateViews';

function Availability() {
  const { t } = useTranslation();
  const me = useCourierMeQuery(undefined, { pollingInterval: COURIER_POLLING_MS });
  const [setAvailability, state] = useSetAvailabilityMutation();
  if (!me.data) {
    return null;
  }
  const available = me.data.is_available;
  return (
    <section className="flex flex-col gap-3 rounded-card border border-border bg-surface p-4">
      <Toggle
        label={t('courier.availabilitySwitch')}
        hint={t('courier.availabilityHint')}
        checked={available}
        disabled={state.isLoading}
        onChange={(e) => void setAvailability(e.target.checked)}
      />
      <p className="text-sm text-ink-600">
        {t('courier.load', {
          active: me.data.active_assignments,
          limit: me.data.max_active_orders,
        })}
      </p>
      <AdminError error={state.error} />
    </section>
  );
}

/** Active assignments of the courier (API §10, DEC-106); refresh every 10 s. */
export function CourierHomePage() {
  const { t } = useTranslation();
  const location = useLocation();
  const notice = (location.state as { notice?: string } | null)?.notice;
  const orders = useCourierOrdersQuery(undefined, { pollingInterval: COURIER_POLLING_MS });

  return (
    <div className="flex flex-col gap-4">
      {notice && (
        <p role="status" className="rounded-xl bg-success-50 px-4 py-3 text-sm text-success-700">
          {t(`courier.notice.${notice}`)}
        </p>
      )}
      <Availability />
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
        <EmptyState title={t('courier.emptyTitle')} text={t('courier.emptyText')} />
      ) : (
        <ul className="flex flex-col gap-3" aria-label={t('courier.tabs.active')}>
          {orders.data.items.map((order) => (
            <li key={order.assignment_id}>
              <Link
                to={`/courier/orders/${order.order_id}`}
                className="flex flex-col gap-2 rounded-card border border-border bg-surface p-4 transition hover:border-accent-600"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-lg font-extrabold">{order.order_number}</span>
                  <StatusBadge status={order.status} />
                </div>
                {order.address && <span className="text-sm">{order.address.address_text}</span>}
                <span className="flex flex-wrap items-center justify-between gap-2 text-sm">
                  <span className="font-semibold">
                    {order.amount_to_collect ? (
                      <>
                        {t('courier.toCollect')}: <Price amount={order.amount_to_collect} />
                      </>
                    ) : (
                      t('courier.paidOnline')
                    )}
                  </span>
                  <span className="text-ink-600">
                    {order.accepted_at ? t('courier.accepted') : t('courier.waitingAccept')}
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
