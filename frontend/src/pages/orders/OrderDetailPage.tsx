import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router';

import { Price } from '../../features/catalog/components/Price';
import { formatDateTime } from '../../features/checkout/messages';
import { LIMITS } from '../../features/checkout/schema';
import { StatusBadge } from '../../features/orders/components/StatusBadge';
import { PaymentAttempts } from '../../features/payments/components/PaymentAttempts';
import { useNow } from '../../features/payments/useNow';
import {
  ORDER_POLLING_MS,
  useGetOrderQuery,
  useRequestCancellationMutation,
} from '../../features/orders/ordersApi';
import { apiErrorInfo } from '../../shared/api/errors';
import { EmptyState, ErrorState } from '../../shared/components/StateViews';
import { useLanguage } from '../../shared/i18n/useLanguage';
import type { OrderDetail } from '../../shared/types/api';

// overflow-wrap:anywhere (inherited): a long word in a comment, address or
// reason wraps instead of widening the box and scrolling the page sideways.
const BOX =
  'rounded-card border border-border bg-surface p-5 shadow-[var(--shadow-card)] [overflow-wrap:anywhere]';

function CancellationForm({ order }: { order: OrderDetail }) {
  const { t } = useTranslation();
  const id = useId();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');
  const [request, state] = useRequestCancellationMutation();
  const code = apiErrorInfo(state.error)?.code;
  const trimmed = reason.trim();

  if (!open) {
    return (
      <button
        type="button"
        className="min-h-11 self-start rounded-full px-5 font-semibold text-danger-700 ring-1 ring-border hover:bg-danger-50"
        onClick={() => setOpen(true)}
      >
        {t('orders.cancel.open')}
      </button>
    );
  }
  return (
    <form
      noValidate
      className="flex flex-col gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        if (!trimmed) {
          return;
        }
        void request({ orderId: order.id, body: { reason: trimmed } })
          .unwrap()
          .then(() => {
            setOpen(false);
            setReason('');
          })
          .catch(() => undefined);
      }}
    >
      <label htmlFor={id} className="text-sm font-medium">
        {t('orders.cancel.reason')}
      </label>
      <textarea
        id={id}
        rows={3}
        maxLength={LIMITS.cancellationReason}
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        className="rounded-md border border-border bg-surface px-3 py-2"
      />
      <p className="text-xs text-ink-600">{t('orders.cancel.hint')}</p>
      {code && (
        <p role="alert" className="text-sm text-danger-700">
          {t(`orders.cancel.errors.${code}`, {
            defaultValue: t(`errors.codes.${code}`, { defaultValue: t('errors.codes.default') }),
          })}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          type="submit"
          disabled={!trimmed || state.isLoading}
          className="min-h-11 rounded-full bg-danger-strong px-5 font-semibold text-on-accent disabled:opacity-60"
        >
          {state.isLoading ? t('orders.cancel.sending') : t('orders.cancel.send')}
        </button>
        <button
          type="button"
          className="min-h-11 rounded-full px-5 font-semibold ring-1 ring-border"
          onClick={() => setOpen(false)}
        >
          {t('cart.cancel')}
        </button>
      </div>
    </form>
  );
}

/** `/orders/:orderId`: snapshot of the order, payment, history and the
 * cancellation request; refreshed every 20 s (DEC-74). The customer never changes the status himself. */
export function OrderDetailPage() {
  const { t } = useTranslation();
  const language = useLanguage();
  const { orderId = '' } = useParams();
  const order = useGetOrderQuery(orderId, { pollingInterval: ORDER_POLLING_MS });
  const now = useNow();

  const back = (
    <Link to="/orders" className="text-sm font-semibold text-accent-800 hover:underline">
      ← {t('orders.back')}
    </Link>
  );
  if (order.isLoading) {
    return (
      <p role="status" className="text-ink-600">
        {t('orders.loading')}
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
            title={t('orders.errorTitle')}
            text={t('menu.errorText')}
            onRetry={() => void order.refetch()}
            retrying={order.isFetching}
          />
        )}
      </div>
    );
  }

  const data = order.data;
  // mock_card waiting for payment within its deadline (DEC-97, DEC-149).
  const awaitingPayment =
    data.payment_method_code === 'mock_card' &&
    data.status === 'pending' &&
    data.payment_status === 'pending' &&
    data.payment_due_at !== null &&
    new Date(data.payment_due_at).getTime() > now;
  const pendingRequest = data.cancellation_requests.find((r) => r.status === 'pending');
  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-2">
        {back}
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-3xl font-extrabold tracking-tight">
            {t('orders.number', { number: data.order_number })}
          </h1>
          <StatusBadge status={data.status} />
        </div>
        <p className="text-sm text-ink-600">
          {formatDateTime(data.created_at, language)} ·{' '}
          {t(`orders.deliveryType.${data.delivery_type}`)}
        </p>
        {awaitingPayment ? (
          <div
            role="status"
            className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-accent-50 px-4 py-3 text-sm"
          >
            <span>
              {t('orders.awaitingPayment', {
                when: formatDateTime(data.payment_due_at ?? '', language),
              })}
            </span>
            <Link
              to={`/orders/${data.id}/pay`}
              className="inline-flex min-h-11 items-center rounded-full bg-accent-700 px-5 font-semibold text-white"
            >
              {t('orders.payNow')}
            </Link>
          </div>
        ) : (
          data.status === 'pending' && (
            <p role="status" className="rounded-xl bg-accent-50 px-4 py-3 text-sm">
              {t('orders.placedNote')}
            </p>
          )
        )}
        {data.status === 'cancelled' && data.cancellation_reason_code && (
          <p role="status" className="rounded-xl bg-danger-50 px-4 py-3 text-sm text-danger-700">
            {t(`orders.cancelReason.${data.cancellation_reason_code}`)}
          </p>
        )}
      </header>

      <div className="grid gap-6 lg:grid-cols-[1fr_20rem] lg:items-start">
        <div className="flex flex-col gap-6">
          <section className={BOX} aria-labelledby="order-items">
            <h2 id="order-items" className="mb-3 text-lg font-bold">
              {t('orders.items')}
            </h2>
            <ul className="flex flex-col gap-3">
              {data.items.map((item) => (
                <li
                  key={item.id}
                  className="flex flex-col gap-1 border-b border-border pb-3 last:border-0"
                >
                  <div className="flex justify-between gap-3">
                    <span className="font-semibold">
                      {item.product_name} · {item.variant_name} × {item.quantity}
                    </span>
                    <Price amount={item.total_price} />
                  </div>
                  {item.modifiers.length > 0 && (
                    <ul className="text-sm text-ink-600">
                      {item.modifiers.map((modifier, index) => (
                        <li key={index}>
                          {modifier.group_name}: {modifier.modifier_name}
                          {modifier.quantity > 1 && ` × ${modifier.quantity}`}
                          {Number(modifier.unit_price) > 0 && (
                            <>
                              {' '}
                              (+
                              <Price amount={modifier.unit_price} />)
                            </>
                          )}
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
          </section>

          <section className={BOX} aria-labelledby="order-history">
            <h2 id="order-history" className="mb-3 text-lg font-bold">
              {t('orders.history')}
            </h2>
            <ol className="flex flex-col gap-2">
              {data.status_history.map((entry, index) => (
                <li key={index} className="flex flex-wrap items-center gap-2 text-sm">
                  <StatusBadge status={entry.new_status} />
                  <span className="text-ink-600">{formatDateTime(entry.created_at, language)}</span>
                  {entry.comment && <span>— {entry.comment}</span>}
                </li>
              ))}
            </ol>
          </section>

          <section className={BOX} aria-labelledby="order-cancellation">
            <h2 id="order-cancellation" className="mb-3 text-lg font-bold">
              {t('orders.cancel.title')}
            </h2>
            {data.cancellation_requests.length > 0 && (
              <ul className="mb-3 flex flex-col gap-2 text-sm">
                {data.cancellation_requests.map((request) => (
                  <li key={request.id} className="rounded-xl bg-cream-100 px-3 py-2">
                    <p className="font-semibold">{t(`orders.cancel.status.${request.status}`)}</p>
                    <p>
                      {t('orders.cancel.yourReason')}: {request.reason}
                    </p>
                    {request.admin_comment && (
                      <p>
                        {t('orders.cancel.answer')}: {request.admin_comment}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {data.can_request_cancellation ? (
              <CancellationForm order={data} />
            ) : (
              !pendingRequest && (
                <p className="text-sm text-ink-600">{t('orders.cancel.notAllowed')}</p>
              )
            )}
            <p className="mt-2 text-xs text-ink-600">{t('orders.cancel.note')}</p>
          </section>
        </div>

        <aside className={`${BOX} flex flex-col gap-3`} aria-label={t('orders.summary')}>
          <dl className="flex flex-col gap-1 text-sm">
            <div className="flex justify-between gap-3">
              <dt className="text-ink-600">{t('orders.subtotal')}</dt>
              <dd>
                <Price amount={data.subtotal} />
              </dd>
            </div>
            {data.delivery_type === 'delivery' && (
              <div className="flex justify-between gap-3">
                <dt className="text-ink-600">{t('checkout.quote.delivery')}</dt>
                <dd>
                  <Price amount={data.delivery_fee} />
                </dd>
              </div>
            )}
            <div className="flex items-baseline justify-between gap-3 border-t border-border pt-2">
              <dt className="font-semibold">{t('checkout.quote.total')}</dt>
              <dd className="text-xl font-bold" data-testid="order-total">
                <Price amount={data.total_amount} />
              </dd>
            </div>
          </dl>
          <p className="text-sm">
            {t('orders.payment', {
              method: t(`orders.paymentMethod.${data.payment_method_code}`, {
                defaultValue: data.payment_method_code,
              }),
              status: t(`orders.paymentStatus.${data.payment_status ?? 'none'}`),
            })}
          </p>
          <PaymentAttempts payments={data.payments} />
          {data.address && (
            <div className="text-sm">
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
          <div className="text-sm">
            <p className="font-semibold">{t('checkout.contacts.title')}</p>
            <p>
              {data.customer_name}, {data.customer_phone}
            </p>
            {data.customer_comment && <p className="text-ink-600">{data.customer_comment}</p>}
          </div>
        </aside>
      </div>
    </div>
  );
}
