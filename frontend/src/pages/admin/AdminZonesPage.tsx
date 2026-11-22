import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import {
  AdminError,
  AdminSection,
  Badge,
  BUTTON_PRIMARY,
  BUTTON_SECONDARY,
  ConfirmAction,
  Field,
  SavedNote,
  Toggle,
} from '../../features/admin/components/AdminUi';
import { ZoneMap, type ZoneGeometry } from '../../features/admin/components/ZoneMap';
import {
  useCreateZoneMutation,
  useDeactivateZoneMutation,
  useUpdateZoneMutation,
  useZonesQuery,
} from '../../features/admin/opsApi';
import { Price } from '../../features/catalog/components/Price';
import { apiErrorInfo } from '../../shared/api/errors';
import { EmptyState, ErrorState } from '../../shared/components/StateViews';
import type { ApiErrorBody, ZoneOut, ZoneUpdate } from '../../shared/types/api';

const MONEY = /^\d{1,10}([.,]\d{1,2})?$/;

// The map yields GeoJSON; its exact shape is validated by PostGIS on the backend.
const boundary = (g: ZoneGeometry) => g as unknown as NonNullable<ZoneUpdate['boundary']>;

function ZoneErrors({ error }: { error: Parameters<typeof apiErrorInfo>[0] }) {
  const { t } = useTranslation();
  const info = apiErrorInfo(error);
  if (!info || (info.code !== 'ZONE_OVERLAP' && info.code !== 'INVALID_GEOMETRY')) {
    return <AdminError error={error} />;
  }
  const details =
    error && 'status' in error
      ? (((error.data as ApiErrorBody | undefined)?.error?.details ?? []) as { message: string }[])
      : [];
  return (
    <div role="alert" className="rounded-xl bg-danger-50 px-4 py-3 text-sm text-danger-700">
      <p className="font-semibold">{t(`errors.codes.${info.code}`)}</p>
      {details.length > 0 && (
        <p>
          {info.code === 'ZONE_OVERLAP' ? t('admin.zones.overlapWith') : t('admin.zones.reason')}:{' '}
          {details.map((d) => d.message).join(', ')}
        </p>
      )}
    </div>
  );
}

function ZoneEditor({
  zone,
  zones,
  onDone,
}: {
  zone: ZoneOut | null;
  zones: ZoneOut[];
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const [create, creating] = useCreateZoneMutation();
  const [update, updating] = useUpdateZoneMutation();
  const [deactivate, deactivating] = useDeactivateZoneMutation();
  const [name, setName] = useState(zone?.name ?? '');
  const [description, setDescription] = useState(zone?.description ?? '');
  const [fee, setFee] = useState(zone?.delivery_fee ?? '');
  const [minimum, setMinimum] = useState(zone?.min_order_amount ?? '0');
  const [active, setActive] = useState(zone?.is_active ?? true);
  const [geometry, setGeometry] = useState<ZoneGeometry | null>(
    (zone?.boundary as ZoneGeometry | null) ?? null,
  );
  const [geometryChanged, setGeometryChanged] = useState(false);
  const pending = creating.isLoading || updating.isLoading;
  const valid = name.trim() !== '' && MONEY.test(fee) && MONEY.test(minimum) && geometry !== null;

  const others = zones
    .filter((z) => z.id !== zone?.id)
    .map((z) => ({
      id: z.id,
      name: z.name,
      isActive: z.is_active,
      boundary: z.boundary as ZoneGeometry | null,
    }));

  const save = async () => {
    if (!valid || !geometry) {
      return;
    }
    const body = {
      name: name.trim(),
      description: description.trim() || null,
      delivery_fee: fee.replace(',', '.'),
      min_order_amount: minimum.replace(',', '.'),
      is_active: active,
    };
    try {
      if (zone) {
        await update({
          id: zone.id,
          body: geometryChanged ? { ...body, boundary: boundary(geometry) } : body,
        }).unwrap();
      } else {
        await create({ ...body, boundary: boundary(geometry) }).unwrap();
        onDone();
      }
    } catch {
      // Shown below.
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <ZoneMap
        key={zone?.id ?? 'new'}
        initial={(zone?.boundary as ZoneGeometry | null) ?? null}
        others={others}
        onChange={(g) => {
          setGeometry(g);
          setGeometryChanged(true);
        }}
      />
      {!geometry && <p className="text-sm text-danger-700">{t('admin.zones.drawFirst')}</p>}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          label={t('admin.zones.name')}
          maxLength={120}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <Field
          label={t('admin.zones.description')}
          maxLength={500}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <Field
          label={t('admin.zones.fee')}
          inputMode="decimal"
          value={fee}
          error={fee && !MONEY.test(fee) ? t('admin.validation.money') : undefined}
          onChange={(e) => setFee(e.target.value)}
        />
        <Field
          label={t('admin.zones.minimum')}
          hint={t('admin.zones.minimumHint')}
          inputMode="decimal"
          value={minimum}
          error={minimum && !MONEY.test(minimum) ? t('admin.validation.money') : undefined}
          onChange={(e) => setMinimum(e.target.value)}
        />
      </div>
      <Toggle
        label={t('admin.zones.active')}
        hint={t('admin.zones.activeHint')}
        checked={active}
        onChange={(e) => setActive(e.target.checked)}
      />
      <ZoneErrors error={creating.error ?? updating.error ?? deactivating.error} />
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          className={BUTTON_PRIMARY}
          disabled={!valid || pending}
          onClick={() => void save()}
        >
          {pending ? t('admin.saving') : zone ? t('admin.save') : t('admin.create')}
        </button>
        <button type="button" className={BUTTON_SECONDARY} onClick={onDone}>
          {t('admin.cancel')}
        </button>
        {zone?.is_active && (
          <ConfirmAction
            label={t('admin.zones.deactivate')}
            question={t('admin.zones.deactivateQuestion')}
            confirmLabel={t('admin.zones.deactivateConfirm')}
            pending={deactivating.isLoading}
            onConfirm={() => void deactivate(zone.id)}
          />
        )}
        <SavedNote show={updating.isSuccess && !pending} />
      </div>
    </div>
  );
}

/** Delivery zones (DEC-53, DEC-102, DEC-150): drawn on the map, checked by
 * PostGIS on the backend; "delete" only deactivates. */
export function AdminZonesPage() {
  const { t } = useTranslation();
  const zones = useZonesQuery();
  const [editing, setEditing] = useState<string | 'new' | null>(null);
  const items = zones.data?.items ?? [];
  const current =
    editing && editing !== 'new' ? (items.find((z) => z.id === editing) ?? null) : null;

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-extrabold">{t('admin.sections.zones')}</h1>
          <p className="text-sm text-ink-600">{t('admin.zones.intro')}</p>
        </div>
        {editing === null && (
          <button type="button" className={BUTTON_PRIMARY} onClick={() => setEditing('new')}>
            {t('admin.zones.add')}
          </button>
        )}
      </header>
      {zones.isError ? (
        <ErrorState
          title={t('admin.loadError')}
          text={t('menu.errorText')}
          onRetry={() => void zones.refetch()}
        />
      ) : zones.isLoading ? (
        <p role="status" className="text-ink-600">
          {t('admin.loading')}
        </p>
      ) : (
        <>
          {editing !== null && (
            <AdminSection title={current ? current.name : t('admin.zones.newTitle')}>
              <ZoneEditor
                key={editing}
                zone={current}
                zones={items}
                onDone={() => setEditing(null)}
              />
            </AdminSection>
          )}
          {items.length === 0 ? (
            <EmptyState title={t('admin.zones.emptyTitle')} text={t('admin.zones.emptyText')} />
          ) : (
            <ul className="flex flex-col gap-3" aria-label={t('admin.sections.zones')}>
              {items.map((zone) => (
                <li
                  key={zone.id}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-border bg-surface p-4"
                >
                  <div>
                    <p className="font-bold">{zone.name}</p>
                    <p className="text-sm text-ink-600">
                      {t('admin.zones.fee')}: <Price amount={zone.delivery_fee} /> ·{' '}
                      {t('admin.zones.minimum')}: <Price amount={zone.min_order_amount} />
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge tone={zone.is_active ? 'success' : 'muted'}>
                      {zone.is_active ? t('admin.zones.isActive') : t('admin.zones.isInactive')}
                    </Badge>
                    <button
                      type="button"
                      className={BUTTON_SECONDARY}
                      onClick={() => setEditing(zone.id)}
                    >
                      {t('admin.edit')}
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
