import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';

import {
  AdminError,
  BUTTON_DANGER,
  BUTTON_PRIMARY,
  BUTTON_SECONDARY,
  ConfirmAction,
} from '../../features/admin/components/AdminUi';
import {
  STAFF_POLLING_MS,
  useApproveRequestMutation,
  useCancellationRequestsQuery,
  useRejectRequestMutation,
} from '../../features/admin/opsApi';
import { formatDateTime } from '../../features/checkout/messages';
import { StatusBadge } from '../../features/orders/components/StatusBadge';
import { EmptyState, ErrorState } from '../../shared/components/StateViews';
import { useLanguage } from '../../shared/i18n/useLanguage';
import type { AdminRequestOut } from '../../shared/types/api';

function RequestActions({ request }: { request: AdminRequestOut }) {
  const { t } = useTranslation();
  const id = useId();
  const [approve, approving] = useApproveRequestMutation();
  const [reject, rejecting] = useRejectRequestMutation();
  const [rejectOpen, setRejectOpen] = useState(false);
  const [comment, setComment] = useState('');

  return (
    <div className="flex flex-col gap-2">
      <AdminError error={approving.error ?? rejecting.error} />
      {rejectOpen ? (
        <form
          className="flex flex-col gap-2 rounded-xl bg-cream-100 p-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (!comment.trim()) {
              return;
            }
            void reject({ id: request.id, adminComment: comment.trim() })
              .unwrap()
              .then(() => setRejectOpen(false))
              .catch(() => undefined);
          }}
        >
          <label htmlFor={id} className="text-sm font-medium">
            {t('admin.requests.answer')}
          </label>
          <textarea
            id={id}
            rows={2}
            maxLength={500}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            className="rounded-md border border-border bg-surface px-3 py-2"
          />
          <div className="flex flex-wrap gap-2">
            <button
              type="submit"
              className={BUTTON_DANGER}
              disabled={!comment.trim() || rejecting.isLoading}
            >
              {t('admin.requests.reject')}
            </button>
            <button type="button" className={BUTTON_SECONDARY} onClick={() => setRejectOpen(false)}>
              {t('admin.cancel')}
            </button>
          </div>
        </form>
      ) : (
        <div className="flex flex-wrap gap-2">
          <ConfirmAction
            label={t('admin.requests.approve')}
            question={t('admin.requests.approveQuestion')}
            confirmLabel={t('admin.requests.approveConfirm')}
            pending={approving.isLoading}
            onConfirm={() => void approve(request.id)}
          />
          <button type="button" className={BUTTON_PRIMARY} onClick={() => setRejectOpen(true)}>
            {t('admin.requests.reject')}
          </button>
        </div>
      )}
    </div>
  );
}

/** Cancellation requests of customers (DEC-38, DEC-42, DEC-82, DEC-150). */
export function AdminCancellationsPage() {
  const { t } = useTranslation();
  const language = useLanguage();
  const [status, setStatus] = useState('pending');
  const requests = useCancellationRequestsQuery(
    { status, page: 1 },
    { pollingInterval: STAFF_POLLING_MS },
  );

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-extrabold">{t('admin.sections.cancellations')}</h1>
          <p className="text-sm text-ink-600">{t('admin.requests.intro')}</p>
        </div>
        <label className="flex flex-col gap-1 text-sm font-medium">
          {t('admin.orders.status')}
          <select
            className="min-h-11 rounded-lg border border-border bg-surface px-3"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            {['pending', 'approved', 'rejected', 'all'].map((s) => (
              <option key={s} value={s}>
                {t(`admin.requests.filter.${s}`)}
              </option>
            ))}
          </select>
        </label>
      </header>
      {requests.isError ? (
        <ErrorState
          title={t('admin.loadError')}
          text={t('menu.errorText')}
          onRetry={() => void requests.refetch()}
        />
      ) : requests.isLoading ? (
        <p role="status" className="text-ink-600">
          {t('admin.loading')}
        </p>
      ) : !requests.data || requests.data.items.length === 0 ? (
        <EmptyState title={t('admin.requests.emptyTitle')} text={t('admin.requests.emptyText')} />
      ) : (
        <ul className="flex flex-col gap-3" aria-label={t('admin.sections.cancellations')}>
          {requests.data.items.map((request) => (
            <li
              key={request.id}
              className="flex flex-col gap-3 rounded-card border border-border bg-surface p-4"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <Link
                  to={`/admin/orders/${request.order_id}`}
                  className="font-bold text-accent-800 underline"
                >
                  {request.order_number}
                </Link>
                <StatusBadge status={request.order_status} />
              </div>
              <p className="text-sm">
                <span className="font-medium">{request.customer_name}:</span> {request.reason}
              </p>
              <p className="text-xs text-ink-600">
                {formatDateTime(request.created_at, language)} ·{' '}
                {t(`orders.cancel.status.${request.status}`)}
                {request.reviewed_by_name && ` · ${request.reviewed_by_name}`}
              </p>
              {request.admin_comment && (
                <p className="text-sm">
                  {t('orders.cancel.answer')}: {request.admin_comment}
                </p>
              )}
              {request.status === 'pending' && <RequestActions request={request} />}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
