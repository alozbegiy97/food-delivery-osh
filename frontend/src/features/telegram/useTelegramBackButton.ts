import { useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router';

import { MINI_APP_START } from '../../shared/lib/miniAppMode';

// BackButton (UI_UX §3, DEC-152 п. 11): bound to the history of the Mini App
// router. Its paths are relative to the basename `/tg`, so the start pages
// `/tg` and `/tg/menu` are `/` and `/menu` here; the button is hidden there.
// If the page is the first one of this launch (deep link or reload), "back"
// goes to `/tg/menu` instead of leaving the app; history never leaves /tg.
const BACK_BUTTON_VERSION = '6.1';
const START_PAGES = new Set(['/', MINI_APP_START]);

export function useTelegramBackButton(): void {
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    const app = window.Telegram?.WebApp;
    if (!app || !app.isVersionAtLeast(BACK_BUTTON_VERSION)) {
      return; // older clients: the page has its own navigation
    }
    const button = app.BackButton;
    if (START_PAGES.has(location.pathname)) {
      button.hide();
      return;
    }
    const firstEntry = location.key === 'default';
    const onClick = () => {
      if (firstEntry) {
        void navigate(MINI_APP_START, { replace: true });
      } else {
        void navigate(-1);
      }
    };
    button.onClick(onClick);
    button.show();
    return () => {
      button.offClick(onClick);
    };
  }, [location.pathname, location.key, navigate]);
}
