import { useState } from 'react';
import { useForm, useWatch } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { z } from 'zod';

import {
  ADMIN_POLLING_MS,
  useAdminGroupsQuery,
  useCreateGroupMutation,
  useCreateModifierMutation,
  useUpdateGroupMutation,
  useUpdateModifierMutation,
} from '../../features/admin/adminCatalogApi';
import {
  AdminError,
  AdminSection,
  Badge,
  BUTTON_PRIMARY,
  BUTTON_SECONDARY,
  Field,
  Toggle,
} from '../../features/admin/components/AdminUi';
import { TranslationTabs } from '../../features/admin/components/TranslationTabs';
import { groupRuleText } from '../../features/admin/groupRules';
import {
  emptyTranslations,
  moneyField,
  ruName,
  sortField,
  translationsSchema,
  translationsToApi,
  translationsToForm,
} from '../../features/admin/forms';
import { Price } from '../../features/catalog/components/Price';
import { EmptyState, ErrorState } from '../../shared/components/StateViews';
import { zodResolver } from '../../shared/lib/zodResolver';
import type { ModifierAdminOut, ModifierGroupAdminOut } from '../../shared/types/api';

const selectClass = 'min-h-11 rounded-lg border border-border bg-surface px-3';

// --------------------------------------------------------------------------
// Group form. Rules (DATABASE_SCHEMA.md §5.5, DEC-128): a single-choice group
// allows at most one option; "required" means minimum ≥ 1. The backend checks
// the same rules again.
// --------------------------------------------------------------------------

const countField = z
  .string()
  .trim()
  .regex(/^\d{1,3}$/, 'admin.validation.integer')
  .transform(Number);

const groupSchema = z
  .object({
    translations: translationsSchema(120),
    selection_type: z.enum(['single', 'multiple']),
    required: z.boolean(),
    min_selections: countField,
    max_selections: z
      .string()
      .trim()
      .regex(/^(\d{1,3})?$/, 'admin.validation.integer')
      .transform((v) => (v === '' ? null : Number(v))),
    is_active: z.boolean(),
    sort_order: sortField,
  })
  .superRefine((value, ctx) => {
    if (value.selection_type === 'multiple') {
      if (value.max_selections !== null && value.max_selections < 1) {
        ctx.addIssue({
          code: 'custom',
          path: ['max_selections'],
          message: 'admin.validation.minOne',
        });
      }
      if (value.max_selections !== null && value.min_selections > value.max_selections) {
        ctx.addIssue({ code: 'custom', path: ['min_selections'], message: 'admin.errors.minMax' });
      }
    }
  });
type GroupIn = z.input<typeof groupSchema>;
type GroupOut = z.output<typeof groupSchema>;

function GroupForm({ group, onDone }: { group: ModifierGroupAdminOut | null; onDone: () => void }) {
  const { t } = useTranslation();
  const [create, creating] = useCreateGroupMutation();
  const [update, updating] = useUpdateGroupMutation();
  const pending = creating.isLoading || updating.isLoading;
  const {
    register,
    handleSubmit,
    control,
    formState: { errors },
  } = useForm<GroupIn, unknown, GroupOut>({
    resolver: zodResolver(groupSchema),
    defaultValues: {
      translations: group ? translationsToForm(group.translations) : emptyTranslations(),
      selection_type: group?.selection_type === 'multiple' ? 'multiple' : 'single',
      required: group?.is_required ?? false,
      min_selections: String(group?.min_selections ?? 0),
      max_selections: group?.max_selections == null ? '' : String(group.max_selections),
      is_active: group?.is_active ?? true,
      sort_order: String(group?.sort_order ?? 0),
    },
  });
  const isSingle = useWatch({ control, name: 'selection_type' }) === 'single';

  const onSubmit = handleSubmit(async (values) => {
    const single = values.selection_type === 'single';
    const min = single ? (values.required ? 1 : 0) : values.min_selections;
    const max = single ? 1 : values.max_selections;
    const common = {
      translations: translationsToApi(values.translations, false),
      selection_type: values.selection_type,
      min_selections: min,
      is_active: values.is_active,
      sort_order: values.sort_order,
    };
    try {
      if (group) {
        await update({
          id: group.id,
          body:
            max === null
              ? { ...common, clear_max_selections: true }
              : { ...common, max_selections: max, clear_max_selections: false },
        }).unwrap();
      } else {
        await create({ ...common, max_selections: max }).unwrap();
      }
      onDone();
    } catch {
      // Shown by <AdminError>.
    }
  });

  return (
    <form noValidate onSubmit={onSubmit} className="flex flex-col gap-4">
      <AdminError error={creating.error ?? updating.error} />
      <TranslationTabs
        register={(name) => register(name)}
        errors={errors.translations}
        withDescription={false}
        nameLabel={t('admin.fields.groupName')}
      />
      <label className="flex flex-col gap-1 text-sm font-medium">
        {t('admin.fields.selectionType')}
        <select className={selectClass} {...register('selection_type')}>
          <option value="single">{t('admin.groups.single')}</option>
          <option value="multiple">{t('admin.groups.multiple')}</option>
        </select>
      </label>
      {isSingle ? (
        <Toggle
          label={t('admin.fields.required')}
          hint={t('admin.hints.requiredSingle')}
          {...register('required')}
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label={t('admin.fields.minSelections')}
            hint={t('admin.hints.minSelections')}
            inputMode="numeric"
            error={errors.min_selections?.message && t(errors.min_selections.message)}
            {...register('min_selections')}
          />
          <Field
            label={t('admin.fields.maxSelections')}
            hint={t('admin.hints.maxSelections')}
            inputMode="numeric"
            error={errors.max_selections?.message && t(errors.max_selections.message)}
            {...register('max_selections')}
          />
        </div>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <Toggle
          label={t('admin.fields.groupActive')}
          hint={t('admin.hints.groupActive')}
          {...register('is_active')}
        />
        <Field
          label={t('admin.fields.sortOrder')}
          inputMode="numeric"
          error={errors.sort_order?.message && t(errors.sort_order.message)}
          {...register('sort_order')}
        />
      </div>
      <div className="flex flex-wrap gap-3">
        <button type="submit" className={BUTTON_PRIMARY} disabled={pending}>
          {pending ? t('admin.saving') : group ? t('admin.save') : t('admin.create')}
        </button>
        <button type="button" className={BUTTON_SECONDARY} onClick={onDone}>
          {t('admin.cancel')}
        </button>
      </div>
    </form>
  );
}

// --------------------------------------------------------------------------
// Modifier (extra) form
// --------------------------------------------------------------------------

const modifierSchema = z.object({
  translations: translationsSchema(120),
  price_delta: moneyField,
  max_quantity: z
    .string()
    .trim()
    .regex(/^\d{1,2}$/, 'admin.validation.integer')
    .transform(Number)
    .refine((v) => v >= 1 && v <= 99, 'admin.validation.maxQuantity'),
  is_available: z.boolean(),
  sort_order: sortField,
});
type ModifierIn = z.input<typeof modifierSchema>;
type ModifierOut = z.output<typeof modifierSchema>;

function ModifierForm({
  groupId,
  modifier,
  onDone,
}: {
  groupId: string;
  modifier: ModifierAdminOut | null;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const [create, creating] = useCreateModifierMutation();
  const [update, updating] = useUpdateModifierMutation();
  const pending = creating.isLoading || updating.isLoading;
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ModifierIn, unknown, ModifierOut>({
    resolver: zodResolver(modifierSchema),
    defaultValues: {
      translations: modifier ? translationsToForm(modifier.translations) : emptyTranslations(),
      price_delta: modifier?.price_delta ?? '0',
      max_quantity: String(modifier?.max_quantity ?? 1),
      is_available: modifier?.is_available ?? true,
      sort_order: String(modifier?.sort_order ?? 0),
    },
  });
  const onSubmit = handleSubmit(async (values) => {
    const body = { ...values, translations: translationsToApi(values.translations, false) };
    try {
      if (modifier) {
        await update({ id: modifier.id, body }).unwrap();
      } else {
        await create({ ...body, group_id: groupId }).unwrap();
      }
      onDone();
    } catch {
      // Shown by <AdminError>.
    }
  });

  return (
    <form noValidate onSubmit={onSubmit} className="flex flex-col gap-3">
      <AdminError error={creating.error ?? updating.error} />
      <TranslationTabs
        register={(name) => register(name)}
        errors={errors.translations}
        withDescription={false}
        nameLabel={t('admin.fields.extraName')}
      />
      <div className="grid gap-3 sm:grid-cols-3">
        <Field
          label={t('admin.fields.extraPrice')}
          hint={t('admin.hints.extraPrice')}
          inputMode="decimal"
          error={errors.price_delta?.message && t(errors.price_delta.message)}
          {...register('price_delta')}
        />
        <Field
          label={t('admin.fields.maxQuantity')}
          hint={t('admin.hints.maxQuantity')}
          inputMode="numeric"
          error={errors.max_quantity?.message && t(errors.max_quantity.message)}
          {...register('max_quantity')}
        />
        <Field
          label={t('admin.fields.sortOrder')}
          inputMode="numeric"
          error={errors.sort_order?.message && t(errors.sort_order.message)}
          {...register('sort_order')}
        />
      </div>
      <Toggle label={t('admin.fields.extraOnSale')} {...register('is_available')} />
      <div className="flex flex-wrap gap-3">
        <button type="submit" className={BUTTON_PRIMARY} disabled={pending}>
          {pending ? t('admin.saving') : modifier ? t('admin.save') : t('admin.create')}
        </button>
        <button type="button" className={BUTTON_SECONDARY} onClick={onDone}>
          {t('admin.cancel')}
        </button>
      </div>
    </form>
  );
}

function GroupCard({ group }: { group: ModifierGroupAdminOut }) {
  const { t } = useTranslation();
  const [editingGroup, setEditingGroup] = useState(false);
  const [editingModifier, setEditingModifier] = useState<string | 'new' | null>(null);

  return (
    <AdminSection
      title={ruName(group.translations)}
      description={`${groupRuleText(group, t)} · ${t('admin.groups.productsCount', { count: group.products_count })}`}
      actions={
        <div className="flex flex-wrap items-center gap-2">
          {!group.is_active && <Badge tone="muted">{t('admin.status.hidden')}</Badge>}
          {!editingGroup && (
            <button
              type="button"
              className={BUTTON_SECONDARY}
              onClick={() => setEditingGroup(true)}
            >
              {t('admin.edit')}
            </button>
          )}
        </div>
      }
    >
      {editingGroup && (
        <div className="mb-4 rounded-xl border border-border p-4">
          <GroupForm group={group} onDone={() => setEditingGroup(false)} />
        </div>
      )}
      <ul className="flex flex-col gap-2" aria-label={t('admin.groups.optionsLabel')}>
        {group.modifiers.map((modifier) => (
          <li key={modifier.id} className="rounded-xl border border-border p-3">
            {editingModifier === modifier.id ? (
              <ModifierForm
                groupId={group.id}
                modifier={modifier}
                onDone={() => setEditingModifier(null)}
              />
            ) : (
              <div className="flex flex-wrap items-center gap-3">
                <div className="min-w-0 flex-1">
                  <p className="font-medium">{ruName(modifier.translations)}</p>
                  <p className="text-xs text-ink-600">
                    +<Price amount={modifier.price_delta} /> ·{' '}
                    {t('admin.groups.upTo', { count: modifier.max_quantity })}
                  </p>
                </div>
                {!modifier.is_available && (
                  <Badge tone="muted">{t('admin.status.notOnSale')}</Badge>
                )}
                <button
                  type="button"
                  className={BUTTON_SECONDARY}
                  onClick={() => setEditingModifier(modifier.id)}
                >
                  {t('admin.edit')}
                </button>
              </div>
            )}
          </li>
        ))}
        {group.modifiers.length === 0 && editingModifier !== 'new' && (
          <li className="text-sm text-ink-600">{t('admin.groups.noOptions')}</li>
        )}
        {editingModifier === 'new' ? (
          <li className="rounded-xl border border-dashed border-accent-600 p-3">
            <ModifierForm
              groupId={group.id}
              modifier={null}
              onDone={() => setEditingModifier(null)}
            />
          </li>
        ) : (
          <li>
            <button
              type="button"
              className={BUTTON_SECONDARY}
              onClick={() => setEditingModifier('new')}
            >
              {t('admin.groups.addOption')}
            </button>
          </li>
        )}
      </ul>
    </AdminSection>
  );
}

/** Extras: modifier groups with their rules and options (API §9). */
export function AdminModifiersPage() {
  const { t } = useTranslation();
  const { data, isLoading, isError, refetch } = useAdminGroupsQuery(undefined, {
    pollingInterval: ADMIN_POLLING_MS,
  });
  const [creating, setCreating] = useState(false);

  if (isError) {
    return (
      <ErrorState
        title={t('admin.loadError')}
        text={t('menu.errorText')}
        onRetry={() => void refetch()}
      />
    );
  }
  const items = data?.items ?? [];

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-extrabold">{t('admin.sections.modifiers')}</h1>
          <p className="text-sm text-ink-600">{t('admin.groups.intro')}</p>
        </div>
        {!creating && (
          <button type="button" className={BUTTON_PRIMARY} onClick={() => setCreating(true)}>
            {t('admin.groups.add')}
          </button>
        )}
      </header>
      {creating && (
        <AdminSection title={t('admin.groups.newTitle')}>
          <GroupForm group={null} onDone={() => setCreating(false)} />
        </AdminSection>
      )}
      {isLoading ? (
        <p role="status" className="text-ink-600">
          {t('admin.loading')}
        </p>
      ) : items.length === 0 ? (
        <EmptyState title={t('admin.groups.emptyTitle')} text={t('admin.groups.emptyText')} />
      ) : (
        items.map((group) => <GroupCard key={group.id} group={group} />)
      )}
    </div>
  );
}
