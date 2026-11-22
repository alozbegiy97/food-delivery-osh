import { useEffect } from 'react';
import { useSelector } from 'react-redux';

import { selectTelegramActive } from './telegramSlice';
import type { TelegramWebApp } from './types';

// Closing confirmation of the Mini App (DEC-152 п. 11, DEC-157 п. 4): on
// checkout and on the demo payment, Telegram asks before the Mini App is
// closed. Pages pass `active`; the hook does nothing on the site (no Mini App
// session), on clients older than Bot API 6.2 or without the methods.
//
// Several pages may hold the confirmation at once during a route change
// (checkout → payment): React may run the new page's effect before or after
// the old page's cleanup. A counter of holders keeps the final state right —
// the confirmation is disabled only when the last holder releases it.
const CLOSING_CONFIRMATION_VERSION = '6.2';

let holders = 0;

type ClosingApp = TelegramWebApp &
  Required<Pick<TelegramWebApp, 'enableClosingConfirmation' | 'disableClosingConfirmation'>>;

function closingApp(): ClosingApp | null {
  const app = window.Telegram?.WebApp;
  if (
    !app ||
    !app.isVersionAtLeast(CLOSING_CONFIRMATION_VERSION) ||
    typeof app.enableClosingConfirmation !== 'function' ||
    typeof app.disableClosingConfirmation !== 'function'
  ) {
    return null;
  }
  return app as ClosingApp;
}

export function useTelegramClosingConfirmation(active: boolean): void {
  const miniApp = useSelector(selectTelegramActive);
  const hold = active && miniApp;

  useEffect(() => {
    if (!hold) {
      return;
    }
    const app = closingApp();
    if (!app) {
      return;
    }
    holders += 1;
    app.enableClosingConfirmation();
    return () => {
      holders = Math.max(0, holders - 1);
      if (holders === 0) {
        app.disableClosingConfirmation();
      }
    };
  }, [hold]);
}
