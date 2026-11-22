import { useTranslation } from 'react-i18next';
import { NavLink } from 'react-router';

import { useCustomerCart } from '../useCartAccess';

interface CartLinkProps {
  /**
   * Icon-only round 44x44 button (public header on phones, MA-4.6-A2). The
   * accessible name stays the same: it comes from aria-label, not the text.
   */
  compact?: boolean;
}

/** Header link to the cart with the number of items from the server. */
export function CartLink({ compact = false }: CartLinkProps = {}) {
  const { t } = useTranslation();
  const { access, cart } = useCustomerCart();
  if (access !== 'customer') {
    return null;
  }
  const count = cart.data?.items_count ?? 0;
  return (
    <NavLink
      to="/cart"
      aria-label={t('cart.linkLabel', { count })}
      className={({ isActive }) =>
        [
          compact
            ? 'relative inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full ring-1 ring-border transition'
            : 'relative inline-flex min-h-11 items-center gap-2 rounded-full px-4 text-sm font-semibold ring-1 ring-border transition',
          isActive ? 'bg-accent-50 text-accent-800' : 'text-ink-900 hover:bg-cream-100',
          compact && !isActive && 'bg-surface',
        ]
          .filter(Boolean)
          .join(' ')
      }
    >
      <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5">
        <path
          d="M3 4h2l2.4 10.2a2 2 0 0 0 2 1.6h7.7a2 2 0 0 0 1.9-1.5L21 8H6.2"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle cx="10" cy="20" r="1.5" fill="currentColor" />
        <circle cx="17" cy="20" r="1.5" fill="currentColor" />
      </svg>
      {!compact && <span>{t('cart.title')}</span>}
      {count > 0 && (
        <span
          aria-hidden="true"
          data-testid="cart-badge"
          className={
            compact
              ? 'absolute -right-1 -top-1 min-w-5 rounded-full bg-accent-700 px-1.5 text-center text-xs font-bold leading-5 text-white'
              : 'rounded-full bg-accent-700 px-2 py-0.5 text-xs font-bold text-white'
          }
        >
          {count}
        </span>
      )}
    </NavLink>
  );
}
