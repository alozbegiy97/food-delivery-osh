import type { ReactNode } from 'react';
import { useSelector } from 'react-redux';

import { selectSessionStatus } from '../../auth/authSlice';
import { selectTelegramPhase } from '../telegramSlice';
import { TelegramOnboarding } from './TelegramOnboarding';
import { TelegramLoadingScreen, TelegramPhaseScreen } from './TelegramScreens';

/**
 * Route guard of the Mini App: instead of redirecting to /login (there is
 * no login page in the Mini App, DEC-152 п. 1) every phase of the Telegram
 * session has its own screen; pages render only when signed in. Without a
 * link the user chooses a new or an existing account (MA-4.1).
 */
export function RequireTelegramSession({ children }: { children: ReactNode }) {
  const phase = useSelector(selectTelegramPhase);
  const status = useSelector(selectSessionStatus);

  if (phase === 'ready' && status === 'authenticated') {
    return children;
  }
  if (phase === 'idle' || phase === 'ready') {
    return <TelegramLoadingScreen />; // bootstrap not started yet / token being set
  }
  if (phase === 'not_linked') {
    return <TelegramOnboarding />;
  }
  return <TelegramPhaseScreen phase={phase} />;
}
