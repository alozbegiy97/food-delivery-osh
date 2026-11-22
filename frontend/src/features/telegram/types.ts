// Minimal types of the Telegram WebApp SDK actually used by the Mini App
// (DEC-142 K5-A: no npm dependency). `initDataUnsafe` is deliberately not
// declared: it is never trusted and never read (DEC-142 K1-B п. 3).
// https://core.telegram.org/bots/webapps

export interface TelegramThemeParams {
  bg_color?: string;
  secondary_bg_color?: string;
  section_bg_color?: string;
  text_color?: string;
  hint_color?: string;
  subtitle_text_color?: string;
  section_separator_color?: string;
}

export interface TelegramBackButton {
  show(): void;
  hide(): void;
  onClick(callback: () => void): void;
  offClick(callback: () => void): void;
}

export type TelegramEvent = 'themeChanged';

export interface TelegramWebApp {
  /** Raw query string signed by Telegram; verified only by the backend. */
  readonly initData: string;
  readonly version: string;
  readonly colorScheme: 'light' | 'dark';
  readonly themeParams: TelegramThemeParams;
  readonly BackButton: TelegramBackButton;
  ready(): void;
  expand(): void;
  /** Opens an external http(s) link outside the Mini App (Bot API 6.1+). */
  openLink?(url: string): void;
  /** Asks before the Mini App is closed (Bot API 6.2+, DEC-152 п. 11). */
  enableClosingConfirmation?(): void;
  disableClosingConfirmation?(): void;
  /** Whether vertical swipes close or minimize the Mini App (Bot API 7.7+). */
  readonly isVerticalSwipesEnabled?: boolean;
  /** Vertical swipes to close/minimize (Bot API 7.7+, DEC-152 п. 11: pages with a map). */
  disableVerticalSwipes?(): void;
  enableVerticalSwipes?(): void;
  isVersionAtLeast(version: string): boolean;
  onEvent(event: TelegramEvent, callback: () => void): void;
  offEvent(event: TelegramEvent, callback: () => void): void;
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp };
  }
}
