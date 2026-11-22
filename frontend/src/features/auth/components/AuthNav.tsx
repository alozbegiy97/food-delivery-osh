import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { Link } from 'react-router';

import { useMeQuery } from '../authApi';
import { selectSessionStatus } from '../authSlice';

/** Header links: sign in / register for guests, account for users. */
export function AuthNav() {
  const { t } = useTranslation();
  const status = useSelector(selectSessionStatus);
  const { data } = useMeQuery(undefined, { skip: status !== 'authenticated' });

  if (status === 'unknown') {
    return null;
  }
  if (status === 'authenticated') {
    return (
      <span className="flex items-center gap-3 text-sm font-medium">
        {data?.roles.includes('customer') && (
          <Link to="/orders" className="text-accent-800 underline">
            {t('orders.navLink')}
          </Link>
        )}
        {data?.roles.includes('admin') ? (
          <Link to="/admin" className="text-accent-800 underline">
            {t('admin.navLink')}
          </Link>
        ) : (
          data?.roles.includes('cook') && (
            <Link to="/admin/kitchen" className="text-accent-800 underline">
              {t('admin.kitchenLink')}
            </Link>
          )
        )}
        {data?.roles.includes('courier') && (
          <Link to="/courier" className="text-accent-800 underline">
            {t('courier.navLink')}
          </Link>
        )}
        <Link to="/account" className="text-accent-800 underline">
          {data?.full_name ?? t('account.title')}
        </Link>
      </span>
    );
  }
  return (
    <nav aria-label={t('auth.navLabel')} className="flex gap-3 text-sm font-medium">
      <Link to="/login" className="text-accent-800 underline">
        {t('auth.login.title')}
      </Link>
      <Link to="/register" className="text-accent-800 underline">
        {t('auth.register.title')}
      </Link>
    </nav>
  );
}
