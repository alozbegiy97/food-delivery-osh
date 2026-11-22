import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import {
  AdminError,
  Badge,
  BUTTON_SECONDARY,
  SavedNote,
  Toggle,
} from '../../features/admin/components/AdminUi';
import {
  STAFF_POLLING_MS,
  useCouriersQuery,
  useUpdateCourierMutation,
} from '../../features/admin/opsApi';
import { EmptyState, ErrorState } from '../../shared/components/StateViews';
import type { CourierOut } from '../../shared/types/api';

const MIN_LIMIT = 1;
const MAX_LIMIT = 10; // DEC-151 п. 2

function CourierRow({ courier }: { courier: CourierOut }) {
  const { t } = useTranslation();
  const [update, state] = useUpdateCourierMutation();
  const [limit, setLimit] = useState(String(courier.max_active_orders));
  const parsed = Number(limit);
  const valid = /^\d+$/.test(limit) && parsed >= MIN_LIMIT && parsed <= MAX_LIMIT;
  const changed = valid && parsed !== courier.max_active_orders;
  const limitId = `limit-${courier.user_id}`;

  return (
    <li className="flex flex-col gap-3 rounded-card border border-border bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="font-bold">{courier.full_name}</p>
          <p className="text-sm text-ink-600">
            {[courier.phone, courier.email].filter(Boolean).join(' · ')}
          </p>
        </div>
        <div className="flex flex-wrap gap-1">
          {!courier.is_active && <Badge tone="muted">{t('admin.staff.inactive')}</Badge>}
          <Badge tone={courier.active_assignments > 0 ? 'accent' : 'muted'}>
            {t('admin.couriers.load', {
              active: courier.active_assignments,
              limit: courier.max_active_orders,
            })}
          </Badge>
        </div>
      </div>
      <Toggle
        label={t('admin.couriers.available')}
        checked={courier.is_available}
        disabled={state.isLoading}
        onChange={(e) =>
          void update({ id: courier.user_id, body: { is_available: e.target.checked } })
        }
      />
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (changed) {
            void update({ id: courier.user_id, body: { max_active_orders: parsed } });
          }
        }}
      >
        <div className="flex flex-col gap-1">
          <label htmlFor={limitId} className="text-sm font-medium">
            {t('admin.couriers.limit')}
          </label>
          <input
            id={limitId}
            type="number"
            inputMode="numeric"
            min={MIN_LIMIT}
            max={MAX_LIMIT}
            value={limit}
            aria-invalid={!valid || undefined}
            aria-describedby={`${limitId}-hint`}
            onChange={(e) => setLimit(e.target.value)}
            className="min-h-11 w-24 rounded-lg border border-border bg-surface px-3"
          />
        </div>
        <button type="submit" className={BUTTON_SECONDARY} disabled={!changed || state.isLoading}>
          {t('admin.save')}
        </button>
        <SavedNote show={state.isSuccess && !changed} />
      </form>
      <p id={`${limitId}-hint`} className={`text-xs ${valid ? 'text-ink-600' : 'text-danger-700'}`}>
        {!valid
          ? t('admin.couriers.limitRange', { min: MIN_LIMIT, max: MAX_LIMIT })
          : parsed < courier.active_assignments
            ? t('admin.couriers.limitBelowActive')
            : t('admin.couriers.limitHint', { min: MIN_LIMIT, max: MAX_LIMIT })}
      </p>
      <AdminError error={state.error} />
    </li>
  );
}

/** Couriers: availability, the active-order limit and the current load
 * (DEC-151 п. 2, UI_UX_GUIDELINES §4 "Couriers"). */
export function AdminCouriersPage() {
  const { t } = useTranslation();
  const couriers = useCouriersQuery(undefined, { pollingInterval: STAFF_POLLING_MS });

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-2xl font-extrabold">{t('admin.sections.couriers')}</h1>
        <p className="text-sm text-ink-600">{t('admin.couriers.intro')}</p>
      </header>
      {couriers.isError ? (
        <ErrorState
          title={t('admin.loadError')}
          text={t('menu.errorText')}
          onRetry={() => void couriers.refetch()}
        />
      ) : couriers.isLoading ? (
        <p role="status" className="text-ink-600">
          {t('admin.loading')}
        </p>
      ) : !couriers.data || couriers.data.items.length === 0 ? (
        <EmptyState title={t('admin.couriers.emptyTitle')} text={t('admin.couriers.emptyText')} />
      ) : (
        <ul className="flex flex-col gap-3" aria-label={t('admin.sections.couriers')}>
          {couriers.data.items.map((courier) => (
            <CourierRow key={`${courier.user_id}-${courier.max_active_orders}`} courier={courier} />
          ))}
        </ul>
      )}
    </div>
  );
}
