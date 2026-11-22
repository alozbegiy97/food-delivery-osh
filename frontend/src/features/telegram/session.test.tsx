// MA-3.2: the Mini App session vs the site session (DEC-142, DEC-152).
import { render, waitFor } from '@testing-library/react';
import { StrictMode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AppProviders } from '../../app/providers/AppProviders';
import { makeStore } from '../../app/store/store';
import { baseApi } from '../../shared/api/baseApi';
import i18n from '../../shared/i18n';
import { callTo, mockFetchRoutes } from '../../test/fetchRoutes';
import { apiError, jsonResponse } from '../../test/renderWithProviders';
import {
  FAKE_INIT_DATA,
  installTelegram,
  openAt,
  uninstallTelegram,
} from '../../test/telegramMock';
import { authApi } from '../auth/authApi';
import { TELEGRAM_SDK_URL } from './sdk';

const WEBAPP = 'POST /api/v1/auth/telegram/webapp';
const REFRESH = 'POST /api/v1/auth/refresh';
const ME = 'GET /api/v1/auth/me';
const token = (value: string) =>
  jsonResponse({ access_token: value, token_type: 'bearer', expires_in: 900 });
const me = () =>
  jsonResponse({
    id: 'u1',
    email: null,
    full_name: 'Айбек',
    phone: null,
    preferred_language: 'ru',
    roles: ['customer'],
    must_change_password: false,
    has_password: false,
  });

// Endpoints used only by these tests: a protected query and the two Mini
// App operations that must never trigger a re-authentication.
const probeApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    probeRegister: build.mutation<unknown, void>({
      query: () => ({ url: 'auth/telegram/webapp/register', method: 'POST', body: {} }),
    }),
    probeLink: build.mutation<unknown, void>({
      query: () => ({ url: 'auth/telegram/webapp/link', method: 'POST', body: {} }),
    }),
  }),
  overrideExisting: false,
});

const cartProbe = baseApi.injectEndpoints({
  endpoints: (build) => ({ probeCart: build.query<unknown, void>({ query: () => 'cart' }) }),
  overrideExisting: false,
});

function boot(path: string, { strict = false } = {}) {
  openAt(path);
  const store = makeStore();
  const tree = (
    <AppProviders store={store}>
      <p>content</p>
    </AppProviders>
  );
  render(strict ? <StrictMode>{tree}</StrictMode> : tree);
  return store;
}

function miniAppStore(accessToken = 'old') {
  return makeStore({
    auth: { accessToken, status: 'authenticated', passwordChangeRequired: false },
    telegram: { active: true, phase: 'ready', attempt: 0 },
  });
}

beforeEach(() => {
  installTelegram();
});

afterEach(() => {
  uninstallTelegram();
  openAt('/');
});

describe('Mini App bootstrap', () => {
  it('exchanges initData once, keeps the token in memory, never uses the refresh cookie', async () => {
    const { calls } = mockFetchRoutes({ [WEBAPP]: () => token('mini') });
    const store = boot('/tg');
    await waitFor(() => expect(store.getState().telegram.phase).toBe('ready'));
    expect(store.getState().auth).toMatchObject({ accessToken: 'mini', status: 'authenticated' });
    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual([WEBAPP]);
    expect(callTo(calls, '/api/v1/auth/telegram/webapp').body).toEqual({
      init_data: FAKE_INIT_DATA,
    });
    const app = window.Telegram!.WebApp!;
    expect(app.ready).toHaveBeenCalledTimes(1);
    expect(app.expand).toHaveBeenCalledTimes(1);
  });

  it('runs once under StrictMode', async () => {
    const { calls } = mockFetchRoutes({ [WEBAPP]: () => token('mini') });
    const store = boot('/tg/orders/1', { strict: true });
    await waitFor(() => expect(store.getState().telegram.phase).toBe('ready'));
    expect(calls.filter((c) => c.path.endsWith('/auth/telegram/webapp'))).toHaveLength(1);
    expect(calls.some((c) => c.path.endsWith('/auth/refresh'))).toBe(false);
    expect(window.Telegram!.WebApp!.ready).toHaveBeenCalledTimes(1);
  });

  it.each([
    [apiError('TELEGRAM_NOT_LINKED', 409), 'not_linked'],
    [apiError('FORBIDDEN', 403), 'forbidden'],
    [apiError('INVALID_TELEGRAM_AUTH', 401), 'restart'],
    [apiError('TELEGRAM_DISABLED', 409), 'disabled'],
    [apiError('INTERNAL_ERROR', 500), 'error'],
  ])('a refused exchange ends in a phase, not in a session (%#)', async (response, phase) => {
    mockFetchRoutes({ [WEBAPP]: () => response });
    const store = boot('/tg');
    await waitFor(() => expect(store.getState().telegram.phase).toBe(phase));
    expect(store.getState().auth).toMatchObject({ accessToken: null, status: 'anonymous' });
  });

  it('a missing SDK is an error phase, not an empty screen', async () => {
    uninstallTelegram();
    mockFetchRoutes({});
    const store = boot('/tg');
    const script = document.querySelector(`script[src="${TELEGRAM_SDK_URL}"]`);
    expect(script).not.toBeNull();
    script!.dispatchEvent(new Event('error'));
    await waitFor(() => expect(store.getState().telegram.phase).toBe('error'));
  });
});

describe('site bootstrap is unchanged', () => {
  it('restores the session from the refresh cookie and never loads the SDK', async () => {
    const { calls } = mockFetchRoutes({ [REFRESH]: () => token('site') });
    const store = boot('/menu');
    await waitFor(() => expect(store.getState().auth.accessToken).toBe('site'));
    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual([REFRESH]);
    expect(store.getState().telegram).toEqual({ active: false, phase: 'idle', attempt: 0 });
    expect(document.querySelector(`script[src="${TELEGRAM_SDK_URL}"]`)).toBeNull();
    expect(window.Telegram!.WebApp!.ready).not.toHaveBeenCalled();
  });

  it('re-authenticates through the refresh cookie on 401', async () => {
    const { calls } = mockFetchRoutes({
      [ME]: [() => apiError('UNAUTHORIZED', 401), me],
      [REFRESH]: () => token('fresh'),
    });
    const store = makeStore({
      auth: { accessToken: 'stale', status: 'authenticated', passwordChangeRequired: false },
    });
    const result = await store.dispatch(authApi.endpoints.me.initiate());
    expect(result.data?.full_name).toBe('Айбек');
    expect(calls.map((c) => c.path)).toEqual([
      '/api/v1/auth/me',
      '/api/v1/auth/refresh',
      '/api/v1/auth/me',
    ]);
    expect(calls.some((c) => c.path.includes('telegram'))).toBe(false);
  });
});

describe('Mini App re-authentication', () => {
  it('answers a 401 with a new initData exchange, not with refresh or navigator.locks', async () => {
    const request = vi.fn();
    Object.defineProperty(navigator, 'locks', { value: { request }, configurable: true });
    const { calls } = mockFetchRoutes({
      [ME]: [() => apiError('UNAUTHORIZED', 401), me],
      [WEBAPP]: () => token('renewed'),
    });
    const store = miniAppStore('expired');
    const result = await store.dispatch(authApi.endpoints.me.initiate());
    expect(result.data?.full_name).toBe('Айбек');
    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual([ME, WEBAPP, ME]);
    expect(calls[2].headers.get('Authorization')).toBe('Bearer renewed');
    expect(store.getState().auth.accessToken).toBe('renewed');
    expect(request).not.toHaveBeenCalled();
    Reflect.deleteProperty(navigator, 'locks');
  });

  it('parallel 401s share one exchange and both requests are retried with the new token', async () => {
    let release: (value: Response) => void = () => undefined;
    const pending = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const { calls } = mockFetchRoutes({
      'GET /api/v1/cart': [() => apiError('UNAUTHORIZED', 401), () => jsonResponse({ items: [] })],
      [ME]: [() => apiError('UNAUTHORIZED', 401), me],
      [WEBAPP]: () => pending,
    });
    const store = miniAppStore();
    const first = store.dispatch(authApi.endpoints.me.initiate());
    const second = store.dispatch(cartProbe.endpoints.probeCart.initiate());
    const exchanges = () => calls.filter((c) => c.path.endsWith('/auth/telegram/webapp'));
    await waitFor(() => expect(exchanges()).toHaveLength(1));
    release(token('shared'));
    const [meResult, cartResult] = await Promise.all([first, second]);
    expect(meResult.data?.full_name).toBe('Айбек');
    expect(cartResult.data).toEqual({ items: [] });
    expect(exchanges()).toHaveLength(1);
    const retried = calls.slice(calls.indexOf(exchanges()[0]) + 1);
    expect(retried.map((c) => c.path).sort()).toEqual(['/api/v1/auth/me', '/api/v1/cart']);
    for (const call of retried) {
      expect(call.headers.get('Authorization')).toBe('Bearer shared');
    }
  });

  it('a failed exchange ends the session and shows the restart screen', async () => {
    const { calls } = mockFetchRoutes({
      [ME]: () => apiError('UNAUTHORIZED', 401),
      [WEBAPP]: () => apiError('INVALID_TELEGRAM_AUTH', 401),
    });
    const store = miniAppStore();
    await store.dispatch(authApi.endpoints.me.initiate());
    expect(store.getState().auth).toMatchObject({ accessToken: null, status: 'anonymous' });
    expect(store.getState().telegram.phase).toBe('restart');
    expect(calls.map((c) => c.path)).toEqual(['/api/v1/auth/me', '/api/v1/auth/telegram/webapp']);
  });

  it.each(['probeRegister', 'probeLink'] as const)(
    '401 of %s is an answer, not an expired session',
    async (endpoint) => {
      const { calls } = mockFetchRoutes({
        'POST /api/v1/auth/telegram/webapp/register': () => apiError('INVALID_TELEGRAM_AUTH', 401),
        'POST /api/v1/auth/telegram/webapp/link': () => apiError('INVALID_CREDENTIALS', 401),
      });
      const store = miniAppStore();
      await store.dispatch(probeApi.endpoints[endpoint].initiate());
      expect(calls).toHaveLength(1); // no exchange, no refresh, no retry
      expect(store.getState().auth.accessToken).toBe('old');
      expect(store.getState().telegram.phase).toBe('ready');
    },
  );
});

describe('language storage', () => {
  it('the Mini App never writes the site language to localStorage', async () => {
    openAt('/tg');
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    await i18n.changeLanguage('ky');
    expect(i18n.language).toBe('ky');
    expect(setItem).not.toHaveBeenCalled();
  });

  it('the site still remembers the language', async () => {
    openAt('/menu');
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    await i18n.changeLanguage('uz');
    expect(setItem).toHaveBeenCalledWith('ui-language', 'uz');
  });
});
