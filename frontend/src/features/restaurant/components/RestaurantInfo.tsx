import { useTranslation } from 'react-i18next';

import { LOCALE_TAGS, useLanguage } from '../../../shared/i18n/useLanguage';
import type { RestaurantOut, WorkingDayOut } from '../../../shared/types/api';
import { Price } from '../../catalog/components/Price';
import { RESTAURANT_TIMEZONE, restaurantWeekday } from '../time';

// The weekday name comes from our translations, not from Intl: browsers lack
// Uzbek (and partly Kyrgyz) weekday names and fall back to English or
// Russian ("Mon 10:00"). The weekday and the time are both taken in the
// restaurant's time zone, as before.
function useOpeningText(nextOpeningAt: string | null): string | null {
  const { t } = useTranslation();
  const language = useLanguage();
  if (!nextOpeningAt) {
    return null;
  }
  const date = new Date(nextOpeningAt);
  const locale = LOCALE_TAGS[language];
  const weekday = t(`restaurant.weekdays.${restaurantWeekday(date)}`).toLocaleLowerCase(locale);
  const time = new Intl.DateTimeFormat(locale, {
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
    timeZone: RESTAURANT_TIMEZONE,
  }).format(date);
  return `${weekday} ${time}`;
}

export function OpenStatusBadge({ restaurant }: { restaurant: RestaurantOut }) {
  const { t } = useTranslation();
  const when = useOpeningText(restaurant.next_opening_at);
  const open = restaurant.is_open_now;
  return (
    <span
      className={[
        'inline-flex items-center gap-2 rounded-full px-3 py-1 text-sm font-semibold',
        open ? 'bg-success-50 text-success-700' : 'bg-danger-50 text-danger-700',
      ].join(' ')}
    >
      <span
        aria-hidden="true"
        className={`h-2 w-2 rounded-full ${open ? 'bg-success-700' : 'bg-danger-700'}`}
      />
      {open ? t('restaurant.openNow') : t('restaurant.closedNow')}
      {!open && when && <span className="font-normal">· {t('restaurant.opensAt', { when })}</span>}
    </span>
  );
}

function hoursText(day: WorkingDayOut, dayOff: string): string {
  if (day.is_closed || !day.opens_at || !day.closes_at) {
    return dayOff;
  }
  return `${day.opens_at}–${day.closes_at}`;
}

export function WorkingHoursList({ days }: { days: WorkingDayOut[] }) {
  const { t } = useTranslation();
  const today = restaurantWeekday();
  return (
    <dl className="grid grid-cols-[1fr_auto] gap-x-6 gap-y-1 text-sm">
      {days.map((day) => {
        const isToday = day.weekday === today;
        return (
          <div key={day.weekday} className="contents">
            <dt className={isToday ? 'font-semibold text-ink-900' : 'text-ink-600'}>
              {t(`restaurant.weekdays.${day.weekday}`)}
              {isToday && <span className="sr-only"> ({t('restaurant.today')})</span>}
            </dt>
            <dd className={isToday ? 'font-semibold text-ink-900' : 'text-ink-600'}>
              {hoursText(day, t('restaurant.dayOff'))}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

/** Contacts and service options; only data the API provides. */
export function RestaurantContacts({ restaurant }: { restaurant: RestaurantOut }) {
  const { t } = useTranslation();
  return (
    <dl className="space-y-3 text-sm">
      {restaurant.address && (
        <div>
          <dt className="text-ink-600">{t('restaurant.address')}</dt>
          <dd className="font-medium text-ink-900">{restaurant.address}</dd>
        </div>
      )}
      {restaurant.phone && (
        <div>
          <dt className="text-ink-600">{t('restaurant.phone')}</dt>
          <dd>
            <a href={`tel:${restaurant.phone}`} className="font-medium text-accent-800 underline">
              {restaurant.phone}
            </a>
          </dd>
        </div>
      )}
      <div>
        <dt className="text-ink-600">{t('restaurant.services')}</dt>
        <dd className="font-medium text-ink-900">
          {[
            restaurant.delivery_enabled ? t('restaurant.delivery') : null,
            restaurant.pickup_enabled ? t('restaurant.pickup') : null,
          ]
            .filter(Boolean)
            .join(' · ') || t('restaurant.noServices')}
        </dd>
      </div>
      {Number(restaurant.min_order_amount) > 0 && (
        <div>
          <dt className="text-ink-600">{t('restaurant.minOrder')}</dt>
          <dd className="font-medium text-ink-900">
            <Price amount={restaurant.min_order_amount} />
          </dd>
        </div>
      )}
    </dl>
  );
}
