import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router';

import { useGetCategoriesQuery, useGetProductsQuery } from '../../features/catalog/catalogApi';
import {
  CategoryChips,
  Pagination,
  SearchField,
} from '../../features/catalog/components/MenuControls';
import { ProductGrid } from '../../features/catalog/components/ProductGrid';
import { MiniAppOvenBanner } from '../../features/telegram/components/MiniAppOvenBanner';
import { EmptyState, ErrorState } from '../../shared/components/StateViews';
import { Button } from '../../shared/components/ui';
import { useLanguage } from '../../shared/i18n/useLanguage';
import { isMiniAppLocation } from '../../shared/lib/miniAppMode';

/**
 * Menu `/menu` (UI_UX_GUIDELINES §3): categories, search, product cards and
 * pages. Filters live in the URL (?category=&q=&page=) so the page can be
 * shared and the browser back button restores them.
 */
export function MenuPage() {
  const { t } = useTranslation();
  const language = useLanguage();
  const [params, setParams] = useSearchParams();
  const categoryId = params.get('category');
  const search = params.get('q') ?? '';
  const page = Math.max(1, Number(params.get('page')) || 1);

  const categories = useGetCategoriesQuery(language);
  const products = useGetProductsQuery({
    language,
    categoryId: categoryId ?? undefined,
    search: search || undefined,
    page,
  });

  const update = useCallback(
    (changes: Record<string, string | null>) => {
      setParams((current) => {
        const next = new URLSearchParams(current);
        for (const [key, value] of Object.entries(changes)) {
          if (value) {
            next.set(key, value);
          } else {
            next.delete(key);
          }
        }
        return next;
      });
    },
    [setParams],
  );
  const onSearch = useCallback(
    (value: string) => update({ q: value || null, page: null }),
    [update],
  );

  const activeCategory = categories.data?.items.find((category) => category.id === categoryId);
  const total = products.data?.pagination.total ?? 0;
  const filtered = Boolean(search || categoryId);
  const loading = products.isLoading || (products.isFetching && !products.data);
  // The Mini App opens on this page: a compact oven above, a smaller title.
  const miniApp = isMiniAppLocation();

  return (
    <div className="flex flex-col gap-5 sm:gap-6">
      {miniApp && <MiniAppOvenBanner />}
      {/* "Печь" (MA-4.6-B): a large title with the search beside it on wide screens. */}
      <div
        className={
          miniApp
            ? 'grid gap-3'
            : 'grid gap-4 pt-1 lg:grid-cols-[minmax(0,1fr)_23.75rem] lg:items-end lg:gap-8 lg:pt-4'
        }
      >
        <div className="min-w-0">
          <h1
            className={`${miniApp ? 'text-2xl' : 'text-[clamp(2.25rem,1.6rem+2.6vw,3.75rem)]'} font-extrabold leading-[1.05] tracking-[-0.035em] text-ink-900 [font-variation-settings:'opsz'_32] [overflow-wrap:anywhere]`}
          >
            {activeCategory?.name ?? t('menu.title')}
          </h1>
          {activeCategory?.description && (
            <p className="mt-2 max-w-prose text-ink-600">{activeCategory.description}</p>
          )}
        </div>
        <SearchField value={search} onSearch={onSearch} />
      </div>

      {categories.data && categories.data.items.length > 0 && (
        <CategoryChips
          categories={categories.data.items}
          selected={categoryId}
          onSelect={(id) => update({ category: id, page: null })}
        />
      )}

      {products.isError ? (
        <ErrorState
          title={t('menu.errorTitle')}
          text={t('menu.errorText')}
          onRetry={() => void products.refetch()}
          retrying={products.isFetching}
        />
      ) : !loading && total === 0 ? (
        filtered ? (
          <EmptyState
            title={t('menu.emptyTitle')}
            text={t('menu.emptyText')}
            action={
              <Button type="button" onClick={() => update({ q: null, category: null, page: null })}>
                {t('menu.resetFilters')}
              </Button>
            }
          />
        ) : (
          <EmptyState title={t('menu.emptyCatalogTitle')} text={t('menu.emptyCatalogText')} />
        )
      ) : (
        <>
          {!loading && (
            <p className="-mt-1 text-[0.9375rem] text-ink-600" aria-live="polite">
              {t('menu.found', { count: total })}
            </p>
          )}
          <div
            aria-busy={products.isFetching}
            className={products.isFetching && !loading ? 'opacity-60 transition-opacity' : ''}
          >
            <ProductGrid
              products={products.data?.items}
              categories={categories.data?.items}
              loading={loading}
              label={t('menu.productsLabel')}
              layout="catalog"
            />
          </div>
          {products.data && (
            <Pagination
              page={products.data.pagination.page}
              pages={products.data.pagination.pages}
              onPage={(next) => {
                update({ page: next > 1 ? String(next) : null });
                window.scrollTo?.({ top: 0, behavior: 'smooth' });
              }}
            />
          )}
        </>
      )}
    </div>
  );
}
