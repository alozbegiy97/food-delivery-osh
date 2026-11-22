import { useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router';
import { z } from 'zod';

import {
  useAdminCategoriesQuery,
  useAdminGroupsQuery,
  useAdminProductQuery,
  useCreateProductMutation,
  useDeleteProductImageMutation,
  useDeleteProductMutation,
  useUploadProductImageMutation,
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
  moneyField,
  ruName,
  skuField,
  slugField,
  sortField,
  translationsSchema,
  translationsToApi,
} from '../../features/admin/forms';
import { ErrorState } from '../../shared/components/StateViews';
import { zodResolver } from '../../shared/lib/zodResolver';
import type { ProductAdminDetail } from '../../shared/types/api';
import {
  GroupsSection,
  MainInfoSection,
  SizePricesSection,
  VariantsSection,
} from './product-editor/ProductSections';

const selectClass = 'min-h-11 rounded-lg border border-border bg-surface px-3';

// A new product is created together with its first size (DEC-06).
const createSchema = z.object({
  category_id: z.string().min(1, 'validation.required'),
  translations: translationsSchema(180),
  is_available: z.boolean(),
  is_featured: z.boolean(),
  sort_order: sortField,
  slug: slugField,
  variant: z.object({
    translations: translationsSchema(100),
    sku: skuField,
    price: moneyField,
  }),
});

function NewProductForm() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const categories = useAdminCategoriesQuery();
  const [create, state] = useCreateProductMutation();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<z.input<typeof createSchema>, unknown, z.output<typeof createSchema>>({
    resolver: zodResolver(createSchema),
    defaultValues: {
      category_id: '',
      translations: emptyTranslations(),
      is_available: true,
      is_featured: false,
      sort_order: '0',
      slug: '',
      variant: { translations: emptyTranslations(), sku: '', price: '' },
    },
  });
  const onSubmit = handleSubmit(async (values) => {
    try {
      const product = await create({
        category_id: values.category_id,
        translations: translationsToApi(values.translations),
        is_available: values.is_available,
        is_featured: values.is_featured,
        sort_order: values.sort_order,
        ...(values.slug ? { slug: values.slug } : {}),
        variants: [
          {
            translations: translationsToApi(values.variant.translations, false),
            sku: values.variant.sku,
            price: values.variant.price,
            is_available: true,
            sort_order: 0,
          },
        ],
      }).unwrap();
      void navigate(`/admin/products/${product.id}`, { replace: true });
    } catch {
      // Shown by <AdminError>.
    }
  });

  return (
    <form noValidate onSubmit={onSubmit} className="flex flex-col gap-6">
      <AdminError error={state.error} />
      <AdminSection title={t('admin.product.mainTitle')}>
        <div className="flex flex-col gap-4">
          <label className="flex flex-col gap-1 text-sm font-medium">
            {t('admin.fields.category')}
            <select
              className={selectClass}
              aria-invalid={errors.category_id ? true : undefined}
              {...register('category_id')}
            >
              <option value="">{t('admin.product.chooseCategory')}</option>
              {(categories.data?.items ?? []).map((category) => (
                <option key={category.id} value={category.id}>
                  {ruName(category.translations, category.slug)}
                  {!category.is_active ? ` (${t('admin.status.hidden')})` : ''}
                </option>
              ))}
            </select>
            {errors.category_id?.message && (
              <span className="text-sm text-danger-700">{t(errors.category_id.message)}</span>
            )}
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
              hint={t('admin.hints.slugAuto')}
              error={errors.slug?.message && t(errors.slug.message)}
              {...register('slug')}
            />
          </div>
        </div>
      </AdminSection>
      <AdminSection
        title={t('admin.product.firstSizeTitle')}
        description={t('admin.product.firstSizeIntro')}
      >
        <div className="flex flex-col gap-3">
          <TranslationTabs
            register={(name) => register(`variant.${name}`)}
            errors={errors.variant?.translations}
            withDescription={false}
            nameLabel={t('admin.fields.sizeName')}
          />
          <div className="grid gap-3 sm:grid-cols-2">
            <Field
              label={t('admin.fields.price')}
              hint={t('admin.hints.price')}
              inputMode="decimal"
              error={errors.variant?.price?.message && t(errors.variant.price.message)}
              {...register('variant.price')}
            />
            <Field
              label={t('admin.fields.sku')}
              hint={t('admin.hints.sku')}
              error={errors.variant?.sku?.message && t(errors.variant.sku.message)}
              {...register('variant.sku')}
            />
          </div>
        </div>
      </AdminSection>
      <div className="flex flex-wrap gap-3">
        <button type="submit" className={BUTTON_PRIMARY} disabled={state.isLoading}>
          {state.isLoading ? t('admin.saving') : t('admin.create')}
        </button>
        <Link to="/admin/products" className={BUTTON_SECONDARY}>
          {t('admin.cancel')}
        </Link>
      </div>
    </form>
  );
}

function ImagesSection({ product }: { product: ProductAdminDetail }) {
  const { t } = useTranslation();
  const [upload, uploading] = useUploadProductImageMutation();
  const [remove, removing] = useDeleteProductImageMutation();
  const name = ruName(product.translations, product.slug);

  return (
    <AdminSection title={t('admin.images.title')} description={t('admin.images.intro')}>
      <AdminError error={uploading.error ?? removing.error} />
      {product.images.length === 0 ? (
        <p className="mb-4 text-sm text-ink-600">{t('admin.images.none')}</p>
      ) : (
        <ul className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {product.images.map((image) => (
            <li key={image.id} className="flex flex-col gap-2 rounded-xl border border-border p-2">
              <img
                src={image.url}
                alt={image.alt_text ?? name}
                className="aspect-square w-full rounded-lg object-cover"
              />
              {image.is_primary && <Badge tone="accent">{t('admin.images.primary')}</Badge>}
              <ConfirmAction
                label={t('admin.images.delete')}
                question={t('admin.images.deleteQuestion')}
                confirmLabel={t('admin.images.deleteConfirm')}
                pending={removing.isLoading}
                onConfirm={() => void remove({ productId: product.id, imageId: image.id })}
              />
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-wrap gap-6">
        <ImagePicker
          label={
            product.images.length === 0 ? t('admin.images.upload') : t('admin.images.uploadPrimary')
          }
          pending={uploading.isLoading}
          onUpload={(file) =>
            void upload({ productId: product.id, file, altText: name, primary: true })
          }
        />
        {product.images.length > 0 && (
          <ImagePicker
            label={t('admin.images.uploadExtra')}
            pending={uploading.isLoading}
            onUpload={(file) =>
              void upload({ productId: product.id, file, altText: name, primary: false })
            }
          />
        )}
      </div>
    </AdminSection>
  );
}

function DeleteSection({ product }: { product: ProductAdminDetail }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [remove, state] = useDeleteProductMutation();
  if (product.deleted_at) {
    return null;
  }
  return (
    <AdminSection
      title={t('admin.product.deleteTitle')}
      description={t('admin.product.deleteIntro')}
    >
      <AdminError error={state.error} />
      <ConfirmAction
        label={t('admin.product.delete')}
        question={t('admin.product.deleteQuestion')}
        confirmLabel={t('admin.product.deleteConfirm')}
        pending={state.isLoading}
        onConfirm={() =>
          void remove(product.id)
            .unwrap()
            .then(() => navigate('/admin/products'))
            .catch(() => undefined)
        }
      />
    </AdminSection>
  );
}

function EditProduct({ productId }: { productId: string }) {
  const { t } = useTranslation();
  const product = useAdminProductQuery(productId);
  const categories = useAdminCategoriesQuery();
  const groups = useAdminGroupsQuery();

  if (product.isError || categories.isError || groups.isError) {
    return (
      <ErrorState
        title={t('admin.loadError')}
        text={t('menu.errorText')}
        onRetry={() => {
          void product.refetch();
          void categories.refetch();
          void groups.refetch();
        }}
      />
    );
  }
  if (!product.data || !categories.data || !groups.data) {
    return (
      <p role="status" className="text-ink-600">
        {t('admin.loading')}
      </p>
    );
  }
  const data = product.data;
  // Keys include fetched data so the forms pick up fresh server values after saving.
  const version = JSON.stringify([data.variants, data.modifier_groups]);

  return (
    <div className="flex flex-col gap-6">
      {data.deleted_at && (
        <p
          role="status"
          className="rounded-xl bg-danger-50 px-4 py-3 text-sm font-medium text-danger-700"
        >
          {t('admin.product.deletedNote')}
        </p>
      )}
      <MainInfoSection product={data} categories={categories.data.items} />
      <VariantsSection product={data} />
      <GroupsSection
        key={`g-${JSON.stringify(data.modifier_groups)}`}
        product={data}
        groups={groups.data.items}
      />
      <SizePricesSection key={`p-${version}`} product={data} groups={groups.data.items} />
      <ImagesSection product={data} />
      <DeleteSection product={data} />
    </div>
  );
}

/** Product editor: `/admin/products/new` and `/admin/products/:productId`. */
export function AdminProductEditPage() {
  const { t } = useTranslation();
  const { productId } = useParams();
  const isNew = !productId;
  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-2">
        <Link
          to="/admin/products"
          className="self-start text-sm font-semibold text-accent-800 hover:underline"
        >
          ← {t('admin.product.back')}
        </Link>
        <h1 className="text-2xl font-extrabold">
          {isNew ? t('admin.product.newTitle') : t('admin.product.editTitle')}
        </h1>
      </header>
      {isNew ? <NewProductForm /> : <EditProduct productId={productId} />}
    </div>
  );
}
