import type { ReactElement } from 'react';

type Motif = 'pizza' | 'burger' | 'bowl' | 'wrap' | 'cake' | 'cup' | 'plate';

// Demo dishes have no photos yet (images are uploaded in stage 4B). Until then
// a drawn illustration by category keeps cards tidy without fake photos.
const MOTIF_BY_CATEGORY: Record<string, Motif> = {
  pizza: 'pizza',
  burgers: 'burger',
  national: 'bowl',
  shawarma: 'wrap',
  salads: 'bowl',
  soups: 'bowl',
  desserts: 'cake',
  drinks: 'cup',
};

const SHAPES: Record<Motif, ReactElement> = {
  pizza: (
    <g>
      <circle cx="60" cy="60" r="42" fill="#f6c46b" />
      <circle cx="60" cy="60" r="35" fill="#e2552b" />
      <circle cx="60" cy="60" r="31" fill="#f7d77e" />
      <path d="M60 29v62M29 60h62M38 38l44 44M82 38 38 82" stroke="#e9b04f" strokeWidth="2" />
      <circle cx="48" cy="46" r="5" fill="#b8322a" />
      <circle cx="72" cy="50" r="5" fill="#b8322a" />
      <circle cx="54" cy="72" r="5" fill="#b8322a" />
      <circle cx="74" cy="72" r="4" fill="#4f8a3c" />
      <circle cx="44" cy="62" r="3.5" fill="#4f8a3c" />
    </g>
  ),
  burger: (
    <g>
      <path d="M28 54c0-16 14-26 32-26s32 10 32 26z" fill="#e9a54d" />
      <rect x="26" y="56" width="68" height="7" rx="3.5" fill="#5f9e3f" />
      <rect x="28" y="64" width="64" height="10" rx="5" fill="#7a3b23" />
      <rect x="26" y="75" width="68" height="5" rx="2.5" fill="#f2c94c" />
      <path d="M28 82h64c0 8-6 12-14 12H42c-8 0-14-4-14-12z" fill="#e9a54d" />
      <circle cx="48" cy="40" r="1.6" fill="#fff4d6" />
      <circle cx="62" cy="36" r="1.6" fill="#fff4d6" />
      <circle cx="74" cy="42" r="1.6" fill="#fff4d6" />
    </g>
  ),
  bowl: (
    <g>
      <path
        d="M44 30c-4 6 4 8 0 14M60 26c-4 6 4 8 0 14M76 30c-4 6 4 8 0 14"
        stroke="#d6b892"
        strokeWidth="3"
        fill="none"
        strokeLinecap="round"
      />
      <ellipse cx="60" cy="58" rx="36" ry="9" fill="#f0b45a" />
      <path d="M24 58h72c0 20-16 34-36 34S24 78 24 58z" fill="#c2410c" />
      <circle cx="48" cy="56" r="4" fill="#5f9e3f" />
      <circle cx="66" cy="55" r="4" fill="#f7d77e" />
    </g>
  ),
  wrap: (
    <g>
      <path d="M36 92 72 26c8 4 16 10 18 16L54 98c-8 2-16-1-18-6z" fill="#f2d09b" />
      <path d="M72 26c8 4 16 10 18 16l-10 6c-4-6-10-10-16-12z" fill="#5f9e3f" />
      <path d="M66 36c6 3 11 7 14 12l-5 3c-3-5-8-9-14-11z" fill="#c2410c" />
      <path d="M44 84 70 40" stroke="#e2b26f" strokeWidth="2" />
    </g>
  ),
  cake: (
    <g>
      <path d="M26 74 60 36l34 38z" fill="#f7e2b8" />
      <rect x="26" y="74" width="68" height="18" rx="3" fill="#d79a5a" />
      <rect x="26" y="80" width="68" height="4" fill="#f7e2b8" />
      <circle cx="60" cy="32" r="6" fill="#d23c3c" />
    </g>
  ),
  cup: (
    <g>
      <path d="M38 34h44l-6 58H44z" fill="#f2e3c6" />
      <path d="M40 46h40l-4 44H44z" fill="#c2410c" opacity="0.85" />
      <rect x="34" y="28" width="52" height="8" rx="4" fill="#9a3412" />
      <path d="M66 28 74 12" stroke="#4b525a" strokeWidth="3" strokeLinecap="round" />
    </g>
  ),
  plate: (
    <g>
      <circle cx="60" cy="60" r="40" fill="#fff" stroke="#eadfce" strokeWidth="4" />
      <circle cx="60" cy="60" r="26" fill="#f7d77e" />
    </g>
  ),
};

interface DishImageProps {
  imageUrl: string | null;
  alt: string;
  categorySlug?: string;
  className?: string;
  /**
   * The image only decorates (the name is shown next to it): an empty alt on
   * a photo, and the drawing is hidden from assistive tech. Default false.
   */
  decorative?: boolean;
}

export function DishImage({
  imageUrl,
  alt,
  categorySlug,
  className = '',
  decorative = false,
}: DishImageProps) {
  if (imageUrl) {
    return (
      <img
        src={imageUrl}
        alt={decorative ? '' : alt}
        loading="lazy"
        className={`aspect-[4/3] w-full object-cover ${className}`}
      />
    );
  }
  const motif = MOTIF_BY_CATEGORY[categorySlug ?? ''] ?? 'plate';
  return (
    <div
      className={`flex aspect-[4/3] w-full items-center justify-center bg-gradient-to-br from-accent-50 to-cream-100 ${className}`}
    >
      <svg
        viewBox="0 0 120 120"
        {...(decorative ? { 'aria-hidden': true } : { role: 'img', 'aria-label': alt })}
        className="h-3/4 w-3/4 drop-shadow-sm"
      >
        {SHAPES[motif]}
      </svg>
    </div>
  );
}
