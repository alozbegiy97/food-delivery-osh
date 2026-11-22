import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { formatDateTime } from '../../checkout/messages';
import { apiErrorInfo } from '../../../shared/api/errors';
import { useLanguage } from '../../../shared/i18n/useLanguage';
import type { AdminOrderDetail } from '../../../shared/types/api';
import {
  useAssignCourierMutation,
  useAutoAssignCourierMutation,
  useCouriersQuery,
} from '../opsApi';
import { AdminError, AdminSection, Badge, BUTTON_PRIMARY, BUTTON_SECONDARY } from './AdminUi';

/**
 * Courier of a delivery order (DEC-48…DEC-51, DEC-92, DEC-151): the current
 * assignment and its history, manual (re)assignment and auto-assignment.
 * The backend re-checks everything; this only offers the actions.
 */
export function CourierPanel({ order }: { order: AdminOrderDetail }) {
  const { t } = useTranslation();
  const language = useLanguage();
  const couriers = useCouriersQuery(undefined, { skip: !order.can_assign_courier });
  const [assign, assigning] = useAssignCourierMutation();
  const [autoAssign, autoAssigning] = useAutoAssignCourierMutation();
  const [courierId, setCourierId] = useState('');
  const selectId = useId();
  const active = order.assignments.find((a) => a.status === 'active') ?? null;
  const past = order.assignments.filter((a) => a.status !== 'active').reverse();
  const busy = assigning.isLoading || autoAssigning.isLoading;
  const noCourier = apiErrorInfo(autoAssigning.error)?.code === 'NO_COURIER_AVAILABLE';
  const candidates = (couriers.data?.items ?? []).filter(
    (c) => c.is_active && c.user_id !== active?.courier_id,
  );

  return (
    <AdminSection title={t('admin.assign.title')}>
      <div className="flex flex-col gap-4">
        {order.needs_courier && (
          <p
            role="status"
            className="rounded-xl bg-danger-50 px-4 py-2 text-sm font-semibold text-danger-700"
          >
            {t('admin.assign.needsCourier')}
          </p>
        )}
        {active ? (
          <div className="flex flex-col gap-1 text-sm">
            <p className="font-semibold">
              {active.courier_name}
              {active.courier_phone && ` · ${active.courier_phone}`}
            </p>
            <p className="flex flex-wrap items-center gap-2 text-ink-600">
              <Badge tone={active.accepted_at ? 'success' : 'accent'}>
                {active.accepted_at ? t('admin.assign.accepted') : t('admin.assign.notAccepted')}
              </Badge>
              {t(`admin.assign.type.${active.assignment_type}`)} ·{' '}
              {formatDateTime(active.assigned_at, language)}
            </p>
          </div>
        ) : (
          !order.needs_courier && <p className="text-sm text-ink-600">{t('admin.assign.none')}</p>
        )}

        {order.can_assign_courier && (
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-end gap-3">
              <div className="flex min-w-48 flex-1 flex-col gap-1">
                <label htmlFor={selectId} className="text-sm font-medium">
                  {active ? t('admin.assign.reassignLabel') : t('admin.assign.chooseLabel')}
                </label>
                <select
                  id={selectId}
                  className="min-h-11 rounded-lg border border-border bg-surface px-3"
                  value={courierId}
                  onChange={(e) => setCourierId(e.target.value)}
                >
                  <option value="">{t('admin.assign.choose')}</option>
                  {candidates.map((c) => (
                    <option key={c.user_id} value={c.user_id}>
                      {t('admin.assign.option', {
                        name: c.full_name,
                        active: c.active_assignments,
                        limit: c.max_active_orders,
                      })}
                      {c.is_available ? '' : ` — ${t('admin.assign.unavailable')}`}
                    </option>
                  ))}
                </select>
              </div>
              <button
                type="button"
                className={BUTTON_PRIMARY}
                disabled={!courierId || busy}
                onClick={() =>
                  void assign({ id: order.id, courierId })
                    .unwrap()
                    .then(() => setCourierId(''))
                    .catch(() => undefined)
                }
              >
                {active ? t('admin.assign.reassign') : t('admin.assign.assign')}
              </button>
              {!active && (
                <button
                  type="button"
                  className={BUTTON_SECONDARY}
                  disabled={busy}
                  onClick={() => void autoAssign(order.id)}
                >
                  {t('admin.assign.auto')}
                </button>
              )}
            </div>
            {noCourier ? (
              <p role="alert" className="rounded-xl bg-danger-50 px-4 py-3 text-sm text-danger-700">
                {t('admin.assign.noCourier')}
              </p>
            ) : (
              <AdminError error={autoAssigning.error ?? assigning.error} />
            )}
          </div>
        )}

        {past.length > 0 && (
          <div className="flex flex-col gap-1">
            <p className="text-xs font-semibold uppercase tracking-wide text-ink-600">
              {t('admin.assign.history')}
            </p>
            <ul className="flex flex-col gap-1 text-sm">
              {past.map((a) => (
                <li key={a.id}>
                  <span className="font-medium">{a.courier_name}</span> —{' '}
                  {t(`admin.assign.status.${a.status}`)}
                  {a.decline_reason && ` («${a.decline_reason}»)`}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </AdminSection>
  );
}
