import { useSelector } from 'react-redux';

import { useMeQuery } from '../auth/authApi';
import { selectSessionStatus } from '../auth/authSlice';
import { useLanguage } from '../../shared/i18n/useLanguage';
import { useGetCartQuery } from './cartApi';

export type CartAccess = 'checking' | 'guest' | 'staff' | 'customer';

/**
 * Who may use the cart: only users with the `customer` role (DEC-13). The
 * backend checks the role again on every request.
 */
export function useCartAccess(): CartAccess {
  const status = useSelector(selectSessionStatus);
  const me = useMeQuery(undefined, { skip: status !== 'authenticated' });
  if (status === 'unknown' || (status === 'authenticated' && !me.data)) {
    return 'checking';
  }
  if (status === 'anonymous') {
    return 'guest';
  }
  return me.data?.roles.includes('customer') ? 'customer' : 'staff';
}

/** The cart of the signed-in customer; skipped for guests and staff. */
export function useCustomerCart() {
  const access = useCartAccess();
  const language = useLanguage();
  const cart = useGetCartQuery(language, { skip: access !== 'customer' });
  return { access, cart };
}
