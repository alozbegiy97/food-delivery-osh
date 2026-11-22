import type { CategoryOut, ProductSummary } from '../../../shared/types/api';
import { CatalogProductCard, CatalogProductCardSkeleton } from './CatalogProductCard';
import { ProductCard, ProductCardSkeleton } from './ProductCard';

interface ProductGridProps {
  products: ProductSummary[] | undefined;
  categories: CategoryOut[] | undefined;
  loading: boolean;
  skeletons?: number;
  label: string;
  /**
   * 'classic' (default): the original cards and grid (home page until
   * MA-4.6.3); 'catalog': rows on phones, square tiles from 640 px (menu and
   * home; "Печь", MA-4.6-B).
   */
  layout?: 'classic' | 'catalog';
}

const GRID = 'grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4';
const CATALOG_GRID =
  'grid grid-cols-1 gap-2 sm:grid-cols-2 sm:gap-x-6 sm:gap-y-9 lg:grid-cols-3 lg:gap-x-7 lg:gap-y-11 xl:grid-cols-4';

export function ProductGrid({
  products,
  categories,
  loading,
  skeletons = 8,
  label,
  layout = 'classic',
}: ProductGridProps) {
  const catalog = layout === 'catalog';
  const grid = catalog ? CATALOG_GRID : GRID;
  const Card = catalog ? CatalogProductCard : ProductCard;
  const Skeleton = catalog ? CatalogProductCardSkeleton : ProductCardSkeleton;

  if (loading) {
    return (
      <ul className={grid} aria-busy="true" aria-label={label}>
        {Array.from({ length: skeletons }, (_, index) => (
          <Skeleton key={index} />
        ))}
      </ul>
    );
  }
  const slugById = new Map((categories ?? []).map((category) => [category.id, category.slug]));
  return (
    <ul className={grid} aria-label={label}>
      {(products ?? []).map((product) => (
        <Card key={product.id} product={product} categorySlug={slugById.get(product.category_id)} />
      ))}
    </ul>
  );
}
