import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router';

import { useGetCategoriesQuery, useGetProductQuery } from '../../features/catalog/catalogApi';
import { DishImage } from '../../features/catalog/components/DishImage';
import { Price } from '../../features/catalog/components/Price';
import { ProductConfigurator } from '../../features/catalog/components/ProductConfigurator';
import { EmptyState, ErrorState } from '../../shared/components/StateViews';
import { useLanguage } from '../../shared/i18n/useLanguage';

/** Product detail `/menu/:productId` with size, dough and extras. */
export function ProductPage() {
  const { t } = useTranslation();
  const language = useLanguage();
  const { productId = '' } = useParams();
  const product = useGetProductQuery({ id: productId, language });
  const categories = useGetCategoriesQuery(language);

  const back = (
    <Link
      to="/menu"
      className="inline-flex min-h-11 items-center text-sm font-semibold text-accent-800"
    >
      ← {t('product.back')}
    </Link>
  );

  if (product.isLoading) {
    return (
      <div aria-busy="true" className="grid gap-8 lg:grid-cols-2">
        <span className="sr-only" role="status">
          {t('product.loading')}
        </span>
        <div className="aspect-[4/3] animate-pulse rounded-card bg-cream-100" />
        <div className="space-y-4">
          <div className="h-9 w-2/3 animate-pulse rounded bg-cream-100" />
          <div className="h-5 w-1/3 animate-pulse rounded bg-cream-100" />
          <div className="h-24 animate-pulse rounded-xl bg-cream-100" />
          <div className="h-24 animate-pulse rounded-xl bg-cream-100" />
        </div>
      </div>
    );
  }

  if (product.isError || !product.data) {
    const notFound = product.error && 'status' in product.error && product.error.status === 404;
    return (
      <div className="flex flex-col gap-4">
        {back}
        {notFound || !product.isError ? (
          <EmptyState title={t('product.notFoundTitle')} text={t('product.notFoundText')} />
        ) : (
          <ErrorState
            title={t('product.errorTitle')}
            text={t('menu.errorText')}
            onRetry={() => void product.refetch()}
            retrying={product.isFetching}
          />
        )}
      </div>
    );
  }

  const data = product.data;
  const category = categories.data?.items.find((item) => item.id === data.category_id);
  const primary = data.images.find((image) => image.is_primary) ?? data.images[0];

  return (
    <div className="flex flex-col gap-4">
      {back}
      <article className="grid gap-8 lg:grid-cols-2 lg:items-start">
        <div className="overflow-hidden rounded-card border border-border bg-surface shadow-[var(--shadow-card)] lg:sticky lg:top-24">
          <DishImage
            imageUrl={primary?.url ?? data.image_url}
            alt={primary?.alt_text ?? data.name}
            categorySlug={category?.slug}
            className={data.is_available ? '' : 'opacity-60 grayscale'}
          />
        </div>
        <div className="flex flex-col gap-6">
          <header>
            {category && (
              <Link
                to={`/menu?category=${category.id}`}
                className="text-sm font-semibold uppercase tracking-wide text-accent-800"
              >
                {category.name}
              </Link>
            )}
            <h1 className="mt-1 text-3xl font-extrabold tracking-tight sm:text-4xl">{data.name}</h1>
            {data.description && <p className="mt-3 text-ink-600">{data.description}</p>}
            {data.price_from && (
              <p className="mt-3 text-lg">
                <Price
                  amount={data.price_from}
                  from={data.variants.length > 1}
                  className="font-semibold"
                />
              </p>
            )}
          </header>
          <ProductConfigurator key={`${data.id}-${language}`} product={data} />
        </div>
      </article>
    </div>
  );
}
