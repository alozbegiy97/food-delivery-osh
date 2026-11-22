import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router';

import {
  AdminError,
  BUTTON_DANGER,
  BUTTON_PRIMARY,
  BUTTON_SECONDARY,
} from '../../features/admin/components/AdminUi';
import { Price } from '../../features/catalog/components/Price';
import {
  COURIER_POLLING_MS,
  useAcceptOrderMutation,
  useCourierOrderQuery,
  useDeclineOrderMutation,
  useDeliverOrderMutation,
  usePickUpOrderMutation,
} from '../../features/courier/courierApi';
import { StatusBadge } from '../../features/orders/components/StatusBadge';
import { EmptyState, ErrorState } from '../../shared/components/StateViews';
import type { CourierOrderOut } from '../../shared/types/api';

const ACTION = 'flex min-h-12 w-full items-center justify-center';

function osmLink(latitude: string, longitude: string): string {
  return `https://www.openstreetmap.org/?mlat=${latitude}&mlon=${longitude}#map=18/${latitude}/${longitude}`;
}

function DeclineForm({ order, onCancel }: { order: CourierOrderOut; onCancel: () => void }) {
  const { t } = useTranslation();
  const id = useId();
  const navigate = useNavigate();
  const [decline, state] = useDeclineOrderMutation();
  const [reason, setReason] = useState('');
  return (
    <form
      role="alertdialog"
      aria-label={t('courier.declineQuestion')}
      className="flex flex-col gap-2 rounded-xl bg-danger-50 p-3"
      onSubmit={(event) => {
        event.preventDefault();
        void decline({ id: order.order_id, reason: reason.trim() || null })
          .unwrap()
          .then(() => navigate('/courier', { state: { notice: 'declined' } }))
          .catch(() => undefined);
      }}
    >
      <p className="text-sm font-semibold text-danger-700">{t('courier.declineQuestion')}</p>
      <label htmlFor={id} className="text-sm font-medium">
        {t('courier.declineReason')}
      </label>
      <textarea
        id={id}
        rows={2}
        maxLength={500}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        className="rounded-md border border-border bg-surface px-3 py-2"
      />
      <AdminError error={state.error} />
      <div className="flex flex-wrap gap-2">
        <button type="submit" className={BUTTON_DANGER} disabled={state.isLoading}>
          {t('courier.declineConfirm')}
        </button>
        <button type="button" className={BUTTON_SECONDARY} onClick={onCancel}>
          {t('admin.cancel')}
        </button>
      </div>
    </form>
  );
}

function Actions({ order }: { order: CourierOrderOut }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [accept, accepting] = useAcceptOrderMutation();
  const [pickUp, picking] = usePickUpOrderMutation();
  const [deliver, delivering] = useDeliverOrderMutation();
  const [declining, setDeclining] = useState(false);
  const [confirmDelivery, setConfirmDelivery] = useState(false);
  const busy = accepting.isLoading || picking.isLoading || delivering.isLoading;
  const accepted = order.accepted_at !== null;
  const pickUpHint = !accepted
    ? t('courier.pickUpNeedsAccept')
    : order.status !== 'ready_for_pickup'
      ? t('courier.pickUpNeedsReady')
      : null;

  if (declining) {
    return <DeclineForm order={order} onCancel={() => setDeclining(false)} />;
  }
  return (
    <div className="flex flex-col gap-3">
      <AdminError error={accepting.error ?? picking.error ?? delivering.error} />
      {order.can_accept && (
        <button
          type="button"
          className={`${BUTTON_PRIMARY} ${ACTION}`}
          disabled={busy}
          onClick={() => void accept(order.order_id)}
        >
          {t('courier.accept')}
        </button>
      )}
      {order.status !== 'out_for_delivery' && (
        <div className="flex flex-col gap-1">
          <button
            type="button"
            className={`${BUTTON_PRIMARY} ${ACTION}`}
            disabled={busy || !order.can_pick_up}
            aria-describedby={pickUpHint ? 'pick-up-hint' : undefined}
            onClick={() => void pickUp(order.order_id)}
          >
            {t('courier.pickUp')}
          </button>
          {pickUpHint && (
            <p id="pick-up-hint" className="text-xs text-ink-600">
              {pickUpHint}
            </p>
          )}
        </div>
      )}
      {order.can_deliver &&
        (confirmDelivery ? (
          <div
            role="alertdialog"
            aria-label={t('courier.deliverQuestion')}
            className="flex flex-col gap-2 rounded-xl bg-cream-100 p-3"
          >
            <p className="text-sm font-semibold">
              {order.amount_to_collect ? (
                <>
                  {t('courier.deliverQuestionCash')} <Price amount={order.amount_to_collect} />
                </>
              ) : (
                t('courier.deliverQuestion')
              )}
            </p>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className={BUTTON_PRIMARY}
                disabled={busy}
                onClick={() =>
                  void deliver(order.order_id)
                    .unwrap()
                    .then(() => navigate('/courier', { state: { notice: 'delivered' } }))
                    .catch(() => undefined)
                }
              >
                {t('courier.deliverConfirm')}
              </button>
              <button
                type="button"
                className={BUTTON_SECONDARY}
                onClick={() => setConfirmDelivery(false)}
              >
                {t('admin.cancel')}
              </button>
            </div>
          </div>
        ) : (
          <button
            type="button"
            className={`${BUTTON_PRIMARY} ${ACTION}`}
            disabled={busy}
            onClick={() => setConfirmDelivery(true)}
          >
            {t('courier.deliver')}
          </button>
        ))}
      {order.can_decline && (
        <button
          type="button"
          className={`${BUTTON_SECONDARY} ${ACTION}`}
          disabled={busy}
          onClick={() => setDeclining(true)}
        >
          {t('courier.decline')}
        </button>
      )}
    </div>
  );
}

/** One active assignment with the data of the delivery (DEC-106). */
export function CourierOrderPage() {
  const { t } = useTranslation();
  const { orderId = '' } = useParams();
  const order = useCourierOrderQuery(orderId, { pollingInterval: COURIER_POLLING_MS });
  const back = (
    <Link
      to="/courier"
      className="self-start text-sm font-semibold text-accent-800 hover:underline"
    >
      ← {t('courier.back')}
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
    const gone = order.error && 'status' in order.error && order.error.status === 404;
    return (
      <div className="flex flex-col gap-4">
        {back}
        {gone ? (
          <EmptyState title={t('courier.goneTitle')} text={t('courier.goneText')} />
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
  const address = data.address;
  const details = address
    ? [
        address.entrance && t('orders.entrance', { value: address.entrance }),
        address.floor && t('orders.floor', { value: address.floor }),
        address.apartment && t('orders.apartment', { value: address.apartment }),
      ].filter(Boolean)
    : [];

  return (
    <div className="flex flex-col gap-4">
      {back}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-xl font-extrabold">{data.order_number}</h2>
        <StatusBadge status={data.status} />
      </div>

      <section className="flex flex-col gap-1 rounded-card border border-border bg-surface p-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-ink-600">
          {t('courier.payment')}
        </p>
        {data.amount_to_collect ? (
          <p className="text-2xl font-extrabold">
            {t('courier.toCollect')}: <Price amount={data.amount_to_collect} />
          </p>
        ) : (
          <p className="text-lg font-bold text-success-700">
            {t('courier.paidOnline')} · <Price amount={data.total_amount} />
          </p>
        )}
      </section>

      {address && (
        <section className="flex flex-col gap-1 rounded-card border border-border bg-surface p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-ink-600">
            {t('courier.address')}
          </p>
          <p className="font-semibold">{address.address_text}</p>
          {details.length > 0 && <p className="text-sm">{details.join(', ')}</p>}
          {address.comment && (
            <p className="text-sm text-ink-600">
              {t('courier.addressComment')}: {address.comment}
            </p>
          )}
          <a
            href={osmLink(address.latitude, address.longitude)}
            target="_blank"
            rel="noreferrer"
            className="mt-1 self-start text-sm font-semibold text-accent-800 underline"
          >
            {t('courier.openMap')}
          </a>
        </section>
      )}

      <section className="flex flex-col gap-1 rounded-card border border-border bg-surface p-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-ink-600">
          {t('courier.customer')}
        </p>
        <p className="font-semibold">{data.customer_name}</p>
        <a
          href={`tel:${data.customer_phone}`}
          className="self-start font-semibold text-accent-800 underline"
        >
          {data.customer_phone}
        </a>
        {data.customer_comment && <p className="text-sm text-ink-600">«{data.customer_comment}»</p>}
      </section>

      <section className="flex flex-col gap-2 rounded-card border border-border bg-surface p-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-ink-600">
          {t('orders.items')}
        </p>
        <ul className="flex flex-col gap-2">
          {data.items.map((item, index) => (
            <li key={index} className="text-sm">
              <span className="font-semibold">
                {item.quantity} × {item.product_name} · {item.variant_name}
              </span>
              {item.modifiers.length > 0 && (
                <span className="block text-ink-600">
                  {item.modifiers
                    .map(
                      (m) =>
                        `${m.group_name}: ${m.modifier_name}${m.quantity > 1 ? ` × ${m.quantity}` : ''}`,
                    )
                    .join('; ')}
                </span>
              )}
              {item.special_instructions && (
                <span className="block">
                  {t('cart.instructions')}: {item.special_instructions}
                </span>
              )}
            </li>
          ))}
        </ul>
      </section>

      <Actions key={`${data.status}-${data.accepted_at}`} order={data} />
    </div>
  );
}
