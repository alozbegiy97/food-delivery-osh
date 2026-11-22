import { useTranslation } from 'react-i18next';
import { Outlet, useLocation } from 'react-router';

import { PublicFooter } from './PublicFooter';
import { PublicHeader } from './PublicHeader';
import { SiteFooter } from './SiteFooter';
import { SiteHeader } from './SiteHeader';
import { isStaffPath } from './staffPath';

export function RootLayout() {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  // MA-4.6-A2: admin, kitchen and courier keep the previous header and footer.
  const staff = isStaffPath(pathname);

  return (
    <div className="flex min-h-screen flex-col bg-cream-50 text-ink-900">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2"
      >
        {t('app.skipToContent')}
      </a>
      {staff ? <SiteHeader /> : <PublicHeader />}
      <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 py-8">
        <Outlet />
      </main>
      {staff ? <SiteFooter /> : <PublicFooter />}
    </div>
  );
}
