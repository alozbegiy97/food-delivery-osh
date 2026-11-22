import type { ReactElement } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';

import {
  useGetCategoriesQuery,
  useGetProductsQuery,
  useGetRestaurantQuery,
} from '../../features/catalog/catalogApi';
import { DishArt } from '../../features/catalog/components/DishArt';
import { DishPlate } from '../../features/catalog/components/DishPlate';
import { ProductGrid } from '../../features/catalog/components/ProductGrid';
import {
  OpenStatusBadge,
  RestaurantContacts,
  WorkingHoursList,
} from '../../features/restaurant/components/RestaurantInfo';
import { ErrorState } from '../../shared/components/StateViews';
import { useLanguage } from '../../shared/i18n/useLanguage';
import type { RestaurantOut } from '../../shared/types/api';

// Home `/` in the "Печь" direction (DEC-161 rev. 47, MA-4.6-A2): the oven arch
// with the neutral pizza, then categories, dishes, benefits and contacts. All
// data comes from the API and all text from the existing translations.

const POPULAR_COUNT = 4;

const H2 =
  "text-[clamp(1.5rem,1.15rem+1.3vw,2.25rem)] font-bold leading-[1.1] tracking-[-0.022em] text-ink-900 [font-variation-settings:'opsz'_32] [overflow-wrap:anywhere]";

type Benefit = 'delivery' | 'pickup' | 'custom' | 'languages';

/** Delivery and pickup only when the restaurant offers them. */
function benefitsOf(restaurant: RestaurantOut | undefined): Benefit[] {
  const items: Array<Benefit | null> = [
    restaurant?.delivery_enabled ? 'delivery' : null,
    restaurant?.pickup_enabled ? 'pickup' : null,
    'custom',
    'languages',
  ];
  return items.filter((item): item is Benefit => item !== null);
}

const ICON_PATHS: Record<Benefit, ReactElement> = {
  delivery: (
    <>
      <path d="M2 6h11v10H2zM13 10h4l4 3v3h-8" />
      <circle cx="6" cy="18" r="1.8" />
      <circle cx="17" cy="18" r="1.8" />
    </>
  ),
  pickup: (
    <>
      <path d="M5 8h14l-1 13H6Z" />
      <path d="M9 8V6a3 3 0 0 1 6 0v2" />
    </>
  ),
  custom: (
    <>
      <path d="M3 5c6-3 12-3 18 0L12 21Z" />
      <circle cx="10" cy="9" r="1.3" />
      <circle cx="14" cy="12" r="1.3" />
    </>
  ),
  languages: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3c2.5 2.6 3.7 5.6 3.7 9s-1.2 6.4-3.7 9c-2.5-2.6-3.7-5.6-3.7-9S9.5 5.6 12 3Z" />
    </>
  ),
};

function BenefitIcon({ item, className }: { item: Benefit; className: string }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      {ICON_PATHS[item]}
    </svg>
  );
}

function Hero() {
  const { t } = useTranslation();
  const { data: restaurant } = useGetRestaurantQuery();
  // Wide screens repeat the services next to the button, as in the concept.
  const facts = benefitsOf(restaurant).filter((item) => item !== 'languages');
  return (
    <section
      aria-labelledby="hero-title"
      className="grid grid-cols-1 gap-7 lg:min-h-[min(46rem,calc(100vh-9rem))] lg:grid-cols-[minmax(0,1.02fr)_minmax(0,1fr)] lg:items-center lg:gap-14"
    >
      <div
        data-testid="oven"
        className="oven-arch mx-auto mb-[15%] aspect-[1/0.86] w-full max-w-[34rem] lg:order-2 lg:mb-0 lg:aspect-[1/1.02] lg:max-w-none"
      >
        <div className="absolute bottom-[-16%] left-1/2 w-[84%] -translate-x-1/2 lg:bottom-[7%] lg:w-[80%]">
          <DishArt kind="pizza" className="oven-dish block h-auto w-full" />
        </div>
      </div>
      <div className="flex flex-col items-start gap-5 lg:gap-7 lg:pb-10">
        {restaurant && <OpenStatusBadge restaurant={restaurant} />}
        <h1
          id="hero-title"
          className="text-balance text-[clamp(2.375rem,1.35rem+4.4vw,4.75rem)] font-extrabold leading-[1.02] tracking-[-0.035em] text-ink-900 [font-variation-settings:'opsz'_32] [overflow-wrap:break-word]"
        >
          {t('home.heroTitle')}
        </h1>
        <p className="max-w-[34ch] text-[clamp(1.0625rem,1rem+0.3vw,1.25rem)] text-ink-600">
          {t('home.heroText')}
        </p>
        <Link
          to="/menu"
          className="inline-flex min-h-14 w-full items-center justify-center rounded-full bg-accent-700 px-7 text-center text-[1.0625rem] font-bold text-on-accent transition-colors hover:bg-accent-strong sm:w-auto"
        >
          {t('home.heroCta')}
        </Link>
        {facts.length > 0 && (
          <ul className="mt-2 hidden w-full max-w-[37.5rem] grid-cols-3 gap-6 border-t border-border pt-7 lg:grid">
            {facts.map((item) => (
              <li key={item} className="flex flex-col gap-2 font-semibold text-ink-900">
                <BenefitIcon item={item} className="h-[26px] w-[26px] text-accent-700" />
                {t(`home.benefits.${item}.title`)}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function ClosedNotice() {
  const { t } = useTranslation();
  const { data: restaurant } = useGetRestaurantQuery();
  if (!restaurant || restaurant.is_open_now) {
    return null;
  }
  return (
    <section
      aria-labelledby="closed-title"
      className="rounded-card border border-danger-700/30 bg-danger-50 p-5"
    >
      <h2 id="closed-title" className="font-semibold text-danger-700">
        {t('home.closedTitle')}
      </h2>
      <p className="mb-3 text-sm text-ink-600">{t('home.closedText')}</p>
      <WorkingHoursList days={restaurant.working_hours} />
    </section>
  );
}

function Categories() {
  const { t } = useTranslation();
  const language = useLanguage();
  const { data, isLoading, isError, refetch } = useGetCategoriesQuery(language);
  if (isError) {
    return (
      <ErrorState
        title={t('menu.errorTitle')}
        text={t('menu.errorText')}
        onRetry={() => void refetch()}
      />
    );
  }
  return (
    <section aria-labelledby="categories-title" className="flex flex-col gap-5">
      <h2 id="categories-title" className={H2}>
        {t('home.categoriesTitle')}
      </h2>
      {/* Phones and tablets: a rail that scrolls inside the page width. */}
      <ul className="-mx-4 flex snap-x gap-3.5 overflow-x-auto px-4 pb-2 pt-1 [scrollbar-width:none] lg:mx-0 lg:grid lg:grid-cols-8 lg:gap-5 lg:overflow-visible lg:p-0">
        {isLoading
          ? Array.from({ length: 8 }, (_, index) => (
              <li key={index} aria-hidden="true" className="w-28 shrink-0 lg:w-auto">
                <span className="dish-plate block aspect-square w-full animate-pulse rounded-full" />
                <span className="mx-auto mt-3 block h-4 w-16 rounded-full bg-cream-100" />
              </li>
            ))
          : (data?.items ?? []).map((category) => (
              <li key={category.id} className="w-28 shrink-0 snap-start lg:w-auto">
                <Link
                  to={`/menu?category=${category.id}`}
                  className="group flex flex-col items-center gap-2.5 rounded-2xl text-center"
                >
                  <DishPlate
                    imageUrl={category.image_url}
                    categorySlug={category.slug}
                    className="aspect-square w-full rounded-full transition-transform group-hover:scale-[1.03]"
                  />
                  <span className="text-sm font-semibold leading-snug text-ink-900 [overflow-wrap:anywhere] group-hover:text-accent-800 sm:text-base">
                    {category.name}
                  </span>
                </Link>
              </li>
            ))}
      </ul>
    </section>
  );
}

function Popular() {
  const { t } = useTranslation();
  const language = useLanguage();
  const categories = useGetCategoriesQuery(language);
  const featured = useGetProductsQuery({ language, featured: true, pageSize: POPULAR_COUNT });
  // No dish is marked as featured yet: show the first dishes of the menu
  // under an honest title instead of calling them "popular".
  const noFeatured = featured.isSuccess && featured.data.items.length === 0;
  const fallback = useGetProductsQuery(
    { language, pageSize: POPULAR_COUNT },
    { skip: !noFeatured },
  );
  const source = noFeatured ? fallback : featured;

  if (source.isError) {
    return null;
  }
  return (
    <section aria-labelledby="popular-title" className="flex flex-col gap-5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 id="popular-title" className={H2}>
          {noFeatured ? t('home.fromMenuTitle') : t('home.popularTitle')}
        </h2>
        <Link
          to="/menu"
          className="inline-flex min-h-11 items-center font-semibold text-accent-800 underline-offset-4 hover:underline"
        >
          {t('home.allMenu')}
        </Link>
      </div>
      {/* The menu's cards (MA-4.6.2b); their square image comes in stage B. */}
      <ProductGrid
        layout="catalog"
        products={source.data?.items}
        categories={categories.data?.items}
        loading={featured.isLoading || source.isLoading}
        skeletons={POPULAR_COUNT}
        label={noFeatured ? t('home.fromMenuTitle') : t('home.popularTitle')}
      />
    </section>
  );
}

function Benefits() {
  const { t } = useTranslation();
  const { data: restaurant } = useGetRestaurantQuery();
  return (
    <section aria-labelledby="benefits-title" className="flex flex-col gap-5">
      <h2 id="benefits-title" className={H2}>
        {t('home.benefitsTitle')}
      </h2>
      <ul className="grid gap-6 rounded-[1.75rem] bg-cream-100 px-5 py-7 sm:grid-cols-2 sm:gap-8 sm:p-9 lg:grid-cols-4">
        {benefitsOf(restaurant).map((item) => (
          <li key={item} className="flex gap-3.5">
            <BenefitIcon item={item} className="h-7 w-7 shrink-0 text-accent-700" />
            <div className="min-w-0">
              <h3 className="text-[1.0625rem] font-semibold leading-snug text-ink-900">
                {t(`home.benefits.${item}.title`)}
              </h3>
              <p className="mt-0.5 text-[0.9375rem] text-ink-600">
                {t(`home.benefits.${item}.text`)}
              </p>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Contacts() {
  const { t } = useTranslation();
  const { data: restaurant } = useGetRestaurantQuery();
  if (!restaurant) {
    return null;
  }
  return (
    <section
      aria-labelledby="contacts-title"
      className="grid gap-8 rounded-[1.75rem] border border-border bg-surface p-6 sm:grid-cols-2 sm:p-9"
    >
      <div className="flex flex-col items-start gap-4 [&_a]:inline-flex [&_a]:min-h-11 [&_a]:items-center">
        <h2 id="contacts-title" className={H2}>
          {t('restaurant.contactsTitle')}
        </h2>
        <OpenStatusBadge restaurant={restaurant} />
        <RestaurantContacts restaurant={restaurant} />
      </div>
      <div>
        <h3 className="mb-3 text-lg font-semibold text-ink-900">{t('restaurant.hoursTitle')}</h3>
        <WorkingHoursList days={restaurant.working_hours} />
      </div>
    </section>
  );
}

/** Home `/` (UI_UX_GUIDELINES §3): hero, categories, dishes, benefits, contacts. */
export function HomePage() {
  return (
    <div className="flex flex-col gap-12 lg:gap-16">
      <Hero />
      <ClosedNotice />
      <Categories />
      <Popular />
      <Benefits />
      <Contacts />
    </div>
  );
}
