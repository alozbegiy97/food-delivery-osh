import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router';

import { Price } from '../../features/catalog/components/Price';
import { formatDateTime } from '../../features/checkout/messages';
import { StatusBadge } from '../../features/orders/components/StatusBadge';
import { ORDER_POLLING_MS, useGetOrderQuery } from '../../features/orders/ordersApi';
import { PaymentAttempts } from '../../features/payments/components/PaymentAttempts';
import { useConfirmMockPaymentMutation } from '../../features/payments/paymentsApi';
import { useNow } from '../../features/payments/useNow';
import { useTelegramClosingConfirmation } from '../../features/telegram/useTelegramClosingConfirmation';
import { apiErrorInfo } from '../../shared/api/errors';
import { EmptyState, ErrorState } from '../../shared/components/StateViews';
import { useLanguage } from '../../shared/i18n/useLanguage';
import type { MockConfirmOut } from '../../shared/types/api';

const BOX = 'rounded-card border border-border bg-surface p-5 shadow-[var(--shadow-card)]';

function formatLeft(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}

/**
 * `/orders/:orderId/pay` — demonstration card payment (UI_UX_GUIDELINES §3
 * "Mock payment", DEC-47, DEC-149). No card fields at all: the customer only
 * chooses the simulated outcome. Buttons are locked while a request runs;
 * success is shown only after the server confirmed it; a repeat after a lost
 * answer uses the same attempt id and gets the stored result.
 */
export function PayPage() {
  const { t } = useTranslation();
  const language = useLanguage();
  const { orderId = '' } = useParams();
  const order = useGetOrderQuery(orderId, { pollingInterval: ORDER_POLLING_MS });
  const [confirm, confirming] = useConfirmMockPaymentMutation();
  const [result, setResult] = useState<MockConfirmOut | null>(null);
  const now = useNow();

  // Mini App only (no-op on the site): ask before closing only while an
  // existing mock_card order still awaits payment before its deadline;
  // off while loading, on errors, after success, cancellation or expiry.
  const current = order.data;
  useTelegramClosingConfirmation(
    !order.isError &&
      current !== undefined &&
      current.payment_method_code === 'mock_card' &&
      current.status === 'pending' &&
      current.payment_status !== 'succeeded' &&
      current.payment_status !== 'refunded' &&
      result?.payment_status !== 'succeeded' &&
      current.payment_due_at !== null &&
      new Date(current.payment_due_at).getTime() > now,
  );

  const back = (
    <Link
      to={`/orders/${orderId}`}
      className="text-sm font-semibold text-accent-800 hover:underline"
    >
      ← {t('payments.toOrder')}
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
    return notFound ? (
      <EmptyState title={t('orders.notFoundTitle')} text={t('orders.notFoundText')} />
    ) : (
      <ErrorState
        title={t('orders.errorTitle')}
        text={t('menu.errorText')}
        onRetry={() => void order.refetch()}
        retrying={order.isFetching}
      />
    );
  }

  const data = order.data;
  const heading = (
    <header className="flex flex-col gap-2">
      {back}
      <h1 className="text-3xl font-extrabold tracking-tight">{t('payments.title')}</h1>
      <p className="flex flex-wrap items-center gap-2 text-sm">
        {t('orders.number', { number: data.order_number })} <StatusBadge status={data.status} />
      </p>
    </header>
  );

  if (data.payment_method_code !== 'mock_card') {
    return (
      <div className="flex flex-col gap-6">
        {heading}
        <EmptyState title={t('payments.notCardTitle')} text={t('payments.notCardText')} />
      </div>
    );
  }

  const paid = data.payment_status === 'succeeded' || data.payment_status === 'refunded';
  const due = data.payment_due_at ? new Date(data.payment_due_at).getTime() : null;
  const expired = !paid && (data.status !== 'pending' || due === null || due <= now);
  const attempt = data.payments.find((p) => p.status === 'pending' && p.is_simulated);
  const busy = confirming.isLoading || order.isFetching;
  const errorCode = apiErrorInfo(confirming.error)?.code;
  const lastFailed = result?.attempt.status === 'failed' && !paid;

  const pay = (outcome: 'success' | 'failure') => {
    if (!attempt || busy) {
      return;
    }
    void confirm({ order_id: data.id, attempt_id: attempt.id, outcome })
      .unwrap()
      .then(setResult)
      .catch(() => undefined);
  };

  return (
    <div className="flex flex-col gap-6">
      {heading}
      <div
        role="note"
        className="rounded-xl border border-accent-600 bg-accent-50 px-4 py-3 font-semibold"
      >
        {t('payments.demoWarning')}
      </div>

      <section className={`${BOX} flex flex-col gap-4`} aria-label={t('payments.summary')}>
        <dl className="grid gap-2 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-ink-600">{t('payments.amount')}</dt>
            <dd className="text-2xl font-bold" data-testid="pay-amount">
              <Price amount={data.total_amount} />
            </dd>
          </div>
          <div>
            <dt className="text-ink-600">{t('payments.statusLabel')}</dt>
            <dd className="font-semibold" data-testid="pay-status">
              {t(`payments.status.${data.payment_status ?? 'pending'}`)}
            </dd>
          </div>
          {data.payment_due_at && !paid && (
            <div className="sm:col-span-2">
              <dt className="text-ink-600">{t('payments.dueLabel')}</dt>
              <dd>
                {formatDateTime(data.payment_due_at, language)}
                {!expired && due !== null && (
                  <span className="ml-2 font-semibold" aria-live="off" data-testid="pay-left">
                    {t('payments.left', { time: formatLeft(due - now) })}
                  </span>
                )}
              </dd>
            </div>
          )}
        </dl>

        {paid ? (
          <div role="status" className="rounded-xl bg-success-50 px-4 py-3 text-success-700">
            <p className="font-semibold">{t('payments.paid')}</p>
            <p className="text-sm">{t('payments.paidNext')}</p>
          </div>
        ) : data.status === 'cancelled' ? (
          <div role="alert" className="rounded-xl bg-danger-50 px-4 py-3 text-danger-700">
            {data.cancellation_reason_code === 'payment_timeout'
              ? t('payments.cancelledTimeout')
              : t('payments.cancelled')}
          </div>
        ) : expired ? (
          <div role="alert" className="rounded-xl bg-danger-50 px-4 py-3 text-danger-700">
            {t('payments.expired')}
          </div>
        ) : (
          <>
            {lastFailed && (
              <p role="alert" className="rounded-xl bg-danger-50 px-4 py-3 text-sm text-danger-700">
                {t('payments.failed')}
              </p>
            )}
            {errorCode && (
              <p role="alert" className="text-sm text-danger-700">
                {t(`payments.errors.${errorCode}`, {
                  defaultValue: t(`errors.codes.${errorCode}`, {
                    defaultValue: t('errors.codes.default'),
                  }),
                })}
              </p>
            )}
            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                disabled={!attempt || busy}
                onClick={() => pay('success')}
                className="min-h-12 rounded-full bg-success-strong px-6 font-semibold text-on-accent disabled:cursor-not-allowed disabled:opacity-60"
              >
                {confirming.isLoading ? t('payments.processing') : t('payments.paySuccess')}
              </button>
              <button
                type="button"
                disabled={!attempt || busy}
                onClick={() => pay('failure')}
                className="min-h-12 rounded-full px-6 font-semibold ring-1 ring-border hover:bg-cream-100 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {t('payments.payFailure')}
              </button>
            </div>
            <p className="text-xs text-ink-600">{t('payments.noCardData')}</p>
          </>
        )}
      </section>

      <section className={BOX} aria-labelledby="pay-attempts">
        <h2 id="pay-attempts" className="mb-3 text-lg font-bold">
          {t('payments.attemptsTitle')}
        </h2>
        <PaymentAttempts payments={data.payments} />
      </section>
      <Link
        to={`/orders/${data.id}`}
        className="self-start font-semibold text-accent-800 underline"
      >
        {t('payments.toOrder')}
      </Link>
    </div>
  );
}
