import type { TelegramWebApp } from './types';

// Official script (DEC-142 K5-A), loaded only on `/tg` and `/tg/*`
// (DEC-152 п. 1): it is injected by the Mini App bootstrap, never by
// index.html, so site pages never load it.
export const TELEGRAM_SDK_URL = 'https://telegram.org/js/telegram-web-app.js';
export const SDK_TIMEOUT_MS = 10_000;

export class TelegramSdkError extends Error {
  constructor() {
    super('Telegram SDK is not available');
    this.name = 'TelegramSdkError';
  }
}

let loading: Promise<TelegramWebApp> | null = null;

function injectScript(timeoutMs: number): Promise<TelegramWebApp> {
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = TELEGRAM_SDK_URL;
    script.async = true;
    script.dataset.telegramSdk = 'true';
    const fail = () => {
      window.clearTimeout(timer);
      script.remove();
      reject(new TelegramSdkError());
    };
    const timer = window.setTimeout(fail, timeoutMs);
    script.onload = () => {
      window.clearTimeout(timer);
      const app = window.Telegram?.WebApp;
      if (app) {
        resolve(app);
      } else {
        fail();
      }
    };
    script.onerror = fail;
    document.head.appendChild(script);
  });
}

/**
 * The SDK object; the script is injected at most once at a time. A failed
 * attempt is forgotten, so "Повторить" can load it again.
 */
export function loadTelegramSdk(timeoutMs: number = SDK_TIMEOUT_MS): Promise<TelegramWebApp> {
  const existing = window.Telegram?.WebApp;
  if (existing) {
    return Promise.resolve(existing);
  }
  if (!loading) {
    loading = injectScript(timeoutMs).finally(() => {
      loading = null;
    });
  }
  return loading;
}
