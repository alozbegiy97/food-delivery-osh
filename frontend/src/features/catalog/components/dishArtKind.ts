// Which "Печь" drawing (DEC-161 rev. 47) a category gets while its dishes
// have no photo. Other categories keep the older motifs of DishImage.

export type DishArtKind = 'pizza' | 'burger' | 'wrap';

const KIND_BY_CATEGORY = new Map<string, DishArtKind>([
  ['pizza', 'pizza'],
  ['burgers', 'burger'],
  ['shawarma', 'wrap'],
]);

/** Drawing for a category slug, or null when the category has none. */
export function dishArtKind(categorySlug: string | null | undefined): DishArtKind | null {
  return (categorySlug && KIND_BY_CATEGORY.get(categorySlug)) || null;
}
