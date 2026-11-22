import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, NavLink, useLocation } from 'react-router';

import { AuthNav } from '../../features/auth/components/AuthNav';
import { CartLink } from '../../features/cart/components/CartLink';
import { LanguageSwitcher } from '../../shared/components/LanguageSwitcher';

function Logo() {
  const { t } = useTranslation();
  return (
    <Link to="/" className="flex items-center gap-2 text-lg font-extrabold text-ink-900">
      <svg aria-hidden="true" viewBox="0 0 32 32" className="h-9 w-9">
        <circle cx="16" cy="16" r="15" className="fill-accent-700" />
        <path d="M16 5 27 23H5z" className="fill-cream-50" />
        <circle cx="13" cy="17" r="2" className="fill-accent-700" />
        <circle cx="19" cy="19" r="1.6" className="fill-accent-700" />
        <circle cx="16" cy="12" r="1.4" className="fill-accent-700" />
      </svg>
      <span className="leading-tight">{t('app.name')}</span>
    </Link>
  );
}

const navLink = ({ isActive }: { isActive: boolean }) =>
  [
    'rounded-full px-4 py-2 text-sm font-semibold transition',
    isActive ? 'bg-accent-50 text-accent-800' : 'text-ink-900 hover:bg-cream-100',
  ].join(' ');

export function SiteHeader() {
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
    <header className="sticky top-0 z-30 border-b border-border bg-surface/95 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3">
        <Logo />
        <nav aria-label={t('nav.mainLabel')} className="hidden items-center gap-1 md:flex">
          {links}
        </nav>
        <div className="hidden items-center gap-4 md:flex">
          <CartLink />
          <AuthNav />
          <LanguageSwitcher />
        </div>
        <div className="md:hidden">
          <CartLink />
        </div>
        <button
          type="button"
          className="flex h-11 w-11 items-center justify-center rounded-full ring-1 ring-border md:hidden"
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
      {open && (
        <div id="mobile-menu" className="border-t border-border px-4 pb-4 md:hidden">
          <nav aria-label={t('nav.mainLabel')} className="flex flex-col gap-1 py-3">
            {links}
          </nav>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <AuthNav />
            <LanguageSwitcher />
          </div>
        </div>
      )}
    </header>
  );
}
