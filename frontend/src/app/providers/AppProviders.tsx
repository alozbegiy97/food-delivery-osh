import type { ReactNode } from 'react';
import { Provider } from 'react-redux';

import { SessionBootstrap } from '../../features/auth/components/SessionGate';
import { TelegramBootstrap } from '../../features/telegram/components/TelegramBootstrap';
import { isMiniAppLocation } from '../../shared/lib/miniAppMode';

import type { AppStore } from '../store/store';

interface AppProvidersProps {
  store: AppStore;
  children: ReactNode;
}

// The site restores its session from the refresh cookie; the Mini App
// (opened on /tg or /tg/*, DEC-152 п. 1) exchanges Telegram initData and
// never uses the cookie. The mode is fixed when the page is opened.
export function AppProviders({ store, children }: AppProvidersProps) {
  const Bootstrap = isMiniAppLocation() ? TelegramBootstrap : SessionBootstrap;
  return (
    <Provider store={store}>
      <Bootstrap>{children}</Bootstrap>
    </Provider>
  );
}
