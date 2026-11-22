import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';

import { Badge, buttonClasses } from '../../../shared/components/ui';
import type { ProductSummary } from '../../../shared/types/api';
import { DishPlate } from './DishPlate';
import { Price } from './Price';

interface CatalogProductCardProps {
  product: ProductSummary;
  categorySlug?: string;
}

// Catalog card ("Печь", DEC-161 rev. 47, MA-4.6-B): a row below 640 px (a
// 104x104 image beside the text), a tile from 640 px (square image on top).
// No card frame: the dark plate behind the dish carries the shape. The whole
// card is one link; inside it there is nothing interactive. The image is
// decorative (the name is the heading) and the "Choose" pill is aria-hidden,
// so the link name is "<name> [status] <price>" without repetitions.
const LINK = 'group flex h-full gap-3.5 rounded-[1.25rem] py-1.5 sm:flex-col sm:gap-4 sm:py-0';
// The frame fixes the proportions: always square. self-start: in the row a
// stretched height would override the square.
const FRAME =
  'relative aspect-square w-26 shrink-0 self-start overflow-hidden rounded-[1.125rem] sm:w-full sm:self-auto sm:rounded-[1.375rem]';
const BODY = 'flex min-w-0 flex-1 flex-col gap-1 sm:gap-1.5';
const NAME =
  'text-[1.0625rem] font-semibold leading-snug tracking-[-0.01em] text-ink-900 transition-colors [overflow-wrap:anywhere] group-hover:text-accent-800 sm:text-[1.1875rem]';
const FOOTER = 'mt-auto flex flex-wrap items-center justify-between gap-x-3 gap-y-2 pt-1.5';
const PILL_AVAILABLE = buttonClasses({ className: 'ml-auto group-hover:bg-accent-strong' });
const PILL_UNAVAILABLE = buttonClasses({
  variant: 'secondary',
  className: 'ml-auto group-hover:ring-accent-600',
});

export function CatalogProductCard({ product, categorySlug }: CatalogProductCardProps) {
  const { t } = useTranslation();
  const unavailable = !product.is_available;
  // Strictly true: a missing or non-boolean value never shows the badge.
  const featured = product.is_featured === true;

  return (
    <li>
      <Link to={`/menu/${product.id}`} className={LINK}>
        <div className={FRAME}>
          {/* A real photo wins; otherwise the category drawing or motif. */}
          <DishPlate
            imageUrl={product.image_url}
            categorySlug={categorySlug}
            className={
              unavailable
                ? 'dish-plate-muted h-full w-full'
                : 'h-full w-full transition-transform duration-300 group-hover:scale-[1.03]'
            }
          />
        </div>
        <div className={BODY}>
          <h3 className={NAME}>{product.name}</h3>
          {(unavailable || featured) && (
            // Availability first (it decides the purchase), then "Hit" (MA-4.6.2d).
            <div className="flex flex-wrap gap-1.5">
              {unavailable && <Badge>{t('menu.unavailable')}</Badge>}
              {/* A space keeps the words apart in the link name (layout uses gap). */}
              {unavailable && featured && ' '}
              {featured && <Badge tone="accent">{t('menu.featured')}</Badge>}
            </div>
          )}
          {product.description && (
            <p className="line-clamp-2 text-sm leading-[1.45] text-ink-600 sm:text-[0.9375rem]">
              {product.description}
            </p>
          )}
          <div className={FOOTER}>
            {product.price_from ? (
              <Price
                amount={product.price_from}
                from
                className="text-[1.0625rem] font-bold tabular-nums tracking-[-0.01em] text-ink-900 sm:text-[1.1875rem]"
              />
            ) : (
              // No price: the status in its place, unless the badge above says it.
              !unavailable && <span className="text-sm text-ink-600">{t('menu.unavailable')}</span>
            )}
            <span aria-hidden="true" className={unavailable ? PILL_UNAVAILABLE : PILL_AVAILABLE}>
              {unavailable ? t('menu.details') : t('menu.choose')}
            </span>
          </div>
        </div>
      </Link>
    </li>
  );
}

const SHIMMER = 'animate-pulse bg-ink-900/10';

export function CatalogProductCardSkeleton() {
  return (
    <li aria-hidden="true" className="flex gap-3.5 py-1.5 sm:flex-col sm:gap-4 sm:py-0">
      <div className={`${FRAME} dish-plate animate-pulse`} />
      <div className={`${BODY} gap-2`}>
        <div className={`h-5 w-2/3 rounded ${SHIMMER}`} />
        <div className="mt-auto flex items-center justify-between gap-3 pt-1.5">
          <div className={`h-6 w-20 rounded ${SHIMMER}`} />
          <div className={`h-11 w-24 rounded-full ${SHIMMER}`} />
        </div>
      </div>
    </li>
  );
}
