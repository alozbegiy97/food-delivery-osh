import type { ReactElement } from 'react';
import { useTranslation } from 'react-i18next';
import { NavLink } from 'react-router';

import { useCustomerCart } from '../../cart/useCartAccess';
import { NAV_SPACE_VAR, SAFE_AREA_BOTTOM } from '../miniAppLayout';

// Bottom navigation of the Mini App (decision Q2 of MA-4): four tabs inside
// the Mini App router (basename /tg). The cart count comes from the same
// server cart query as the site's CartLink — no second cart logic.

// "Печь" (MA-4.6-C): every tab has an icon; the current one is marked three
// ways — accent colour, a tinted pill behind the icon and bold text — so it
// reads without colour alone. accent-50/accent-800 change together in the
// dark Telegram theme (theme.ts), ink-600 follows Telegram's hint colour.
// The tab height (min-h-12) and the bar measures are unchanged.
const tab = ({ isActive }: { isActive: boolean }) =>
  [
    'group relative flex min-h-12 flex-1 flex-col items-center justify-center gap-0.5 rounded-xl px-1 text-xs transition-colors',
    isActive ? 'font-bold text-accent-800' : 'font-semibold text-ink-600 hover:text-ink-900',
  ].join(' ');

const PILL =
  'relative flex h-7 w-12 items-center justify-center rounded-full transition-colors group-aria-[current=page]:bg-accent-50';

type TabIcon = 'menu' | 'cart' | 'orders' | 'account';

const ICONS: Record<TabIcon, ReactElement> = {
  menu: (
    <>
      <path d="M12 4a9 9 0 0 1 9 9H3a9 9 0 0 1 9-9Z" />
      <path d="M3 17h18M6 20.5h12" />
    </>
  ),
  cart: (
    <>
      <path d="M3 4h2l2.2 10.2a2 2 0 0 0 2 1.6h7.6a2 2 0 0 0 2-1.5L20.5 8H6.2" />
      <circle cx="10" cy="20" r="1.3" />
      <circle cx="17" cy="20" r="1.3" />
    </>
  ),
  orders: (
    <>
      <path d="M6 3h12v18l-3-2-3 2-3-2-3 2Z" />
      <path d="M9 8h6M9 12h6" />
    </>
  ),
  account: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6" />
    </>
  ),
};

function Icon({ name }: { name: TabIcon }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-[1.375rem] w-[1.375rem]"
    >
      {ICONS[name]}
    </svg>
  );
}

function CartCount({ count }: { count: number }) {
  if (count <= 0) {
    return null;
  }
  return (
    <span
      aria-hidden="true"
      data-testid="mini-cart-badge"
      className="absolute -right-0.5 -top-1.5 min-w-5 rounded-full bg-accent-700 px-1.5 text-center text-[11px] font-bold leading-5 text-on-accent"
    >
      {count}
    </span>
  );
}

export function MiniAppNav() {
  const { t } = useTranslation();
  const { access, cart } = useCustomerCart();
  const count = access === 'customer' ? (cart.data?.items_count ?? 0) : 0;

  return (
    <nav
      aria-label={t('telegram.nav.label')}
      className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-surface/95 backdrop-blur"
      // Exactly the space the layout reserves (MINI_APP_NAV_HEIGHT + safe area).
      style={{ height: `var(${NAV_SPACE_VAR})`, paddingBottom: SAFE_AREA_BOTTOM }}
    >
      <div className="mx-auto flex w-full max-w-xl gap-1 px-2 py-1.5">
        <NavLink to="/menu" className={tab}>
          <span className={PILL}>
            <Icon name="menu" />
          </span>
          {t('telegram.nav.menu')}
        </NavLink>
        <NavLink to="/cart" className={tab} aria-label={t('cart.linkLabel', { count })}>
          <span className={PILL}>
            <Icon name="cart" />
            <CartCount count={count} />
          </span>
          {t('telegram.nav.cart')}
        </NavLink>
        <NavLink to="/orders" className={tab}>
          <span className={PILL}>
            <Icon name="orders" />
          </span>
          {t('telegram.nav.orders')}
        </NavLink>
        <NavLink to="/account" className={tab}>
          <span className={PILL}>
            <Icon name="account" />
          </span>
          {t('telegram.nav.account')}
        </NavLink>
      </div>
    </nav>
  );
}
