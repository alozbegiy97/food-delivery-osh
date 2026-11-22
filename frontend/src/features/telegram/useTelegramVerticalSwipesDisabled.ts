import { useEffect } from 'react';
import { useSelector } from 'react-redux';

import { selectTelegramActive } from './telegramSlice';
import type { TelegramWebApp } from './types';

// Vertical swipes of the Mini App (DEC-152 п. 11): while a map is on screen,
// dragging it vertically must not close or minimize the Mini App, so the
// swipes are turned off and turned back on when the map is gone. Telegram
// recommends keeping them enabled otherwise (Bot API 7.7).
//
// Nothing happens on the site (no Mini App session), on clients older than
// Bot API 7.7, without the methods, or when the current state is not a known
// boolean. Swipes are disabled only if they were reliably enabled
// (`isVerticalSwipesEnabled === true`); the last holder restores exactly that.
// A counter of holders keeps the state right when maps mount and unmount in
// any order (the same scheme as useTelegramClosingConfirmation).
const VERTICAL_SWIPES_VERSION = '7.7';

let holders = 0;
let restore: (() => void) | null = null;

type SwipesApp = TelegramWebApp &
  Required<Pick<TelegramWebApp, 'disableVerticalSwipes' | 'enableVerticalSwipes'>>;

function swipesApp(): SwipesApp | null {
  const app = window.Telegram?.WebApp;
  if (
    !app ||
    !app.isVersionAtLeast(VERTICAL_SWIPES_VERSION) ||
    typeof app.disableVerticalSwipes !== 'function' ||
    typeof app.enableVerticalSwipes !== 'function'
  ) {
    return null;
  }
  return app as SwipesApp;
}

export function useTelegramVerticalSwipesDisabled(active: boolean): void {
  const miniApp = useSelector(selectTelegramActive);
  const hold = active && miniApp;

  useEffect(() => {
    if (!hold) {
      return;
    }
    const app = swipesApp();
    if (!app) {
      return;
    }
    holders += 1;
    if (holders === 1) {
      // The first holder decides from the state before any map was shown.
      if (app.isVerticalSwipesEnabled === true) {
        app.disableVerticalSwipes();
        restore = () => app.enableVerticalSwipes();
      } else {
        restore = null; // already off, or unknown: leave it as it is
      }
    }
    return () => {
      holders = Math.max(0, holders - 1);
      if (holders === 0) {
        const back = restore;
        restore = null;
        back?.();
      }
    };
  }, [hold]);
}
