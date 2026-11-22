import { useTranslation } from 'react-i18next';

import { useGetRestaurantQuery } from '../../catalog/catalogApi';
import { DishArt } from '../../catalog/components/DishArt';
import { OpenStatusBadge } from '../../restaurant/components/RestaurantInfo';

/**
 * Compact "oven" of the Mini App menu ("Печь", DEC-161 rev. 47, MA-4.6-C):
 * about 120 px, so search and categories stay right below it. The status
 * comes only from GET /restaurant (nothing is shown while it loads or when it
 * fails); the title is the existing home text. The graphite and the white
 * text are fixed tokens that the Telegram theme never replaces.
 */
export function MiniAppOvenBanner() {
  const { t } = useTranslation();
  const { data: restaurant } = useGetRestaurantQuery();

  return (
    <div
      data-testid="mini-oven"
      className="mini-oven grid min-h-[7.5rem] grid-cols-[minmax(0,1fr)_5rem] items-center gap-2 overflow-hidden rounded-3xl py-3.5 pl-4 min-[360px]:grid-cols-[minmax(0,1fr)_6.5rem] min-[360px]:py-4 min-[360px]:pl-5"
    >
      <div className="flex min-w-0 flex-col items-start gap-2">
        {restaurant && (
          // A long "closed · opens …" status wraps by words on narrow phones.
          <div className="max-w-full [&>span]:flex-wrap [&>span]:gap-x-2 [&>span]:gap-y-0 [&>span]:text-[0.8125rem]">
            <OpenStatusBadge restaurant={restaurant} />
          </div>
        )}
        <p className="text-base font-extrabold leading-[1.15] tracking-[-0.02em] text-on-scrim [font-variation-settings:'opsz'_32] [overflow-wrap:anywhere] min-[360px]:text-[1.125rem] min-[390px]:text-[1.25rem]">
          {t('home.heroTitle')}
        </p>
      </div>
      <div aria-hidden="true" className="relative h-full min-h-[5.5rem]">
        <DishArt
          lite
          kind="pizza"
          className="oven-dish absolute -right-10 top-1/2 h-32 w-32 -translate-y-1/2 min-[360px]:-right-9 min-[360px]:h-[9.5rem] min-[360px]:w-[9.5rem]"
        />
      </div>
    </div>
  );
}
