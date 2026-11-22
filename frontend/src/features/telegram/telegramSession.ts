import { apiUrl } from '../../shared/api/http';
import type { TelegramPhase } from './telegramSlice';

// Exchange of Telegram initData for an access token (API §2.3, DEC-142):
// `POST /auth/telegram/webapp {init_data}`. Only the raw `initData` string
// is sent — the backend verifies it; `initDataUnsafe` is never used. No
// cookie and no CSRF header: the Mini App has no refresh cookie.
//
// Concurrent callers (the bootstrap and any number of parallel 401s) share
// one in-flight promise, so initData is exchanged at most once at a time.

export const WEBAPP_LOGIN_PATH = 'auth/telegram/webapp';

export type ExchangeResult =
  | { kind: 'ok'; token: string }
  | { kind: 'not_linked' | 'forbidden' | 'invalid' | 'disabled' | 'error' };

let inFlight: Promise<ExchangeResult> | null = null;

/** The signed initData of the current launch, or '' outside Telegram. */
export function currentInitData(): string {
  const value = window.Telegram?.WebApp?.initData;
  return typeof value === 'string' ? value : '';
}

async function errorCode(response: Response): Promise<string | undefined> {
  try {
    const body = (await response.json()) as { error?: { code?: unknown } };
    return typeof body.error?.code === 'string' ? body.error.code : undefined;
  } catch {
    return undefined;
  }
}

async function requestExchange(initData: string): Promise<ExchangeResult> {
  if (!initData) {
    return { kind: 'invalid' }; // opened outside Telegram or without initData
  }
  let response: Response;
  try {
    response = await fetch(apiUrl(WEBAPP_LOGIN_PATH), {
      method: 'POST',
      credentials: 'omit',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ init_data: initData }),
    });
  } catch {
    return { kind: 'error' };
  }
  if (response.ok) {
    try {
      const body = (await response.json()) as { access_token?: unknown };
      if (typeof body.access_token === 'string' && body.access_token) {
        return { kind: 'ok', token: body.access_token };
      }
    } catch {
      // fall through: malformed success is treated as an error
    }
    return { kind: 'error' };
  }
  const code = await errorCode(response);
  if (response.status === 409 && code === 'TELEGRAM_NOT_LINKED') {
    return { kind: 'not_linked' };
  }
  if (response.status === 409 && code === 'TELEGRAM_DISABLED') {
    return { kind: 'disabled' };
  }
  if (response.status === 403) {
    return { kind: 'forbidden' };
  }
  if (response.status === 401) {
    return { kind: 'invalid' }; // invalid or expired initData, or inactive user
  }
  return { kind: 'error' }; // 429, 5xx, unexpected
}

/** Exchanges the current initData; parallel calls share one request. */
export function exchangeTelegramSession(): Promise<ExchangeResult> {
  if (!inFlight) {
    inFlight = requestExchange(currentInitData()).finally(() => {
      inFlight = null;
    });
  }
  return inFlight;
}

/** Phase shown for a failed exchange (`ok` -> `ready`). */
export function phaseFor(result: ExchangeResult): TelegramPhase {
  switch (result.kind) {
    case 'ok':
      return 'ready';
    case 'not_linked':
      return 'not_linked';
    case 'forbidden':
      return 'forbidden';
    case 'disabled':
      return 'disabled';
    case 'invalid':
      return 'restart';
    default:
      return 'error';
  }
}
