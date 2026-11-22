import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, NavLink, useLocation } from 'react-router';

import { AuthNav } from '../../features/auth/components/AuthNav';
import { CartLink } from '../../features/cart/components/CartLink';
import { LanguageSwitcher } from '../../shared/components/LanguageSwitcher';
import { OvenMark } from '../../shared/components/OvenMark';

// Public header of the "Печь" direction (DEC-161 rev. 47, MA-4.6-A2). Staff
// areas keep SiteHeader (see RootLayout). The restaurant name is never cut
// with an ellipsis: on phones it may wrap to two lines.

const navLink = ({ isActive }: { isActive: boolean }) =>
  [
    'inline-flex min-h-11 items-center rounded-full px-4 font-semibold transition-colors',
    isActive ? 'bg-cream-100 text-ink-900' : 'text-ink-600 hover:text-ink-900',
  ].join(' ');

// Shared text links (AuthNav) get a 44 px tall target here only; the staff
// header keeps them as they are.
const TALL_LINKS =
  '[&_a]:inline-flex [&_a]:min-h-11 [&_a]:min-w-11 [&_a]:items-center [&_a]:justify-center';

export function PublicHeader() {
  const { t } = useTranslation();
  const location = useLocation();
  // The mobile menu stays open only on the page where it was opened, so it
  // closes by itself after navigation.
  const [openOn, setOpenOn] = useState<string | null>(null);
  const open = openOn === location.pathname;

  const links = (
    <>
      <NavLink to="/" end className={navLink}>
        {t('nav.home')}
      </NavLink>
      <NavLink to="/menu" className={navLink}>
        {t('nav.menu')}
      </NavLink>
    </>
  );

  return (
    <header data-header="public" className="sticky top-0 z-30 bg-cream-50/90 backdrop-blur-md">
      <div className="mx-auto flex min-h-16 max-w-6xl items-center gap-2 px-4 py-2 lg:min-h-20 lg:gap-4">
        <Link
          to="/"
          className="flex min-h-11 min-w-0 flex-1 items-center gap-2.5 text-ink-900 lg:flex-none"
        >
          <OvenMark className="h-[34px] w-[30px] shrink-0" />
          <span
            data-testid="site-name"
            className="line-clamp-2 text-sm font-bold leading-tight tracking-tight [overflow-wrap:anywhere] sm:text-base"
          >
            {t('app.name')}
          </span>
        </Link>
        <nav aria-label={t('nav.mainLabel')} className="ml-4 hidden items-center gap-1 lg:flex">
          {links}
        </nav>
        <div className="ml-auto hidden items-center gap-4 lg:flex">
          <LanguageSwitcher />
          <div className={TALL_LINKS}>
            <AuthNav />
          </div>
          <CartLink />
        </div>
        <div className="flex shrink-0 items-center gap-2 lg:hidden">
          <CartLink compact />
          <button
            type="button"
            className="flex h-11 w-11 items-center justify-center rounded-full bg-surface text-ink-900 ring-1 ring-border"
            aria-expanded={open}
            aria-controls="mobile-menu"
            aria-label={open ? t('nav.closeMenu') : t('nav.openMenu')}
            onClick={() => setOpenOn(open ? null : location.pathname)}
          >
            <svg aria-hidden="true" viewBox="0 0 24 24" className="h-6 w-6">
              {open ? (
                <path
                  d="M6 6l12 12M18 6 6 18"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                />
              ) : (
                <path
                  d="M4 7h16M4 12h16M4 17h16"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                />
              )}
            </svg>
          </button>
        </div>
      </div>
      {open && (
        <div id="mobile-menu" className="border-t border-border bg-cream-50 px-4 pb-5 lg:hidden">
          <nav aria-label={t('nav.mainLabel')} className="flex flex-col gap-1 py-3">
            {links}
          </nav>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className={TALL_LINKS}>
              <AuthNav />
            </div>
            <LanguageSwitcher />
          </div>
        </div>
      )}
    </header>
  );
}
