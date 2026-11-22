import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { z } from 'zod';

import {
  useAddVariantMutation,
  usePutModifierPricesMutation,
  usePutProductGroupsMutation,
  useUpdateProductMutation,
  useUpdateVariantMutation,
} from '../../../features/admin/adminCatalogApi';
import {
  AdminError,
  AdminSection,
  Badge,
  BUTTON_PRIMARY,
  Field,
  SavedNote,
  Toggle,
} from '../../../features/admin/components/AdminUi';
import { TranslationTabs } from '../../../features/admin/components/TranslationTabs';
import {
  emptyTranslations,
  moneyField,
  ruName,
  skuField,
  slugField,
  sortField,
  translationsSchema,
  translationsToApi,
  translationsToForm,
} from '../../../features/admin/forms';
import { groupRuleText } from '../../../features/admin/groupRules';
import { Price } from '../../../features/catalog/components/Price';
import { zodResolver } from '../../../shared/lib/zodResolver';
import type {
  CategoryAdminOut,
  ModifierGroupAdminOut,
  ProductAdminDetail,
  VariantAdminOut,
} from '../../../shared/types/api';

const selectClass = 'min-h-11 rounded-lg border border-border bg-surface px-3';

// --------------------------------------------------------------------------
// Main information
// --------------------------------------------------------------------------

const mainSchema = z.object({
  category_id: z.string().min(1, 'validation.required'),
  translations: translationsSchema(180),
  is_available: z.boolean(),
  is_featured: z.boolean(),
  sort_order: sortField,
  slug: slugField,
});

export function MainInfoSection({
  product,
  categories,
}: {
  product: ProductAdminDetail;
  categories: CategoryAdminOut[];
}) {
  const { t } = useTranslation();
  const [update, state] = useUpdateProductMutation();
  const {
    register,
    handleSubmit,
    formState: { errors, isDirty },
    reset,
  } = useForm<z.input<typeof mainSchema>, unknown, z.output<typeof mainSchema>>({
    resolver: zodResolver(mainSchema),
    defaultValues: {
      category_id: product.category_id,
      translations: translationsToForm(product.translations),
      is_available: product.is_available,
      is_featured: product.is_featured,
      sort_order: String(product.sort_order),
      slug: product.slug,
    },
  });
  const onSubmit = handleSubmit(async (values) => {
    try {
      await update({
        id: product.id,
        body: {
          category_id: values.category_id,
          translations: translationsToApi(values.translations),
          is_available: values.is_available,
          is_featured: values.is_featured,
          sort_order: values.sort_order,
          ...(values.slug ? { slug: values.slug } : {}),
        },
      }).unwrap();
      reset(undefined, { keepValues: true });
    } catch {
      // Shown by <AdminError>.
    }
  });

  return (
    <AdminSection title={t('admin.product.mainTitle')}>
      <form noValidate onSubmit={onSubmit} className="flex flex-col gap-4">
        <AdminError error={state.error} />
        <label className="flex flex-col gap-1 text-sm font-medium">
          {t('admin.fields.category')}
          <select className={selectClass} {...register('category_id')}>
            {categories.map((category) => (
              <option key={category.id} value={category.id}>
                {ruName(category.translations, category.slug)}
                {!category.is_active ? ` (${t('admin.status.hidden')})` : ''}
              </option>
            ))}
          </select>
        </label>
        <TranslationTabs register={(name) => register(name)} errors={errors.translations} />
        <div className="grid gap-4 sm:grid-cols-2">
          <Toggle
            label={t('admin.fields.onSale')}
            hint={t('admin.hints.onSale')}
            {...register('is_available')}
          />
          <Toggle
            label={t('admin.fields.featured')}
            hint={t('admin.hints.featured')}
            {...register('is_featured')}
          />
          <Field
            label={t('admin.fields.sortOrder')}
            hint={t('admin.hints.sortOrder')}
            inputMode="numeric"
            error={errors.sort_order?.message && t(errors.sort_order.message)}
            {...register('sort_order')}
          />
          <Field
            label={t('admin.fields.slug')}
            hint={t('admin.hints.slug')}
            error={errors.slug?.message && t(errors.slug.message)}
            {...register('slug')}
          />
        </div>
        <div className="flex items-center gap-3">
          <button type="submit" className={BUTTON_PRIMARY} disabled={state.isLoading}>
            {state.isLoading ? t('admin.saving') : t('admin.save')}
          </button>
          <SavedNote show={state.isSuccess && !isDirty} />
        </div>
      </form>
    </AdminSection>
  );
}

// --------------------------------------------------------------------------
// Sizes (variants)
// --------------------------------------------------------------------------

const variantSchema = z.object({
  translations: translationsSchema(100),
  sku: skuField,
  price: moneyField,
  is_available: z.boolean(),
  sort_order: sortField,
});
type VariantIn = z.input<typeof variantSchema>;
type VariantOut = z.output<typeof variantSchema>;

function VariantForm({
  productId,
  variant,
  onCreated,
}: {
  productId: string;
  variant: VariantAdminOut | null;
  onCreated?: () => void;
}) {
  const { t } = useTranslation();
  const [add, adding] = useAddVariantMutation();
  const [update, updating] = useUpdateVariantMutation();
  const state = variant ? updating : adding;
  const {
    register,
    handleSubmit,
    formState: { errors, isDirty },
    reset,
  } = useForm<VariantIn, unknown, VariantOut>({
    resolver: zodResolver(variantSchema),
    defaultValues: {
      translations: variant ? translationsToForm(variant.translations) : emptyTranslations(),
      sku: variant?.sku ?? '',
      price: variant?.price ?? '',
      is_available: variant?.is_available ?? true,
      sort_order: String(variant?.sort_order ?? 0),
    },
  });
  const onSubmit = handleSubmit(async (values) => {
    const body = { ...values, translations: translationsToApi(values.translations, false) };
    try {
      if (variant) {
        await update({ id: variant.id, body }).unwrap();
        reset(undefined, { keepValues: true });
      } else {
        await add({ productId, body }).unwrap();
        reset();
        onCreated?.();
      }
    } catch {
      // Shown by <AdminError>.
    }
  });

  return (
    <form noValidate onSubmit={onSubmit} className="flex flex-col gap-3">
      <AdminError error={state.error} />
      <TranslationTabs
        register={(name) => register(name)}
        errors={errors.translations}
        withDescription={false}
        nameLabel={t('admin.fields.sizeName')}
      />
      <div className="grid gap-3 sm:grid-cols-3">
        <Field
          label={t('admin.fields.price')}
          hint={t('admin.hints.price')}
          inputMode="decimal"
          error={errors.price?.message && t(errors.price.message)}
          {...register('price')}
        />
        <Field
          label={t('admin.fields.sku')}
          hint={t('admin.hints.sku')}
          error={errors.sku?.message && t(errors.sku.message)}
          {...register('sku')}
        />
        <Field
          label={t('admin.fields.sortOrder')}
          inputMode="numeric"
          error={errors.sort_order?.message && t(errors.sort_order.message)}
          {...register('sort_order')}
        />
      </div>
      <Toggle label={t('admin.fields.sizeOnSale')} {...register('is_available')} />
      <div className="flex items-center gap-3">
        <button type="submit" className={BUTTON_PRIMARY} disabled={state.isLoading}>
          {state.isLoading
            ? t('admin.saving')
            : variant
              ? t('admin.save')
              : t('admin.product.addSize')}
        </button>
        <SavedNote show={Boolean(variant) && state.isSuccess && !isDirty} />
      </div>
    </form>
  );
}

export function VariantsSection({ product }: { product: ProductAdminDetail }) {
  const { t } = useTranslation();
  const [adding, setAdding] = useState(false);
  return (
    <AdminSection
      title={t('admin.product.sizesTitle')}
      description={t('admin.product.sizesIntro')}
      actions={
        !adding && (
          <button type="button" className={BUTTON_PRIMARY} onClick={() => setAdding(true)}>
            {t('admin.product.addSize')}
          </button>
        )
      }
    >
      <ul className="flex flex-col gap-4">
        {product.variants.map((variant) => (
          <li key={variant.id} className="rounded-xl border border-border p-4">
            <p className="mb-3 flex flex-wrap items-center gap-2 font-semibold">
              {ruName(variant.translations, variant.sku)} · <Price amount={variant.price} />
              {!variant.is_available && <Badge tone="muted">{t('admin.status.notOnSale')}</Badge>}
            </p>
            <VariantForm productId={product.id} variant={variant} />
          </li>
        ))}
        {adding && (
          <li className="rounded-xl border border-dashed border-accent-600 p-4">
            <p className="mb-3 font-semibold">{t('admin.product.newSize')}</p>
            <VariantForm productId={product.id} variant={null} onCreated={() => setAdding(false)} />
          </li>
        )}
      </ul>
    </AdminSection>
  );
}

// --------------------------------------------------------------------------
// Modifier groups of the product
// --------------------------------------------------------------------------

export function GroupsSection({
  product,
  groups,
}: {
  product: ProductAdminDetail;
  groups: ModifierGroupAdminOut[];
}) {
  const { t } = useTranslation();
  const [save, state] = usePutProductGroupsMutation();
  const initial = new Map(product.modifier_groups.map((link) => [link.group_id, link.sort_order]));
  const [selected, setSelected] = useState<Map<string, number>>(initial);
  const changed =
    selected.size !== initial.size ||
    [...selected].some(([id, order]) => initial.get(id) !== order);

  return (
    <AdminSection
      title={t('admin.product.groupsTitle')}
      description={t('admin.product.groupsIntro')}
    >
      <AdminError error={state.error} />
      {groups.length === 0 ? (
        <p className="text-sm text-ink-600">{t('admin.product.noGroups')}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {groups.map((group) => {
            const checked = selected.has(group.id);
            return (
              <li
                key={group.id}
                className="flex flex-wrap items-center gap-3 rounded-xl border border-border p-3"
              >
                <label className="flex flex-1 items-center gap-3">
                  <input
                    type="checkbox"
                    className="h-4 w-4 accent-accent-700"
                    checked={checked}
                    onChange={() => {
                      const next = new Map(selected);
                      if (checked) {
                        next.delete(group.id);
                      } else {
                        next.set(group.id, next.size);
                      }
                      setSelected(next);
                    }}
                  />
                  <span>
                    <span className="font-semibold">{ruName(group.translations)}</span>
                    <span className="block text-xs text-ink-600">
                      {groupRuleText(group, t)} ·{' '}
                      {t('admin.groups.optionsCount', { count: group.modifiers.length })}
                    </span>
                  </span>
                </label>
                {!group.is_active && <Badge tone="muted">{t('admin.status.hidden')}</Badge>}
                {checked && (
                  <label className="flex items-center gap-2 text-sm">
                    {t('admin.fields.position')}
                    <input
                      type="number"
                      className="min-h-10 w-20 rounded-lg border border-border px-2"
                      value={selected.get(group.id)}
                      onChange={(e) =>
                        setSelected(new Map(selected).set(group.id, Number(e.target.value) || 0))
                      }
                    />
                  </label>
                )}
              </li>
            );
          })}
        </ul>
      )}
      <div className="mt-4 flex items-center gap-3">
        <button
          type="button"
          className={BUTTON_PRIMARY}
          disabled={!changed || state.isLoading}
          onClick={() =>
            void save({
              productId: product.id,
              items: [...selected].map(([group_id, sort_order]) => ({ group_id, sort_order })),
            })
          }
        >
          {state.isLoading ? t('admin.saving') : t('admin.save')}
        </button>
        <SavedNote show={state.isSuccess && !changed} />
      </div>
    </AdminSection>
  );
}

// --------------------------------------------------------------------------
// Extra prices per size (DATABASE_SCHEMA.md §5.6)
// --------------------------------------------------------------------------

const MONEY_RE = /^\d{1,10}([.,]\d{1,2})?$/;

export function SizePricesSection({
  product,
  groups,
}: {
  product: ProductAdminDetail;
  groups: ModifierGroupAdminOut[];
}) {
  const { t } = useTranslation();
  const [save, state] = usePutModifierPricesMutation();
  const linked = product.modifier_groups
    .map((link) => groups.find((g) => g.id === link.group_id))
    .filter((g): g is ModifierGroupAdminOut => Boolean(g));
  const modifiers = linked.flatMap((group) => group.modifiers.map((m) => ({ group, modifier: m })));

  const initial: Record<string, string> = {};
  for (const variant of product.variants) {
    for (const price of variant.modifier_prices) {
      initial[`${variant.id}:${price.modifier_id}`] = price.price_delta;
    }
  }
  const [values, setValues] = useState<Record<string, string>>(initial);
  const [saving, setSaving] = useState(false);
  const invalid = Object.values(values).some((v) => v.trim() !== '' && !MONEY_RE.test(v.trim()));

  if (modifiers.length === 0 || product.variants.length === 0) {
    return null;
  }

  const onSave = async () => {
    setSaving(true);
    try {
      for (const variant of product.variants) {
        const items = modifiers
          .map(({ modifier }) => ({
            modifier,
            value: (values[`${variant.id}:${modifier.id}`] ?? '').trim(),
          }))
          .filter(({ value }) => value !== '')
          .map(({ modifier, value }) => ({
            modifier_id: modifier.id,
            price_delta: value.replace(',', '.'),
          }));
        await save({ variantId: variant.id, items }).unwrap();
      }
    } catch {
      // Shown by <AdminError>.
    } finally {
      setSaving(false);
    }
  };

  return (
    <AdminSection
      title={t('admin.product.pricesTitle')}
      description={t('admin.product.pricesIntro')}
    >
      <AdminError error={state.error} />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[28rem] text-sm">
          <thead>
            <tr className="text-left text-ink-600">
              <th className="py-2 pr-3 font-medium">{t('admin.product.extra')}</th>
              <th className="py-2 pr-3 font-medium">{t('admin.product.basePrice')}</th>
              {product.variants.map((variant) => (
                <th key={variant.id} className="py-2 pr-3 font-medium">
                  {ruName(variant.translations, variant.sku)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {modifiers.map(({ group, modifier }) => (
              <tr key={modifier.id} className="border-t border-border">
                <td className="py-2 pr-3">
                  <span className="font-medium">{ruName(modifier.translations)}</span>
                  <span className="block text-xs text-ink-600">{ruName(group.translations)}</span>
                </td>
                <td className="py-2 pr-3">
                  <Price amount={modifier.price_delta} />
                </td>
                {product.variants.map((variant) => {
                  const key = `${variant.id}:${modifier.id}`;
                  const value = values[key] ?? '';
                  const bad = value.trim() !== '' && !MONEY_RE.test(value.trim());
                  return (
                    <td key={variant.id} className="py-2 pr-3">
                      <input
                        aria-label={t('admin.product.priceFor', {
                          extra: ruName(modifier.translations),
                          size: ruName(variant.translations, variant.sku),
                        })}
                        inputMode="decimal"
                        placeholder={modifier.price_delta}
                        aria-invalid={bad || undefined}
                        value={value}
                        onChange={(e) => setValues({ ...values, [key]: e.target.value })}
                        className="min-h-10 w-28 rounded-lg border border-border px-2 aria-[invalid=true]:border-danger-700"
                      />
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-ink-600">{t('admin.product.pricesHint')}</p>
      {invalid && <p className="text-sm text-danger-700">{t('admin.validation.money')}</p>}
      <div className="mt-3 flex items-center gap-3">
        <button
          type="button"
          className={BUTTON_PRIMARY}
          disabled={invalid || saving}
          onClick={() => void onSave()}
        >
          {saving ? t('admin.saving') : t('admin.save')}
        </button>
        <SavedNote show={state.isSuccess && !saving} />
      </div>
    </AdminSection>
  );
}
