import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';

import { useGetRestaurantQuery } from '../../features/catalog/catalogApi';
import {
  OpenStatusBadge,
  RestaurantContacts,
  WorkingHoursList,
} from '../../features/restaurant/components/RestaurantInfo';

/**
 * Graphite footer of the public site ("Печь", DEC-161 rev. 47) with real
 * restaurant data from GET /restaurant (UI_UX_GUIDELINES §2). `on-scrim`
 * (styles/oven.css) makes the shared restaurant blocks readable on it.
 * Staff areas keep SiteFooter.
 */
export function PublicFooter() {
  const { t } = useTranslation();
  const { data: restaurant, isError } = useGetRestaurantQuery();

  return (
    <footer data-footer="public" className="on-scrim mt-16 rounded-t-[1.75rem] lg:mt-24">
      <div className="mx-auto grid max-w-6xl gap-10 px-4 pb-12 pt-10 sm:grid-cols-2 lg:grid-cols-[2fr_1fr_1fr] lg:pt-14">
        <div className="flex flex-col items-start gap-4">
          <p className="text-xl font-bold tracking-tight [overflow-wrap:anywhere]">
            {restaurant?.name ?? t('app.name')}
          </p>
          {restaurant && <OpenStatusBadge restaurant={restaurant} />}
          <nav aria-label={t('nav.footerLabel')} className="flex gap-2">
            <Link
              to="/"
              className="-ml-3 inline-flex min-h-11 items-center px-3 font-semibold underline underline-offset-4"
            >
              {t('nav.home')}
            </Link>
            <Link
              to="/menu"
              className="inline-flex min-h-11 items-center px-3 font-semibold underline underline-offset-4"
            >
              {t('nav.menu')}
            </Link>
          </nav>
        </div>
        {restaurant && (
          <>
            {/* The phone link gets a 44 px tall target. */}
            <div className="[&_a]:inline-flex [&_a]:min-h-11 [&_a]:items-center">
              <p className="mb-3 font-semibold">{t('restaurant.contactsTitle')}</p>
              <RestaurantContacts restaurant={restaurant} />
            </div>
            <div>
              <p className="mb-3 font-semibold">{t('restaurant.hoursTitle')}</p>
              <WorkingHoursList days={restaurant.working_hours} />
            </div>
          </>
        )}
        {isError && <p className="text-sm text-ink-600">{t('restaurant.unavailable')}</p>}
      </div>
    </footer>
  );
}
