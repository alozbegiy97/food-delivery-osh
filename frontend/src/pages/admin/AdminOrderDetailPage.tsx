import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router';

import {
  AdminError,
  AdminSection,
  Badge,
  BUTTON_DANGER,
  BUTTON_PRIMARY,
  BUTTON_SECONDARY,
} from '../../features/admin/components/AdminUi';
import { CourierPanel } from '../../features/admin/components/CourierPanel';
import {
  STAFF_POLLING_MS,
  useAdminOrderQuery,
  useChangeOrderStatusMutation,
} from '../../features/admin/opsApi';
import { Price } from '../../features/catalog/components/Price';
import { formatDateTime } from '../../features/checkout/messages';
import { StatusBadge } from '../../features/orders/components/StatusBadge';
import { PaymentAttempts } from '../../features/payments/components/PaymentAttempts';
import { EmptyState, ErrorState } from '../../shared/components/StateViews';
import { useLanguage } from '../../shared/i18n/useLanguage';

// Rejecting and cancelling need a reason (DEC-132) and a confirmation; the
// courier transitions of a delivery are an administrator override with a
// warning and a required comment (DEC-91, UI_UX_GUIDELINES §4).
const NEEDS_REASON = new Set(['rejected', 'cancelled']);
const COURIER_TRANSITIONS = new Set(['out_for_delivery', 'completed']);

function StatusAction({
  orderId,
  status,
  deliveryType,
}: {
  orderId: string;
  status: string;
  deliveryType: string;
}) {
  const { t } = useTranslation();
  const id = useId();
  const [change, state] = useChangeOrderStatusMutation();
  const [asking, setAsking] = useState(false);
  const [comment, setComment] = useState('');
  const override = deliveryType === 'delivery' && COURIER_TRANSITIONS.has(status);
  const dangerous = NEEDS_REASON.has(status) || override;
  const label = override
    ? t(`admin.orders.overrideActions.${status}`)
    : t(`admin.orders.actions.${status}`);

  if (!dangerous) {
    return (
      <div className="flex flex-col gap-1">
        <button
          type="button"
          className={BUTTON_PRIMARY}
          disabled={state.isLoading}
          onClick={() => void change({ id: orderId, body: { status: status as never } })}
        >
          {state.isLoading ? t('admin.saving') : label}
        </button>
        <AdminError error={state.error} />
      </div>
    );
  }
  if (!asking) {
    return (
      <button type="button" className={BUTTON_SECONDARY} onClick={() => setAsking(true)}>
        {label}
      </button>
    );
  }
  return (
    <form
      role="alertdialog"
      aria-label={label}
      className="flex w-full flex-col gap-2 rounded-xl bg-danger-50 p-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (!comment.trim()) {
          return;
        }
        void change({ id: orderId, body: { status: status as never, comment: comment.trim() } })
          .unwrap()
          .then(() => setAsking(false))
          .catch(() => undefined);
      }}
    >
      {override && (
        <p className="text-sm font-semibold text-danger-700">{t('admin.orders.overrideWarning')}</p>
      )}
      <label htmlFor={id} className="text-sm font-medium text-danger-700">
        {override ? t('admin.orders.overrideComment') : t('admin.orders.reason')}
      </label>
      <textarea
        id={id}
        rows={2}
        maxLength={500}
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        className="rounded-md border border-border bg-surface px-3 py-2"
      />
      <AdminError error={state.error} />
      <div className="flex flex-wrap gap-2">
        <button
          type="submit"
          className={BUTTON_DANGER}
          disabled={!comment.trim() || state.isLoading}
        >
          {t('admin.orders.confirmAction', { action: label })}
        </button>
        <button type="button" className={BUTTON_SECONDARY} onClick={() => setAsking(false)}>
          {t('admin.cancel')}
        </button>
      </div>
    </form>
  );
}

/** Order card of the administrator: customer, items, payments, history,
 * cancellation requests and the allowed status actions (DEC-150). */
export function AdminOrderDetailPage() {
  const { t } = useTranslation();
  const language = useLanguage();
  const { orderId = '' } = useParams();
  const order = useAdminOrderQuery(orderId, { pollingInterval: STAFF_POLLING_MS });

  const back = (
    <Link
      to="/admin/orders"
      className="self-start text-sm font-semibold text-accent-800 hover:underline"
    >
      ← {t('admin.orders.back')}
    </Link>
  );
  if (order.isLoading) {
    return (
      <p role="status" className="text-ink-600">
        {t('admin.loading')}
      </p>
    );
  }
  if (order.isError || !order.data) {
    const notFound = order.error && 'status' in order.error && order.error.status === 404;
    return (
      <div className="flex flex-col gap-4">
        {back}
        {notFound ? (
          <EmptyState title={t('orders.notFoundTitle')} text={t('orders.notFoundText')} />
        ) : (
          <ErrorState
            title={t('admin.loadError')}
            text={t('menu.errorText')}
            onRetry={() => void order.refetch()}
          />
        )}
      </div>
    );
  }
  const data = order.data;

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-2">
        {back}
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-extrabold">
            {t('orders.number', { number: data.order_number })}
          </h1>
          <StatusBadge status={data.status} />
          {data.awaiting_payment && <Badge tone="muted">{t('admin.orders.awaitingBadge')}</Badge>}
        </div>
        <p className="text-sm text-ink-600">
          {formatDateTime(data.created_at, language)} ·{' '}
          {t(`orders.deliveryType.${data.delivery_type}`)}
          {data.delivery_zone_name && ` · ${data.delivery_zone_name}`}
          {data.delivered_at &&
            ` · ${t('admin.orders.deliveredAt', { when: formatDateTime(data.delivered_at, language) })}`}
        </p>
      </header>

      <AdminSection title={t('admin.orders.actionsTitle')}>
        {data.awaiting_payment ? (
          <p className="text-sm text-ink-600">{t('admin.orders.awaitingNote')}</p>
        ) : data.allowed_statuses.length === 0 ? (
          <p className="text-sm text-ink-600">{t('admin.orders.noActions')}</p>
        ) : (
          <div
            className="flex flex-wrap items-start gap-3"
            aria-label={t('admin.orders.actionsTitle')}
          >
            {data.allowed_statuses.map((status) => (
              <StatusAction
                key={status}
                orderId={data.id}
                status={status}
                deliveryType={data.delivery_type}
              />
            ))}
          </div>
        )}
      </AdminSection>

      {data.delivery_type === 'delivery' &&
        (data.can_assign_courier || data.assignments.length > 0) && <CourierPanel order={data} />}

      <div className="grid gap-6 lg:grid-cols-[1fr_20rem] lg:items-start">
        <div className="flex flex-col gap-6">
          <AdminSection title={t('orders.items')}>
            <ul className="flex flex-col gap-3">
              {data.items.map((item) => (
                <li key={item.id} className="border-b border-border pb-3 last:border-0">
                  <div className="flex justify-between gap-3">
                    <span className="font-semibold">
                      {item.product_name} · {item.variant_name} × {item.quantity}
                    </span>
                    <Price amount={item.total_price} />
                  </div>
                  {item.modifiers.length > 0 && (
                    <ul className="text-sm text-ink-600">
                      {item.modifiers.map((m, i) => (
                        <li key={i}>
                          {m.group_name}: {m.modifier_name}
                          {m.quantity > 1 && ` × ${m.quantity}`}
                        </li>
                      ))}
                    </ul>
                  )}
                  {item.special_instructions && (
                    <p className="text-sm">
                      <span className="font-medium">{t('cart.instructions')}:</span>{' '}
                      {item.special_instructions}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          </AdminSection>

          <AdminSection title={t('orders.history')}>
            <ol className="flex flex-col gap-2 text-sm">
              {data.admin_history.map((entry, index) => (
                <li key={index} className="flex flex-wrap items-center gap-2">
                  <StatusBadge status={entry.new_status} />
                  <span className="text-ink-600">{formatDateTime(entry.created_at, language)}</span>
                  {entry.changed_by_name && <span>· {entry.changed_by_name}</span>}
                  {entry.is_admin_override && (
                    <Badge tone="accent">{t('admin.orders.override')}</Badge>
                  )}
                  {entry.comment && <span>— {entry.comment}</span>}
                </li>
              ))}
            </ol>
          </AdminSection>

          {data.cancellation_requests.length > 0 && (
            <AdminSection title={t('orders.cancel.title')}>
              <ul className="flex flex-col gap-2 text-sm">
                {data.cancellation_requests.map((r) => (
                  <li key={r.id} className="rounded-xl bg-cream-100 px-3 py-2">
                    <p className="font-semibold">{t(`orders.cancel.status.${r.status}`)}</p>
                    <p>
                      {t('orders.cancel.yourReason')}: {r.reason}
                    </p>
                    {r.admin_comment && (
                      <p>
                        {t('orders.cancel.answer')}: {r.admin_comment}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
              <Link
                to="/admin/cancellations"
                className="mt-2 inline-block text-sm font-semibold text-accent-800 underline"
              >
                {t('admin.orders.toRequests')}
              </Link>
            </AdminSection>
          )}
        </div>

        <aside className="flex flex-col gap-4">
          <AdminSection title={t('admin.orders.customer')}>
            <dl className="flex flex-col gap-1 text-sm">
              <dd className="font-semibold">{data.customer_name}</dd>
              <dd>{data.customer_phone}</dd>
              {data.customer_email && <dd className="text-ink-600">{data.customer_email}</dd>}
              {data.customer_comment && <dd className="text-ink-600">«{data.customer_comment}»</dd>}
            </dl>
            {data.address && (
              <div className="mt-3 text-sm">
                <p className="font-semibold">{t('checkout.address.title')}</p>
                <p>{data.address.address_text}</p>
                <p className="text-ink-600">
                  {[
                    data.address.entrance && t('orders.entrance', { value: data.address.entrance }),
                    data.address.floor && t('orders.floor', { value: data.address.floor }),
                    data.address.apartment &&
                      t('orders.apartment', { value: data.address.apartment }),
                  ]
                    .filter(Boolean)
                    .join(', ')}
                </p>
                {data.address.comment && <p className="text-ink-600">{data.address.comment}</p>}
              </div>
            )}
          </AdminSection>
          <AdminSection title={t('orders.summary')}>
            <dl className="flex flex-col gap-1 text-sm">
              <div className="flex justify-between">
                <dt className="text-ink-600">{t('orders.subtotal')}</dt>
                <dd>
                  <Price amount={data.subtotal} />
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-600">{t('checkout.quote.delivery')}</dt>
                <dd>
                  <Price amount={data.delivery_fee} />
                </dd>
              </div>
              <div className="flex justify-between border-t border-border pt-1 font-bold">
                <dt>{t('checkout.quote.total')}</dt>
                <dd data-testid="admin-order-total">
                  <Price amount={data.total_amount} />
                </dd>
              </div>
            </dl>
            <div className="mt-3">
              <PaymentAttempts payments={data.payments} />
            </div>
          </AdminSection>
        </aside>
      </div>
    </div>
  );
}
