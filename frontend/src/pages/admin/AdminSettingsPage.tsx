import { useState } from 'react';
import { Controller, useForm, useWatch } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { z } from 'zod';

import {
  AdminError,
  AdminSection,
  BUTTON_PRIMARY,
  Field,
  SavedNote,
  Toggle,
} from '../../features/admin/components/AdminUi';
import {
  useAdminSettingsQuery,
  useSaveWorkingHoursMutation,
  useUpdateSettingsMutation,
  useWorkingHoursQuery,
} from '../../features/admin/opsApi';
import { DeliveryMap } from '../../features/checkout/components/DeliveryMap';
import { toPoint } from '../../features/checkout/point';
import { ErrorState } from '../../shared/components/StateViews';
import { apiErrorInfo } from '../../shared/api/errors';
import { formatPhoneInput, isCompletePhone } from '../../shared/lib/phone';
import { zodResolver } from '../../shared/lib/zodResolver';
import type { ApiErrorBody, DayHoursIn, SettingsOut, WeekHours } from '../../shared/types/api';

const COORD = /^-?\d{1,3}(\.\d{1,7})?$/;

const settingsSchema = z
  .object({
    restaurant_name: z
      .string()
      .trim()
      .min(1, 'validation.required')
      .max(180, 'checkout.validation.tooLong'),
    phone: z.string().refine((v) => v === '' || isCompletePhone(v), 'validation.phoneInvalid'),
    address: z.string().trim().max(500, 'checkout.validation.tooLong'),
    latitude: z.string().trim(),
    longitude: z.string().trim(),
    min_order_amount: z
      .string()
      .trim()
      .regex(/^\d{1,10}([.,]\d{1,2})?$/, 'admin.validation.money'),
    delivery_enabled: z.boolean(),
    pickup_enabled: z.boolean(),
  })
  .superRefine((v, ctx) => {
    if ((v.latitude === '') !== (v.longitude === '')) {
      ctx.addIssue({ code: 'custom', path: ['latitude'], message: 'admin.settings.pairRequired' });
    }
    if (v.latitude && (!COORD.test(v.latitude) || Math.abs(Number(v.latitude)) > 90)) {
      ctx.addIssue({ code: 'custom', path: ['latitude'], message: 'admin.settings.badLatitude' });
    }
    if (v.longitude && (!COORD.test(v.longitude) || Math.abs(Number(v.longitude)) > 180)) {
      ctx.addIssue({ code: 'custom', path: ['longitude'], message: 'admin.settings.badLongitude' });
    }
  });

function SettingsForm({ settings }: { settings: SettingsOut }) {
  const { t } = useTranslation();
  const [save, state] = useUpdateSettingsMutation();
  const {
    register,
    control,
    handleSubmit,
    setValue,
    formState: { errors, isDirty },
    reset,
  } = useForm<z.input<typeof settingsSchema>, unknown, z.output<typeof settingsSchema>>({
    resolver: zodResolver(settingsSchema),
    defaultValues: {
      restaurant_name: settings.restaurant_name,
      phone: settings.phone ? formatPhoneInput(settings.phone) : '',
      address: settings.address ?? '',
      latitude: settings.latitude ?? '',
      longitude: settings.longitude ?? '',
      min_order_amount: settings.min_order_amount,
      delivery_enabled: settings.delivery_enabled,
      pickup_enabled: settings.pickup_enabled,
    },
  });
  const latitude = useWatch({ control, name: 'latitude' });
  const longitude = useWatch({ control, name: 'longitude' });
  const point = COORD.test(latitude) && COORD.test(longitude) ? { latitude, longitude } : null;
  const message = (key?: string) => (key ? t(key) : undefined);

  return (
    <form
      noValidate
      className="flex flex-col gap-4"
      onSubmit={handleSubmit(async (values) => {
        try {
          await save({
            restaurant_name: values.restaurant_name,
            phone: values.phone || null,
            address: values.address || null,
            latitude: values.latitude || null,
            longitude: values.longitude || null,
            min_order_amount: values.min_order_amount.replace(',', '.'),
            delivery_enabled: values.delivery_enabled,
            pickup_enabled: values.pickup_enabled,
          }).unwrap();
          reset(undefined, { keepValues: true });
        } catch {
          // Shown by <AdminError>.
        }
      })}
    >
      <AdminError error={state.error} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          label={t('admin.settings.name')}
          error={message(errors.restaurant_name?.message)}
          {...register('restaurant_name')}
        />
        <Controller
          control={control}
          name="phone"
          render={({ field }) => (
            <Field
              label={t('admin.settings.phone')}
              type="tel"
              error={message(errors.phone?.message)}
              name={field.name}
              ref={field.ref}
              value={field.value}
              onBlur={field.onBlur}
              onChange={(e) => field.onChange(formatPhoneInput(e.target.value))}
            />
          )}
        />
        <Field
          label={t('admin.settings.address')}
          error={message(errors.address?.message)}
          {...register('address')}
        />
        <Field
          label={t('admin.settings.minOrder')}
          inputMode="decimal"
          error={message(errors.min_order_amount?.message)}
          {...register('min_order_amount')}
        />
        <Field
          label={t('admin.settings.latitude')}
          inputMode="decimal"
          error={message(errors.latitude?.message)}
          {...register('latitude')}
        />
        <Field
          label={t('admin.settings.longitude')}
          inputMode="decimal"
          error={message(errors.longitude?.message)}
          {...register('longitude')}
        />
      </div>
      <DeliveryMap
        point={point}
        onPick={(picked) => {
          const p = toPoint(Number(picked.latitude), Number(picked.longitude));
          setValue('latitude', p.latitude, { shouldDirty: true });
          setValue('longitude', p.longitude, { shouldDirty: true });
        }}
      />
      <div className="grid gap-4 sm:grid-cols-2">
        <Toggle label={t('admin.settings.delivery')} {...register('delivery_enabled')} />
        <Toggle label={t('admin.settings.pickup')} {...register('pickup_enabled')} />
      </div>
      <p className="text-sm text-ink-600">
        {t('admin.settings.timezone', { tz: settings.timezone })}
      </p>
      <div className="flex items-center gap-3">
        <button type="submit" className={BUTTON_PRIMARY} disabled={state.isLoading}>
          {state.isLoading ? t('admin.saving') : t('admin.save')}
        </button>
        <SavedNote show={state.isSuccess && !isDirty} />
      </div>
    </form>
  );
}

const hhmm = (value: string | null | undefined) => (value ? value.slice(0, 5) : '');

function HoursForm({ hours }: { hours: WeekHours }) {
  const { t } = useTranslation();
  const [save, state] = useSaveWorkingHoursMutation();
  const [days, setDays] = useState<DayHoursIn[]>(
    hours.items.map((d) => ({
      weekday: d.weekday,
      is_closed: d.is_closed,
      opens_at: hhmm(d.opens_at) || null,
      closes_at: hhmm(d.closes_at) || null,
    })),
  );
  const problems =
    state.error &&
    'status' in state.error &&
    apiErrorInfo(state.error)?.code === 'INVALID_WORKING_HOURS'
      ? (((state.error.data as ApiErrorBody | undefined)?.error?.details ?? []) as {
          weekday: number | null;
          problem: string;
        }[])
      : [];
  const update = (weekday: number, patch: Partial<DayHoursIn>) =>
    setDays(days.map((d) => (d.weekday === weekday ? { ...d, ...patch } : d)));
  const field = 'min-h-11 rounded-lg border border-border bg-surface px-2';

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        void save(days);
      }}
    >
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-ink-600">
            <th className="py-1 font-medium">{t('admin.hours.day')}</th>
            <th className="py-1 font-medium">{t('admin.hours.closed')}</th>
            <th className="py-1 font-medium">{t('admin.hours.opens')}</th>
            <th className="py-1 font-medium">{t('admin.hours.closes')}</th>
          </tr>
        </thead>
        <tbody>
          {days.map((day) => (
            <tr key={day.weekday} className="border-t border-border">
              <td className="py-2 pr-2 font-medium">{t(`restaurant.weekdays.${day.weekday}`)}</td>
              <td className="py-2 pr-2">
                <input
                  type="checkbox"
                  aria-label={t('admin.hours.closedOf', {
                    day: t(`restaurant.weekdays.${day.weekday}`),
                  })}
                  className="h-4 w-4 accent-accent-700"
                  checked={day.is_closed}
                  onChange={(e) => update(day.weekday, { is_closed: e.target.checked })}
                />
              </td>
              <td className="py-2 pr-2">
                <input
                  type="time"
                  aria-label={t('admin.hours.opensOf', {
                    day: t(`restaurant.weekdays.${day.weekday}`),
                  })}
                  className={field}
                  disabled={day.is_closed}
                  value={day.opens_at ?? ''}
                  onChange={(e) => update(day.weekday, { opens_at: e.target.value || null })}
                />
              </td>
              <td className="py-2 pr-2">
                <input
                  type="time"
                  aria-label={t('admin.hours.closesOf', {
                    day: t(`restaurant.weekdays.${day.weekday}`),
                  })}
                  className={field}
                  disabled={day.is_closed}
                  value={day.closes_at ?? ''}
                  onChange={(e) => update(day.weekday, { closes_at: e.target.value || null })}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-xs text-ink-600">{t('admin.hours.overnightHint')}</p>
      {problems.length > 0 ? (
        <ul role="alert" className="rounded-xl bg-danger-50 px-4 py-3 text-sm text-danger-700">
          {problems.map((p, i) => (
            <li key={i}>
              {p.weekday !== null && `${t(`restaurant.weekdays.${p.weekday}`)}: `}
              {t(`admin.hours.problems.${p.problem}`, { defaultValue: p.problem })}
            </li>
          ))}
        </ul>
      ) : (
        <AdminError error={state.error} />
      )}
      <div className="flex items-center gap-3">
        <button type="submit" className={BUTTON_PRIMARY} disabled={state.isLoading}>
          {state.isLoading ? t('admin.saving') : t('admin.save')}
        </button>
        <SavedNote show={state.isSuccess} />
      </div>
    </form>
  );
}

/** Restaurant settings and working hours (DEC-107, DEC-150). */
export function AdminSettingsPage() {
  const { t } = useTranslation();
  const settings = useAdminSettingsQuery();
  const hours = useWorkingHoursQuery();
  if (settings.isError || hours.isError) {
    return (
      <ErrorState
        title={t('admin.loadError')}
        text={t('menu.errorText')}
        onRetry={() => {
          void settings.refetch();
          void hours.refetch();
        }}
      />
    );
  }
  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-2xl font-extrabold">{t('admin.sections.settings')}</h1>
        <p className="text-sm text-ink-600">{t('admin.settings.intro')}</p>
      </header>
      <AdminSection title={t('admin.settings.title')}>
        {settings.data ? <SettingsForm settings={settings.data} /> : <p>{t('admin.loading')}</p>}
      </AdminSection>
      <AdminSection title={t('admin.hours.title')} description={t('admin.hours.intro')}>
        {hours.data ? <HoursForm hours={hours.data} /> : <p>{t('admin.loading')}</p>}
      </AdminSection>
    </div>
  );
}
