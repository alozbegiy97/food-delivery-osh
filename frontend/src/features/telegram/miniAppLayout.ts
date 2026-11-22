import type { CSSProperties } from 'react';

// Shared measures of the Mini App layout (MA-4.2). The bottom tab bar's
// height is defined only here; the layout publishes the space the bar takes
// (its height plus the phone's bottom safe area) as a CSS variable, so the bar
// itself and anything pinned to the bottom of the page use the same value.

/** Bottom safe area: the device's inset plus Telegram's content inset. */
export const SAFE_AREA_BOTTOM =
  'calc(var(--tg-safe-area-inset-bottom, env(safe-area-inset-bottom, 0px)) + var(--tg-content-safe-area-inset-bottom, 0px))';

/** Height of the tab bar without the safe area (its tabs are 3rem high). */
export const MINI_APP_NAV_HEIGHT = '3.875rem';

/** Set on the Mini App root while the tab bar is shown. */
export const NAV_SPACE_VAR = '--mini-app-nav-space';

/** Root style that publishes the space taken by the tab bar. */
export function navSpaceStyle(): CSSProperties {
  return { [NAV_SPACE_VAR]: `calc(${MINI_APP_NAV_HEIGHT} + ${SAFE_AREA_BOTTOM})` } as CSSProperties;
}

/** `bottom` of an element pinned above the tab bar (0 when there is no bar). */
export const ABOVE_NAV_BOTTOM = `var(${NAV_SPACE_VAR}, 0px)`;
