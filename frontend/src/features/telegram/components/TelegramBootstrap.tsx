import { useEffect, type ReactNode } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import { sessionEnded, sessionStarted } from '../../auth/authSlice';
import { loadTelegramSdk } from '../sdk';
import { selectTelegramAttempt, telegramPhaseChanged, telegramStarted } from '../telegramSlice';
import { exchangeTelegramSession, phaseFor } from '../telegramSession';
import { applyTelegramTheme } from '../theme';
import type { TelegramWebApp } from '../types';

// ready()/expand() and the theme subscription happen once per SDK object,
// also under React StrictMode (effects run twice in development).
const launched = new WeakSet<TelegramWebApp>();

function launch(app: TelegramWebApp): void {
  if (launched.has(app)) {
    return;
  }
  launched.add(app);
  app.ready();
  app.expand();
  applyTelegramTheme(app);
  app.onEvent('themeChanged', () => applyTelegramTheme(app));
}

/**
 * Session of the Mini App (DEC-142, DEC-152): replaces SessionBootstrap on
 * `/tg` and `/tg/*`. It never touches the refresh cookie: the SDK is loaded,
 * initData is exchanged for an access token kept in memory, and every
 * outcome becomes a phase shown by RequireTelegramSession. "Повторить"
 * (telegramRetried) runs it again.
 */
export function TelegramBootstrap({ children }: { children: ReactNode }) {
  const dispatch = useDispatch();
  const attempt = useSelector(selectTelegramAttempt);

  useEffect(() => {
    let cancelled = false;
    dispatch(telegramStarted());
    void (async () => {
      let app: TelegramWebApp;
      try {
        app = await loadTelegramSdk();
      } catch {
        if (!cancelled) {
          dispatch(telegramPhaseChanged('error'));
        }
        return;
      }
      if (cancelled) {
        return;
      }
      launch(app);
      // Shared with parallel 401 re-authentications: one exchange at a time.
      const outcome = await exchangeTelegramSession();
      if (cancelled) {
        return;
      }
      if (outcome.kind === 'ok') {
        dispatch(sessionStarted(outcome.token));
      } else {
        dispatch(sessionEnded());
      }
      dispatch(telegramPhaseChanged(phaseFor(outcome)));
    })();
    return () => {
      cancelled = true;
    };
  }, [dispatch, attempt]);

  return children;
}
