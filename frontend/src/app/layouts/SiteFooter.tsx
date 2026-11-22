import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';

import { useGetRestaurantQuery } from '../../features/catalog/catalogApi';
import {
  OpenStatusBadge,
  RestaurantContacts,
  WorkingHoursList,
} from '../../features/restaurant/components/RestaurantInfo';

/** Footer with real restaurant data from GET /restaurant (UI_UX_GUIDELINES §2). */
export function SiteFooter() {
  const { t } = useTranslation();
  const { data: restaurant, isError } = useGetRestaurantQuery();

  return (
    <footer className="mt-16 border-t border-border bg-surface">
      <div className="mx-auto grid max-w-6xl gap-8 px-4 py-10 sm:grid-cols-2 lg:grid-cols-3">
        <div className="space-y-3">
          <p className="text-lg font-bold">{restaurant?.name ?? t('app.name')}</p>
          {restaurant && <OpenStatusBadge restaurant={restaurant} />}
          <nav aria-label={t('nav.footerLabel')} className="flex gap-4 pt-2 text-sm">
            <Link to="/" className="text-accent-800 underline">
              {t('nav.home')}
            </Link>
            <Link to="/menu" className="text-accent-800 underline">
              {t('nav.menu')}
            </Link>
          </nav>
        </div>
        {restaurant && (
          <>
            <div>
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
