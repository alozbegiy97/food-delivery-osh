import { useTranslation } from 'react-i18next';
import { NavLink, Outlet } from 'react-router';

/**
 * Separate mobile-first courier cabinet at `/courier` (DEC-151 п. 9,
 * UI_UX_GUIDELINES §5): no admin sidebar, a narrow column and two tabs.
 */
export function CourierLayout() {
  const { t } = useTranslation();
  const tab = ({ isActive }: { isActive: boolean }) =>
    [
      'flex min-h-11 flex-1 items-center justify-center rounded-full px-4 text-sm font-semibold transition',
      isActive ? 'bg-accent-700 text-white' : 'text-ink-900 ring-1 ring-border hover:bg-cream-100',
    ].join(' ');

  return (
    <div className="mx-auto flex w-full max-w-xl flex-col gap-5">
      <header className="flex flex-col gap-3">
        <h1 className="text-2xl font-extrabold">{t('courier.title')}</h1>
        <nav aria-label={t('courier.navLabel')} className="flex gap-2">
          <NavLink to="/courier" end className={tab}>
            {t('courier.tabs.active')}
          </NavLink>
          <NavLink to="/courier/history" className={tab}>
            {t('courier.tabs.history')}
          </NavLink>
        </nav>
      </header>
      <Outlet />
    </div>
  );
}
