import { useTranslation } from 'react-i18next';

import { AdminError, BUTTON_PRIMARY } from '../../features/admin/components/AdminUi';
import {
  STAFF_POLLING_MS,
  useKitchenActionMutation,
  useKitchenQueueQuery,
} from '../../features/admin/opsApi';
import { formatDateTime } from '../../features/checkout/messages';
import { StatusBadge } from '../../features/orders/components/StatusBadge';
import { EmptyState, ErrorState } from '../../shared/components/StateViews';
import { useLanguage } from '../../shared/i18n/useLanguage';
import type { KitchenOrderOut } from '../../shared/types/api';

function Ticket({ order }: { order: KitchenOrderOut }) {
  const { t } = useTranslation();
  const language = useLanguage();
  const [act, state] = useKitchenActionMutation();
  const action =
    order.status === 'confirmed' ? 'start' : order.status === 'preparing' ? 'ready' : null;

  return (
    <li className="flex flex-col gap-3 rounded-card border border-border bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-lg font-extrabold">{order.order_number}</p>
        <StatusBadge status={order.status} />
      </div>
      <p className="text-xs text-ink-600">
        {t(`orders.deliveryType.${order.delivery_type}`)}
        {order.confirmed_at &&
          ` · ${t('admin.kitchen.confirmed', { when: formatDateTime(order.confirmed_at, language) })}`}
        {order.preparing_started_at &&
          ` · ${t('admin.kitchen.started', { when: formatDateTime(order.preparing_started_at, language) })}`}
      </p>
      <ul className="flex flex-col gap-2">
        {order.items.map((item, index) => (
          <li key={index} className="rounded-xl bg-cream-100 px-3 py-2">
            <p className="font-semibold">
              {item.quantity} × {item.product_name} · {item.variant_name}
            </p>
            {item.modifiers.length > 0 && (
              <ul className="text-sm">
                {item.modifiers.map((m, i) => (
                  <li key={i}>
                    {m.group_name}: {m.modifier_name}
                    {m.quantity > 1 && ` × ${m.quantity}`}
                  </li>
                ))}
              </ul>
            )}
            {item.special_instructions && (
              <p className="mt-1 rounded-lg bg-accent-50 px-2 py-1 text-sm font-semibold text-accent-800">
                {t('admin.kitchen.wishes')}: {item.special_instructions}
              </p>
            )}
          </li>
        ))}
      </ul>
      <AdminError error={state.error} />
      {action && (
        <button
          type="button"
          className={`${BUTTON_PRIMARY} self-start`}
          disabled={state.isLoading}
          onClick={() => void act({ id: order.id, action })}
        >
          {state.isLoading ? t('admin.saving') : t(`admin.kitchen.${action}`)}
        </button>
      )}
    </li>
  );
}

/** Kitchen queue (DEC-25, DEC-106, DEC-112): items, extras and wishes only —
 * no customer data, comments, amounts or payment. Refreshes every 10 s. */
export function KitchenPage() {
  const { t } = useTranslation();
  const queue = useKitchenQueueQuery(undefined, { pollingInterval: STAFF_POLLING_MS });

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-2xl font-extrabold">{t('admin.sections.kitchen')}</h1>
        <p className="text-sm text-ink-600">{t('admin.kitchen.intro')}</p>
      </header>
      {queue.isError ? (
        <ErrorState
          title={t('admin.loadError')}
          text={t('menu.errorText')}
          onRetry={() => void queue.refetch()}
        />
      ) : queue.isLoading ? (
        <p role="status" className="text-ink-600">
          {t('admin.loading')}
        </p>
      ) : !queue.data || queue.data.items.length === 0 ? (
        <EmptyState title={t('admin.kitchen.emptyTitle')} text={t('admin.kitchen.emptyText')} />
      ) : (
        <ul
          className="grid gap-4 md:grid-cols-2 xl:grid-cols-3"
          aria-label={t('admin.sections.kitchen')}
        >
          {queue.data.items.map((order) => (
            <Ticket key={order.id} order={order} />
          ))}
        </ul>
      )}
    </div>
  );
}
