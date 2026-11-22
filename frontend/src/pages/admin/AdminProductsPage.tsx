import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';

import {
  ADMIN_POLLING_MS,
  useAdminCategoriesQuery,
  useAdminProductsQuery,
  type AdminProductsArgs,
} from '../../features/admin/adminCatalogApi';
import { Badge, BUTTON_PRIMARY } from '../../features/admin/components/AdminUi';
import { ruName } from '../../features/admin/forms';
import { DishImage } from '../../features/catalog/components/DishImage';
import { Price } from '../../features/catalog/components/Price';
import { EmptyState, ErrorState } from '../../shared/components/StateViews';

/** Products: filters by category, name and status; links to the editor. */
export function AdminProductsPage() {
  const { t } = useTranslation();
  const [categoryId, setCategoryId] = useState('');
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<AdminProductsArgs['status']>('active');
  const categories = useAdminCategoriesQuery();
  const products = useAdminProductsQuery(
    { categoryId: categoryId || undefined, search: search.trim() || undefined, status },
    { pollingInterval: ADMIN_POLLING_MS },
  );
  const categoryById = new Map((categories.data?.items ?? []).map((c) => [c.id, c]));
  const select = 'min-h-11 rounded-lg border border-border bg-surface px-3';

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-extrabold">{t('admin.sections.products')}</h1>
          <p className="text-sm text-ink-600">{t('admin.products.intro')}</p>
        </div>
        <Link to="/admin/products/new" className={BUTTON_PRIMARY}>
          {t('admin.products.add')}
        </Link>
      </header>

      <div className="grid gap-3 sm:grid-cols-3">
        <label className="flex flex-col gap-1 text-sm font-medium">
          {t('admin.fields.category')}
          <select
            className={select}
            value={categoryId}
            onChange={(e) => setCategoryId(e.target.value)}
          >
            <option value="">{t('admin.products.allCategories')}</option>
            {(categories.data?.items ?? []).map((category) => (
              <option key={category.id} value={category.id}>
                {ruName(category.translations, category.slug)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm font-medium">
          {t('admin.products.search')}
          <input
            type="search"
            className={select}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('admin.products.searchPlaceholder')}
          />
        </label>
        <label className="flex flex-col gap-1 text-sm font-medium">
          {t('admin.products.status')}
          <select
            className={select}
            value={status}
            onChange={(e) => setStatus(e.target.value as AdminProductsArgs['status'])}
          >
            <option value="active">{t('admin.products.statusActive')}</option>
            <option value="deleted">{t('admin.products.statusDeleted')}</option>
            <option value="all">{t('admin.products.statusAll')}</option>
          </select>
        </label>
      </div>

      {products.isError ? (
        <ErrorState
          title={t('admin.loadError')}
          text={t('menu.errorText')}
          onRetry={() => void products.refetch()}
        />
      ) : products.isLoading ? (
        <p role="status" className="text-ink-600">
          {t('admin.loading')}
        </p>
      ) : (products.data?.items.length ?? 0) === 0 ? (
        <EmptyState title={t('admin.products.emptyTitle')} text={t('admin.products.emptyText')} />
      ) : (
        <>
          <p className="text-sm text-ink-600">
            {t('admin.products.total', { count: products.data?.total ?? 0 })}
          </p>
          <ul className="flex flex-col gap-3" aria-label={t('admin.sections.products')}>
            {products.data?.items.map((product) => {
              const category = categoryById.get(product.category_id);
              return (
                <li key={product.id}>
                  <Link
                    to={`/admin/products/${product.id}`}
                    className="flex flex-wrap items-center gap-4 rounded-card border border-border bg-surface p-4 transition hover:border-accent-600"
                  >
                    <div className="w-16 overflow-hidden rounded-lg border border-border">
                      <DishImage
                        imageUrl={product.image_url}
                        alt=""
                        categorySlug={category?.slug}
                      />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="font-semibold">{product.name}</p>
                      <p className="text-xs text-ink-600">
                        {category ? ruName(category.translations, category.slug) : '—'} ·{' '}
                        {t('admin.products.variantsCount', { count: product.variants_count })}
                      </p>
                    </div>
                    <span className="text-sm font-semibold">
                      {product.price_from ? <Price amount={product.price_from} from /> : '—'}
                    </span>
                    <span className="flex flex-wrap gap-1">
                      {product.deleted_at ? (
                        <Badge tone="danger">{t('admin.status.deleted')}</Badge>
                      ) : (
                        <Badge tone={product.is_available ? 'success' : 'muted'}>
                          {product.is_available
                            ? t('admin.status.onSale')
                            : t('admin.status.notOnSale')}
                        </Badge>
                      )}
                      {product.is_featured && (
                        <Badge tone="accent">{t('admin.status.featured')}</Badge>
                      )}
                      {category && !category.is_active && (
                        <Badge tone="muted">{t('admin.status.categoryHidden')}</Badge>
                      )}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}
