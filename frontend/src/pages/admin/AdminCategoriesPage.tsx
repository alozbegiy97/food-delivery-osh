import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { z } from 'zod';

import {
  ADMIN_POLLING_MS,
  useAdminCategoriesQuery,
  useCreateCategoryMutation,
  useDeactivateCategoryMutation,
  useUpdateCategoryMutation,
  useUploadCategoryImageMutation,
} from '../../features/admin/adminCatalogApi';
import {
  AdminError,
  AdminSection,
  Badge,
  BUTTON_PRIMARY,
  BUTTON_SECONDARY,
  ConfirmAction,
  Field,
  Toggle,
} from '../../features/admin/components/AdminUi';
import { ImagePicker } from '../../features/admin/components/ImagePicker';
import { TranslationTabs } from '../../features/admin/components/TranslationTabs';
import {
  emptyTranslations,
  ruName,
  slugField,
  sortField,
  translationsSchema,
  translationsToApi,
  translationsToForm,
} from '../../features/admin/forms';
import { DishImage } from '../../features/catalog/components/DishImage';
import { EmptyState, ErrorState } from '../../shared/components/StateViews';
import { zodResolver } from '../../shared/lib/zodResolver';
import type { CategoryAdminOut } from '../../shared/types/api';

const schema = z.object({
  translations: translationsSchema(120),
  sort_order: sortField,
  is_active: z.boolean(),
  slug: slugField,
});
type FormIn = z.input<typeof schema>;
type FormOut = z.output<typeof schema>;

function CategoryForm({
  category,
  onDone,
}: {
  category: CategoryAdminOut | null;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const [create, creating] = useCreateCategoryMutation();
  const [update, updating] = useUpdateCategoryMutation();
  const [upload, uploading] = useUploadCategoryImageMutation();
  const pending = creating.isLoading || updating.isLoading;
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormIn, unknown, FormOut>({
    resolver: zodResolver(schema),
    defaultValues: {
      translations: category ? translationsToForm(category.translations) : emptyTranslations(),
      sort_order: String(category?.sort_order ?? 0),
      is_active: category?.is_active ?? true,
      slug: category?.slug ?? '',
    },
  });

  const onSubmit = handleSubmit(async (values) => {
    const body = {
      translations: translationsToApi(values.translations),
      sort_order: values.sort_order,
      is_active: values.is_active,
      ...(values.slug ? { slug: values.slug } : {}),
    };
    try {
      if (category) {
        await update({ id: category.id, body }).unwrap();
      } else {
        await create(body).unwrap();
      }
      onDone();
    } catch {
      // Shown by <AdminError>.
    }
  });

  return (
    <form noValidate onSubmit={onSubmit} className="flex flex-col gap-4">
      <AdminError error={creating.error ?? updating.error ?? uploading.error} />
      <TranslationTabs register={(name) => register(name)} errors={errors.translations} />
      <div className="grid gap-4 sm:grid-cols-2">
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
      <Toggle
        label={t('admin.fields.categoryActive')}
        hint={t('admin.hints.categoryActive')}
        {...register('is_active')}
      />
      {category && (
        <div className="flex items-center gap-4">
          <div className="w-24 overflow-hidden rounded-xl border border-border">
            <DishImage imageUrl={category.image_url} alt="" categorySlug={category.slug} />
          </div>
          <ImagePicker
            label={t('admin.images.uploadCategory')}
            pending={uploading.isLoading}
            onUpload={(file) => void upload({ id: category.id, file })}
          />
        </div>
      )}
      <div className="flex flex-wrap gap-3">
        <button type="submit" className={BUTTON_PRIMARY} disabled={pending}>
          {pending ? t('admin.saving') : category ? t('admin.save') : t('admin.create')}
        </button>
        <button type="button" className={BUTTON_SECONDARY} onClick={onDone}>
          {t('admin.cancel')}
        </button>
      </div>
    </form>
  );
}

/** Categories: list with status, create, edit, image, (de)activation (DEC-26). */
export function AdminCategoriesPage() {
  const { t } = useTranslation();
  const { data, isLoading, isError, refetch } = useAdminCategoriesQuery(undefined, {
    pollingInterval: ADMIN_POLLING_MS,
  });
  const [editing, setEditing] = useState<string | 'new' | null>(null);
  const [deactivate, deactivating] = useDeactivateCategoryMutation();
  const [update] = useUpdateCategoryMutation();

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
          <h1 className="text-2xl font-extrabold">{t('admin.sections.categories')}</h1>
          <p className="text-sm text-ink-600">{t('admin.categories.intro')}</p>
        </div>
        {editing !== 'new' && (
          <button type="button" className={BUTTON_PRIMARY} onClick={() => setEditing('new')}>
            {t('admin.categories.add')}
          </button>
        )}
      </header>

      {editing === 'new' && (
        <AdminSection title={t('admin.categories.newTitle')}>
          <CategoryForm category={null} onDone={() => setEditing(null)} />
        </AdminSection>
      )}

      <AdminError error={deactivating.error} />

      {isLoading ? (
        <p role="status" className="text-ink-600">
          {t('admin.loading')}
        </p>
      ) : items.length === 0 ? (
        <EmptyState
          title={t('admin.categories.emptyTitle')}
          text={t('admin.categories.emptyText')}
        />
      ) : (
        <ul className="flex flex-col gap-3" aria-label={t('admin.sections.categories')}>
          {items.map((category) => (
            <li key={category.id} className="rounded-card border border-border bg-surface p-4">
              {editing === category.id ? (
                <CategoryForm category={category} onDone={() => setEditing(null)} />
              ) : (
                <div className="flex flex-wrap items-center gap-4">
                  <div className="w-16 overflow-hidden rounded-lg border border-border">
                    <DishImage imageUrl={category.image_url} alt="" categorySlug={category.slug} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold">{ruName(category.translations, category.slug)}</p>
                    <p className="text-xs text-ink-600">
                      {t('admin.categories.productsCount', { count: category.products_count })} ·{' '}
                      {t('admin.fields.sortOrder')}: {category.sort_order}
                    </p>
                  </div>
                  <Badge tone={category.is_active ? 'success' : 'muted'}>
                    {category.is_active ? t('admin.status.active') : t('admin.status.hidden')}
                  </Badge>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      className={BUTTON_SECONDARY}
                      onClick={() => setEditing(category.id)}
                    >
                      {t('admin.edit')}
                    </button>
                    {category.is_active ? (
                      <ConfirmAction
                        label={t('admin.categories.hide')}
                        question={t('admin.categories.hideQuestion')}
                        confirmLabel={t('admin.categories.hideConfirm')}
                        pending={deactivating.isLoading}
                        onConfirm={() => void deactivate(category.id)}
                      />
                    ) : (
                      <button
                        type="button"
                        className={BUTTON_SECONDARY}
                        onClick={() => void update({ id: category.id, body: { is_active: true } })}
                      >
                        {t('admin.categories.show')}
                      </button>
                    )}
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
