// The Telegram Mini App mode is decided only by the path (DEC-152 п. 1):
// `/tg` and everything under `/tg/`. It is decided once, when the page is
// opened, before the router is created: the site and the Mini App each get
// their own router, never both.
export const MINI_APP_PREFIX = '/tg';
// The Mini App router runs with this basename, so every in-app link
// (`/menu`, `/cart`, …) stays under `/tg` and can never reach a site page.
export const MINI_APP_BASENAME = MINI_APP_PREFIX;
// Start page inside the Mini App router (i.e. `/tg/menu` in the address bar).
export const MINI_APP_START = '/menu';

export function isMiniAppPath(pathname: string): boolean {
  return pathname === MINI_APP_PREFIX || pathname.startsWith(`${MINI_APP_PREFIX}/`);
}

/** True when the current document was opened on a Mini App path. */
export function isMiniAppLocation(): boolean {
  return typeof window !== 'undefined' && isMiniAppPath(window.location.pathname);
}
