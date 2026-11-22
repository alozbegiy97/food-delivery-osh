import type { CSSProperties } from 'react';
import { useTranslation } from 'react-i18next';
import { Outlet } from 'react-router';

import { guardMiniAppLinks } from '../linkGuard';
import { navSpaceStyle, SAFE_AREA_BOTTOM } from '../miniAppLayout';
import { useMiniAppSignedIn } from '../useMiniAppLanguage';
import { useTelegramBackButton } from '../useTelegramBackButton';
import { MiniAppNav } from './MiniAppNav';
import { RequireTelegramSession } from './RequireTelegramSession';
import { TelegramLanguageSwitcher } from './TelegramLanguageSwitcher';

// Mini App layout (UI_UX §3 "Макет"): no site header or footer, no login,
// registration or logout links; mobile width; Telegram's safe areas and the
// stable viewport height (CSS variables set by the SDK) are respected.
// Signed in, a bottom tab bar (MA-4.0) is shown; the content keeps room for
// it. Plain anchors are guarded so nothing leads into the site.
const frame: CSSProperties = {
  minHeight: 'var(--tg-viewport-stable-height, 100dvh)',
  paddingTop:
    'calc(var(--tg-safe-area-inset-top, env(safe-area-inset-top, 0px)) + var(--tg-content-safe-area-inset-top, 0px))',
  paddingBottom: SAFE_AREA_BOTTOM,
  paddingLeft: 'var(--tg-safe-area-inset-left, env(safe-area-inset-left, 0px))',
  paddingRight: 'var(--tg-safe-area-inset-right, env(safe-area-inset-right, 0px))',
};

export function TelegramLayout() {
  const { t } = useTranslation();
  const signedIn = useMiniAppSignedIn();
  useTelegramBackButton();

  return (
    <div
      data-mini-app=""
      style={signedIn ? { ...frame, ...navSpaceStyle() } : frame}
      onClickCapture={guardMiniAppLinks}
      className="flex flex-col bg-cream-50 text-ink-900"
    >
      <header className="mx-auto flex w-full max-w-xl items-center justify-between gap-3 px-4 py-3">
        <span className="text-base font-extrabold">{t('app.name')}</span>
        <TelegramLanguageSwitcher />
      </header>
      <main
        id="main"
        className={['mx-auto w-full max-w-xl flex-1 px-4', signedIn ? 'pb-24' : 'pb-6'].join(' ')}
      >
        <RequireTelegramSession>
          <Outlet />
        </RequireTelegramSession>
      </main>
      {signedIn && <MiniAppNav />}
    </div>
  );
}
