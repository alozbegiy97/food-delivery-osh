import { DishArt } from './DishArt';
import { dishArtKind } from './dishArtKind';
import { DishImage } from './DishImage';

interface DishPlateProps {
  imageUrl: string | null | undefined;
  categorySlug: string | null | undefined;
  /** Shape and size of the plate, e.g. `h-28 w-28 rounded-full`. */
  className?: string;
}

/**
 * A dish image on the dark "Печь" plate (DEC-161 rev. 47). A real photo from
 * the API always wins; without it pizza, burgers and shawarma get their
 * drawing, other categories keep the older motif of DishImage. Decorative:
 * the visible text next to it names the dish or category.
 */
export function DishPlate({ imageUrl, categorySlug, className = '' }: DishPlateProps) {
  const kind = dishArtKind(categorySlug);
  let content;
  if (imageUrl) {
    content = <DishImage decorative imageUrl={imageUrl} alt="" className="h-full" />;
  } else if (kind) {
    content = (
      // Small image: the light drawing without filters (cheap on weak phones).
      <DishArt lite kind={kind} className="dish-plate-art absolute inset-[7%] h-[86%] w-[86%]" />
    );
  } else {
    content = (
      <DishImage
        decorative
        imageUrl={null}
        alt=""
        categorySlug={categorySlug ?? undefined}
        className="h-full !bg-none"
      />
    );
  }
  return (
    <span
      data-dish-plate={imageUrl ? 'photo' : (kind ?? 'motif')}
      className={`dish-plate block ${className}`}
    >
      {content}
    </span>
  );
}
