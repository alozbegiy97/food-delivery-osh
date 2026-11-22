import { vi } from 'vitest';

import type { TelegramThemeParams, TelegramWebApp } from '../features/telegram/types';

// A fake `window.Telegram.WebApp` for Vitest (DEC-142 K3-A). It carries an
// opaque initData string: the frontend never interprets it, the backend is
// mocked by the tests.
export const FAKE_INIT_DATA =
  'query_id=AAE&user=%7B%22id%22%3A1%7D&auth_date=1&hash=' + 'a'.repeat(64);

export interface FakeTelegram {
  app: TelegramWebApp;
  backButton: { visible: boolean; click(): void };
  /** Current state of the closing confirmation (enable/disableClosingConfirmation). */
  closing: { enabled: boolean };
  /** Current isVerticalSwipesEnabled (enable/disableVerticalSwipes). */
  swipes: { enabled: unknown };
  emit(event: 'themeChanged'): void;
  setTheme(scheme: 'light' | 'dark', params: TelegramThemeParams): void;
}

export function installTelegram(
  options: {
    initData?: string;
    version?: string;
    colorScheme?: 'light' | 'dark';
    themeParams?: TelegramThemeParams;
    /**
     * Initial isVerticalSwipesEnabled; any given value (also an explicit
     * undefined or a non-boolean) is kept as is; true when not given.
     */
    verticalSwipesEnabled?: unknown;
    /** false: the client has no enable/disableVerticalSwipes. */
    swipeMethods?: boolean;
  } = {},
): FakeTelegram {
  const {
    initData = FAKE_INIT_DATA,
    version = '8.0',
    colorScheme = 'light',
    themeParams = {},
    swipeMethods = true,
  } = options;
  // A default parameter would turn an explicit `undefined` into true.
  const verticalSwipesEnabled = Object.prototype.hasOwnProperty.call(
    options,
    'verticalSwipesEnabled',
  )
    ? options.verticalSwipesEnabled
    : true;
  const backHandlers = new Set<() => void>();
  const eventHandlers = new Set<() => void>();
  const backButton = { visible: false, click: () => backHandlers.forEach((h) => h()) };
  const closing = { enabled: false };
  const swipes: { enabled: unknown } = { enabled: verticalSwipesEnabled };
  const swipeApi = swipeMethods
    ? {
        disableVerticalSwipes: vi.fn(() => {
          swipes.enabled = false;
        }),
        enableVerticalSwipes: vi.fn(() => {
          swipes.enabled = true;
        }),
      }
    : {};
  const state = { colorScheme, themeParams };
  const app = {
    initData,
    version,
    get colorScheme() {
      return state.colorScheme;
    },
    get themeParams() {
      return state.themeParams;
    },
    get isVerticalSwipesEnabled() {
      return swipes.enabled;
    },
    ...swipeApi,
    BackButton: {
      show: vi.fn(() => {
        backButton.visible = true;
      }),
      hide: vi.fn(() => {
        backButton.visible = false;
      }),
      onClick: vi.fn((cb: () => void) => backHandlers.add(cb)),
      offClick: vi.fn((cb: () => void) => backHandlers.delete(cb)),
    },
    ready: vi.fn(),
    expand: vi.fn(),
    enableClosingConfirmation: vi.fn(() => {
      closing.enabled = true;
    }),
    disableClosingConfirmation: vi.fn(() => {
      closing.enabled = false;
    }),
    isVersionAtLeast: (wanted: string) => Number(version) >= Number(wanted),
    onEvent: vi.fn((_event: string, cb: () => void) => eventHandlers.add(cb)),
    offEvent: vi.fn((_event: string, cb: () => void) => eventHandlers.delete(cb)),
  } as unknown as TelegramWebApp;
  window.Telegram = { WebApp: app };
  return {
    app,
    backButton,
    closing,
    swipes,
    emit: () => eventHandlers.forEach((h) => h()),
    setTheme: (scheme, params) => {
      state.colorScheme = scheme;
      state.themeParams = params;
    },
  };
}

export function uninstallTelegram(): void {
  delete window.Telegram;
  document.querySelectorAll('script[data-telegram-sdk]').forEach((node) => node.remove());
}

/** Opens the document on a path (window.location), as a real launch would. */
export function openAt(path: string): void {
  window.history.replaceState(null, '', path);
}
