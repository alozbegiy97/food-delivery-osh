import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';

import type { ProductSummary } from '../../../shared/types/api';
import { DishImage } from './DishImage';
import { Price } from './Price';

interface ProductCardProps {
  product: ProductSummary;
  categorySlug?: string;
}

export function ProductCard({ product, categorySlug }: ProductCardProps) {
  const { t } = useTranslation();
  const unavailable = !product.is_available;

  return (
    <li>
      <Link
        to={`/menu/${product.id}`}
        className="group flex h-full flex-col overflow-hidden rounded-card border border-border bg-surface shadow-[var(--shadow-card)] transition hover:-translate-y-0.5 hover:border-accent-600 focus-visible:-translate-y-0.5"
      >
        <div className="relative">
          <DishImage
            imageUrl={product.image_url}
            alt={product.name}
            categorySlug={categorySlug}
            className={unavailable ? 'opacity-50 grayscale' : ''}
          />
          {unavailable && (
            <span className="absolute left-3 top-3 rounded-full bg-scrim/85 px-3 py-1 text-xs font-semibold text-on-scrim">
              {t('menu.unavailable')}
            </span>
          )}
        </div>
        <div className="flex flex-1 flex-col gap-2 p-4">
          <h3 className="text-lg font-semibold leading-snug text-ink-900">{product.name}</h3>
          {product.description && (
            <p className="line-clamp-2 text-sm text-ink-600">{product.description}</p>
          )}
          <div className="mt-auto flex items-center justify-between gap-3 pt-2">
            {product.price_from ? (
              <Price amount={product.price_from} from className="text-lg font-bold text-ink-900" />
            ) : (
              <span className="text-sm text-ink-600">{t('menu.unavailable')}</span>
            )}
            <span
              aria-hidden="true"
              className={[
                'rounded-full px-4 py-2 text-sm font-semibold transition',
                unavailable
                  ? 'bg-cream-100 text-ink-600'
                  : 'bg-accent-700 text-on-accent group-hover:bg-accent-strong',
              ].join(' ')}
            >
              {unavailable ? t('menu.details') : t('menu.choose')}
            </span>
          </div>
        </div>
      </Link>
    </li>
  );
}

export function ProductCardSkeleton() {
  return (
    <li aria-hidden="true" className="overflow-hidden rounded-card border border-border bg-surface">
      <div className="aspect-[4/3] w-full animate-pulse bg-cream-100" />
      <div className="space-y-3 p-4">
        <div className="h-5 w-2/3 animate-pulse rounded bg-cream-100" />
        <div className="h-4 w-1/2 animate-pulse rounded bg-cream-100" />
        <div className="flex justify-between pt-2">
          <div className="h-6 w-20 animate-pulse rounded bg-cream-100" />
          <div className="h-9 w-24 animate-pulse rounded-full bg-cream-100" />
        </div>
      </div>
    </li>
  );
}
