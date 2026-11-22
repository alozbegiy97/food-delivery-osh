import { useState } from 'react';
import { Controller, useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { z } from 'zod';

import {
  AdminError,
  AdminSection,
  Badge,
  BUTTON_PRIMARY,
  BUTTON_SECONDARY,
  ConfirmAction,
  Field,
} from '../../features/admin/components/AdminUi';
import {
  useCreateStaffMutation,
  useSetStaffActiveMutation,
  useStaffQuery,
  useUpdateStaffRolesMutation,
} from '../../features/admin/opsApi';
import { EmptyState, ErrorState } from '../../shared/components/StateViews';
import { formatPhoneInput, isCompletePhone } from '../../shared/lib/phone';
import { zodResolver } from '../../shared/lib/zodResolver';
import type { StaffOut } from '../../shared/types/api';

type StaffRoleName = 'cook' | 'courier';
const STAFF_ROLES: StaffRoleName[] = ['cook', 'courier'];

// Same rules as the backend (DEC-96 password policy, DEC-150 roles).
const createSchema = z
  .object({
    full_name: z.string().trim().min(1, 'validation.required').max(150, 'validation.nameTooLong'),
    email: z.string().trim().email('validation.emailInvalid'),
    phone: z.string().refine((v) => v === '' || isCompletePhone(v), 'validation.phoneInvalid'),
    temporary_password: z
      .string()
      .min(8, 'validation.passwordLength')
      .max(128, 'validation.passwordLength')
      .regex(/\p{L}/u, 'validation.passwordLetter')
      .regex(/\d/, 'validation.passwordDigit'),
    cook: z.boolean(),
    courier: z.boolean(),
  })
  .refine((v) => v.cook || v.courier, { path: ['cook'], message: 'admin.staff.roleRequired' });

function CreateStaffForm({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation();
  const [create, state] = useCreateStaffMutation();
  const {
    register,
    control,
    handleSubmit,
    formState: { errors },
  } = useForm<z.input<typeof createSchema>, unknown, z.output<typeof createSchema>>({
    resolver: zodResolver(createSchema),
    defaultValues: {
      full_name: '',
      email: '',
      phone: '',
      temporary_password: '',
      cook: true,
      courier: false,
    },
  });
  const message = (key?: string) => (key ? t(key) : undefined);

  return (
    <form
      noValidate
      className="flex flex-col gap-4"
      onSubmit={handleSubmit(async (values) => {
        try {
          await create({
            full_name: values.full_name,
            email: values.email,
            phone: values.phone || null,
            temporary_password: values.temporary_password,
            roles: STAFF_ROLES.filter((role) => values[role]),
          }).unwrap();
          onDone();
        } catch {
          // Shown by <AdminError>.
        }
      })}
    >
      <AdminError error={state.error} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          label={t('admin.staff.fullName')}
          error={message(errors.full_name?.message)}
          {...register('full_name')}
        />
        <Field
          label={t('admin.staff.email')}
          type="email"
          autoComplete="off"
          error={message(errors.email?.message)}
          {...register('email')}
        />
        <Controller
          control={control}
          name="phone"
          render={({ field }) => (
            <Field
              label={t('admin.staff.phone')}
              type="tel"
              placeholder="+996 700 12 34 56"
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
          label={t('admin.staff.temporaryPassword')}
          type="text"
          autoComplete="new-password"
          hint={t('admin.staff.passwordHint')}
          error={message(errors.temporary_password?.message)}
          {...register('temporary_password')}
        />
      </div>
      <fieldset className="flex flex-wrap gap-4">
        <legend className="mb-1 text-sm font-medium">{t('admin.staff.roles')}</legend>
        {STAFF_ROLES.map((role) => (
          <label key={role} className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="h-4 w-4 accent-accent-700" {...register(role)} />
            {t(`admin.staff.role.${role}`)}
          </label>
        ))}
      </fieldset>
      {errors.cook?.message && <p className="text-sm text-danger-700">{t(errors.cook.message)}</p>}
      <p className="text-xs text-ink-600">{t('admin.staff.createNote')}</p>
      <div className="flex gap-3">
        <button type="submit" className={BUTTON_PRIMARY} disabled={state.isLoading}>
          {state.isLoading ? t('admin.saving') : t('admin.create')}
        </button>
        <button type="button" className={BUTTON_SECONDARY} onClick={onDone}>
          {t('admin.cancel')}
        </button>
      </div>
    </form>
  );
}

function StaffRow({ member }: { member: StaffOut }) {
  const { t } = useTranslation();
  const managed = member.roles.filter((r): r is StaffRoleName =>
    (STAFF_ROLES as string[]).includes(r),
  );
  const [roles, setRoles] = useState<StaffRoleName[]>(managed);
  const [saveRoles, saving] = useUpdateStaffRolesMutation();
  const [setActive, toggling] = useSetStaffActiveMutation();
  const isAdmin = member.roles.includes('admin');
  const changed = roles.length !== managed.length || roles.some((r) => !managed.includes(r));

  return (
    <li className="flex flex-col gap-3 rounded-card border border-border bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="font-bold">{member.full_name}</p>
          <p className="text-sm text-ink-600">
            {member.email}
            {member.phone && ` · ${member.phone}`}
          </p>
        </div>
        <div className="flex flex-wrap gap-1">
          <Badge tone={member.is_active ? 'success' : 'muted'}>
            {member.is_active ? t('admin.staff.active') : t('admin.staff.inactive')}
          </Badge>
          {member.must_change_password && (
            <Badge tone="accent">{t('admin.staff.mustChange')}</Badge>
          )}
          {member.roles
            .filter((r) => !(STAFF_ROLES as string[]).includes(r))
            .map((r) => (
              <Badge key={r} tone="muted">
                {t(`admin.staff.role.${r}`, { defaultValue: r })}
              </Badge>
            ))}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-4">
        {STAFF_ROLES.map((role) => (
          <label key={role} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="h-4 w-4 accent-accent-700"
              checked={roles.includes(role)}
              onChange={() =>
                setRoles(roles.includes(role) ? roles.filter((r) => r !== role) : [...roles, role])
              }
            />
            {t(`admin.staff.role.${role}`)}
          </label>
        ))}
        <button
          type="button"
          className={BUTTON_SECONDARY}
          disabled={!changed || roles.length === 0 || saving.isLoading}
          onClick={() => void saveRoles({ id: member.id, roles })}
        >
          {t('admin.staff.saveRoles')}
        </button>
        {isAdmin ? (
          <span className="text-xs text-ink-600">{t('admin.staff.adminProtected')}</span>
        ) : member.is_active ? (
          <ConfirmAction
            label={t('admin.staff.deactivate')}
            question={t('admin.staff.deactivateQuestion')}
            confirmLabel={t('admin.staff.deactivateConfirm')}
            pending={toggling.isLoading}
            onConfirm={() => void setActive({ id: member.id, active: false })}
          />
        ) : (
          <button
            type="button"
            className={BUTTON_PRIMARY}
            disabled={toggling.isLoading}
            onClick={() => void setActive({ id: member.id, active: true })}
          >
            {t('admin.staff.reactivate')}
          </button>
        )}
      </div>
      <AdminError error={saving.error ?? toggling.error} />
    </li>
  );
}

/** Staff (DEC-150): cooks and couriers; administrators are created only by
 * the CLI and are not managed here. */
export function AdminStaffPage() {
  const { t } = useTranslation();
  const staff = useStaffQuery();
  const [creating, setCreating] = useState(false);

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-extrabold">{t('admin.sections.staff')}</h1>
          <p className="text-sm text-ink-600">{t('admin.staff.intro')}</p>
        </div>
        {!creating && (
          <button type="button" className={BUTTON_PRIMARY} onClick={() => setCreating(true)}>
            {t('admin.staff.add')}
          </button>
        )}
      </header>
      {creating && (
        <AdminSection title={t('admin.staff.newTitle')}>
          <CreateStaffForm onDone={() => setCreating(false)} />
        </AdminSection>
      )}
      {staff.isError ? (
        <ErrorState
          title={t('admin.loadError')}
          text={t('menu.errorText')}
          onRetry={() => void staff.refetch()}
        />
      ) : staff.isLoading ? (
        <p role="status" className="text-ink-600">
          {t('admin.loading')}
        </p>
      ) : !staff.data || staff.data.items.length === 0 ? (
        <EmptyState title={t('admin.staff.emptyTitle')} text={t('admin.staff.emptyText')} />
      ) : (
        <ul className="flex flex-col gap-3" aria-label={t('admin.sections.staff')}>
          {staff.data.items.map((member) => (
            <StaffRow key={`${member.id}-${member.roles.join()}`} member={member} />
          ))}
        </ul>
      )}
    </div>
  );
}
