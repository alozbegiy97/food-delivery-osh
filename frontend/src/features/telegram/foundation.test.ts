// MA-3.1: mode detection, SDK loading and the initData exchange.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { isMiniAppPath } from '../../shared/lib/miniAppMode';
import { jsonResponse, apiError } from '../../test/renderWithProviders';
import { mockFetchRoutes } from '../../test/fetchRoutes';
import { FAKE_INIT_DATA, installTelegram, uninstallTelegram } from '../../test/telegramMock';
import { loadTelegramSdk, TELEGRAM_SDK_URL, TelegramSdkError } from './sdk';
import { exchangeTelegramSession, phaseFor } from './telegramSession';

const WEBAPP = 'POST /api/v1/auth/telegram/webapp';

afterEach(() => {
  uninstallTelegram();
  vi.useRealTimers();
});

describe('Mini App mode is decided only by the path', () => {
  it.each(['/tg', '/tg/', '/tg/menu', '/tg/orders/1/pay'])('%s is the Mini App', (path) => {
    expect(isMiniAppPath(path)).toBe(true);
  });

  it.each(['/', '/menu', '/tgx', '/tg-promo', '/admin', '/login', '/menu/tg'])(
    '%s is the site',
    (path) => {
      expect(isMiniAppPath(path)).toBe(false);
    },
  );
});

describe('loadTelegramSdk', () => {
  const scripts = () => document.querySelectorAll(`script[src="${TELEGRAM_SDK_URL}"]`);

  it('injects the official script once and resolves with WebApp', async () => {
    const first = loadTelegramSdk();
    const second = loadTelegramSdk();
    expect(scripts()).toHaveLength(1); // one script for parallel callers
    const fake = installTelegram();
    scripts()[0].dispatchEvent(new Event('load'));
    await expect(first).resolves.toBe(fake.app);
    await expect(second).resolves.toBe(fake.app);
  });

  it('uses an already present WebApp without a new script', async () => {
    const fake = installTelegram();
    await expect(loadTelegramSdk()).resolves.toBe(fake.app);
    expect(scripts()).toHaveLength(0);
  });

  it('fails on a load error and can be retried', async () => {
    const attempt = loadTelegramSdk();
    scripts()[0].dispatchEvent(new Event('error'));
    await expect(attempt).rejects.toBeInstanceOf(TelegramSdkError);
    expect(scripts()).toHaveLength(0); // removed, so a retry starts clean

    const retry = loadTelegramSdk();
    expect(scripts()).toHaveLength(1);
    const fake = installTelegram();
    scripts()[0].dispatchEvent(new Event('load'));
    await expect(retry).resolves.toBe(fake.app);
  });

  it('fails when the script loads without WebApp', async () => {
    const attempt = loadTelegramSdk();
    scripts()[0].dispatchEvent(new Event('load'));
    await expect(attempt).rejects.toBeInstanceOf(TelegramSdkError);
  });

  it('fails after the timeout', async () => {
    vi.useFakeTimers();
    const attempt = loadTelegramSdk(1000);
    const assertion = expect(attempt).rejects.toBeInstanceOf(TelegramSdkError);
    await vi.advanceTimersByTimeAsync(1001);
    await assertion;
    expect(scripts()).toHaveLength(0);
  });
});

describe('exchangeTelegramSession', () => {
  beforeEach(() => {
    installTelegram();
  });

  it('sends only the raw initData string, without cookies or CSRF header', async () => {
    const { calls } = mockFetchRoutes({
      [WEBAPP]: () => jsonResponse({ access_token: 'tok', token_type: 'bearer', expires_in: 900 }),
    });
    await expect(exchangeTelegramSession()).resolves.toEqual({ kind: 'ok', token: 'tok' });
    expect(calls).toHaveLength(1);
    expect(calls[0].body).toEqual({ init_data: FAKE_INIT_DATA });
    expect(calls[0].credentials).toBe('omit');
    expect(calls[0].headers.get('X-CSRF-Protection')).toBeNull();
    expect(calls[0].headers.get('Authorization')).toBeNull();
  });

  it('never reads initDataUnsafe: empty initData means no request', async () => {
    const fake = installTelegram({ initData: '' });
    Object.assign(fake.app, { initDataUnsafe: { user: { id: 1, first_name: 'Spoof' } } });
    const { calls } = mockFetchRoutes({});
    await expect(exchangeTelegramSession()).resolves.toEqual({ kind: 'invalid' });
    expect(calls).toHaveLength(0);
  });

  it('outside Telegram there is nothing to exchange', async () => {
    uninstallTelegram();
    const { calls } = mockFetchRoutes({});
    await expect(exchangeTelegramSession()).resolves.toEqual({ kind: 'invalid' });
    expect(calls).toHaveLength(0);
  });

  it('parallel callers share one request', async () => {
    let release: (value: Response) => void = () => undefined;
    const pending = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const { calls } = mockFetchRoutes({ [WEBAPP]: () => pending });
    const results = [
      exchangeTelegramSession(),
      exchangeTelegramSession(),
      exchangeTelegramSession(),
    ];
    release(jsonResponse({ access_token: 'shared', token_type: 'bearer', expires_in: 900 }));
    for (const result of await Promise.all(results)) {
      expect(result).toEqual({ kind: 'ok', token: 'shared' });
    }
    expect(calls).toHaveLength(1);
    // A later call is a new exchange.
    mockFetchRoutes({
      [WEBAPP]: () => jsonResponse({ access_token: 'next', token_type: 'bearer', expires_in: 900 }),
    });
    await expect(exchangeTelegramSession()).resolves.toEqual({ kind: 'ok', token: 'next' });
  });

  it.each([
    [apiError('TELEGRAM_NOT_LINKED', 409), 'not_linked', 'not_linked'],
    [apiError('TELEGRAM_DISABLED', 409), 'disabled', 'disabled'],
    [apiError('FORBIDDEN', 403), 'forbidden', 'forbidden'],
    [apiError('INVALID_TELEGRAM_AUTH', 401), 'invalid', 'restart'],
    [apiError('RATE_LIMITED', 429), 'error', 'error'],
    [apiError('TELEGRAM_BUSY', 409), 'error', 'error'],
    [apiError('INTERNAL_ERROR', 500), 'error', 'error'],
    [new Response('not json', { status: 502 }), 'error', 'error'],
    [jsonResponse({ unexpected: true }), 'error', 'error'],
  ])('maps the response to %#', async (response, kind, phase) => {
    mockFetchRoutes({ [WEBAPP]: () => response });
    const result = await exchangeTelegramSession();
    expect(result.kind).toBe(kind);
    expect(phaseFor(result)).toBe(phase);
  });

  it('a network failure is a retryable error', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('offline'));
    await expect(exchangeTelegramSession()).resolves.toEqual({ kind: 'error' });
  });
});
