// MA-3.3 / MA-3.4: Mini App screens, routes, BackButton, theme and language.
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AppProviders } from '../../app/providers/AppProviders';
import { miniAppRoutes } from '../../app/router/miniAppRoutes';
import { makeStore } from '../../app/store/store';
import i18n from '../../shared/i18n';
import { callTo, mockFetchRoutes } from '../../test/fetchRoutes';
import { apiError, jsonResponse } from '../../test/renderWithProviders';
import {
  installTelegram,
  openAt,
  uninstallTelegram,
  type FakeTelegram,
} from '../../test/telegramMock';
import { contrastRatio, DARK_OVERRIDES, MIN_CONTRAST, themeVariables } from './theme';

const WEBAPP = 'POST /api/v1/auth/telegram/webapp';
const PROFILE = 'GET /api/v1/users/me';
const PATCH_PROFILE = 'PATCH /api/v1/users/me';
const token = () => jsonResponse({ access_token: 'mini', token_type: 'bearer', expires_in: 900 });
const profile =
  (language = 'ru') =>
  () =>
    jsonResponse({
      id: 'u1',
      email: null,
      full_name: 'Айбек',
      phone: null,
      preferred_language: language,
      roles: ['customer'],
      must_change_password: false,
      has_password: false,
    });

// Telegram's own default palettes.
const LIGHT = {
  bg_color: '#ffffff',
  text_color: '#000000',
  hint_color: '#999999',
  secondary_bg_color: '#f4f4f5',
  section_bg_color: '#ffffff',
  section_separator_color: '#e7e7e7',
};
const DARK = {
  bg_color: '#212121',
  text_color: '#ffffff',
  hint_color: '#aaaaaa',
  secondary_bg_color: '#181818',
  section_bg_color: '#212121',
  section_separator_color: '#2f2f2f',
};

let fake: FakeTelegram;

function launch(path: string) {
  openAt(path);
  const store = makeStore();
  const router = createMemoryRouter(miniAppRoutes, { initialEntries: [path], basename: '/tg' });
  render(
    <AppProviders store={store}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return { store, router };
}

beforeEach(() => {
  fake = installTelegram({ themeParams: LIGHT });
});

afterEach(() => {
  uninstallTelegram();
  document.documentElement.removeAttribute('style');
  openAt('/');
});

describe('Mini App screens and routes', () => {
  it('signed in: the profile page, no site header, no login links', async () => {
    mockFetchRoutes({ [WEBAPP]: token, [PROFILE]: profile() });
    const { router } = launch('/tg/account');
    expect(await screen.findByRole('heading', { name: 'Профиль' })).toBeInTheDocument();
    // Only the Mini App's own tab bar, no site navigation.
    expect(screen.getAllByRole('navigation').map((n) => n.getAttribute('aria-label'))).toEqual([
      'Разделы Mini App',
    ]);
    expect(screen.queryByRole('link', { name: /войти|регистрац|выйти/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('contentinfo')).not.toBeInTheDocument(); // no site footer
    expect(router.state.location.pathname).toBe('/tg/account');
  });

  it('shows a loading state first, never an empty screen', async () => {
    let release: (r: Response) => void = () => undefined;
    const pending = new Promise<Response>((resolve) => {
      release = resolve;
    });
    mockFetchRoutes({ [WEBAPP]: () => pending, [PROFILE]: profile() });
    launch('/tg/account');
    expect(await screen.findByRole('status')).toHaveTextContent('Подключаемся к Telegram');
    release(token());
    expect(await screen.findByRole('heading', { name: 'Профиль' })).toBeInTheDocument();
  });

  it.each([
    [apiError('TELEGRAM_NOT_LINKED', 409), 'Как вы хотите продолжить?'], // MA-4.1 choice
    [apiError('FORBIDDEN', 403), 'Mini App доступен только клиентам'],
    [apiError('INVALID_TELEGRAM_AUTH', 401), 'Сессия Telegram истекла'],
    [apiError('TELEGRAM_DISABLED', 409), 'Telegram временно недоступен'],
  ])('phase screen %#, staying inside the Mini App', async (response, title) => {
    mockFetchRoutes({ [WEBAPP]: () => response });
    const { router } = launch('/tg');
    expect(await screen.findByRole('heading', { name: title })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Повторить' })).not.toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/tg'); // no redirect to /login
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument(); // no tabs before sign-in
    expect(screen.queryByRole('group', { name: /язык/i })).not.toBeInTheDocument();
  });

  it('an error offers "Повторить", which signs in on the next attempt', async () => {
    const { calls } = mockFetchRoutes({
      [WEBAPP]: [() => apiError('INTERNAL_ERROR', 500), token],
      [PROFILE]: profile(),
    });
    launch('/tg/account');
    fireEvent.click(await screen.findByRole('button', { name: 'Повторить' }));
    expect(await screen.findByRole('heading', { name: 'Профиль' })).toBeInTheDocument();
    expect(calls.filter((c) => c.path.endsWith('/auth/telegram/webapp'))).toHaveLength(2);
    expect(window.Telegram!.WebApp!.ready).toHaveBeenCalledTimes(1);
  });

  it('opened outside Telegram (no initData): restart screen, no request', async () => {
    fake = installTelegram({ initData: '' });
    const { calls } = mockFetchRoutes({});
    launch('/tg');
    expect(
      await screen.findByRole('heading', { name: 'Сессия Telegram истекла' }),
    ).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });

  it('unknown /tg path stays in the Mini App layout', async () => {
    mockFetchRoutes({ [WEBAPP]: token, [PROFILE]: profile() });
    launch('/tg/something');
    expect(await screen.findByRole('heading', { name: 'Раздел недоступен' })).toBeInTheDocument();
  });
});

describe('BackButton', () => {
  it('is hidden on the start pages and shown on other pages', async () => {
    mockFetchRoutes({ [WEBAPP]: token, [PROFILE]: profile() });
    const { router } = launch('/tg/account');
    await screen.findByRole('heading', { name: 'Профиль' });
    expect(fake.backButton.visible).toBe(true);
    await act(() => router.navigate('/menu'));
    expect(fake.backButton.visible).toBe(false);
    expect(fake.app.BackButton.hide).toHaveBeenCalled();
    await act(() => router.navigate('/orders/1'));
    expect(fake.backButton.visible).toBe(true);
    act(() => fake.backButton.click()); // history exists: go back
    await waitFor(() => expect(router.state.location.pathname).toBe('/tg/menu'));
    expect(fake.backButton.visible).toBe(false);
  });

  it('on the first page of a launch goes to the Mini App start, not out of it', async () => {
    mockFetchRoutes({ [WEBAPP]: token, [PROFILE]: profile() });
    const { router } = launch('/tg/account');
    await screen.findByRole('heading', { name: 'Профиль' });
    act(() => fake.backButton.click());
    await waitFor(() => expect(router.state.location.pathname).toBe('/tg/menu'));
    expect(router.state.historyAction).toBe('REPLACE');
  });

  it('removes its handler when the page changes', async () => {
    mockFetchRoutes({ [WEBAPP]: token, [PROFILE]: profile() });
    const { router } = launch('/tg/a');
    await screen.findByRole('heading', { name: 'Раздел недоступен' });
    await act(() => router.navigate('/b'));
    const added = vi.mocked(fake.app.BackButton.onClick).mock.calls.length;
    const removed = vi.mocked(fake.app.BackButton.offClick).mock.calls.length;
    expect(added - removed).toBe(1); // exactly one live handler
  });

  it('old Telegram clients without BackButton are left alone', async () => {
    fake = installTelegram({ version: '6.0' });
    mockFetchRoutes({ [WEBAPP]: token, [PROFILE]: profile() });
    launch('/tg/orders/1/x');
    await screen.findByRole('heading', { name: 'Раздел недоступен' });
    expect(fake.app.BackButton.show).not.toHaveBeenCalled();
  });
});

describe('theme', () => {
  const root = () => document.documentElement.style;

  it('applies Telegram backgrounds and texts, keeps the brand accent', async () => {
    mockFetchRoutes({ [WEBAPP]: token, [PROFILE]: profile() });
    launch('/tg/account');
    await screen.findByRole('heading', { name: 'Профиль' });
    expect(root().getPropertyValue('--color-cream-50')).toBe('#ffffff');
    expect(root().getPropertyValue('--color-ink-900')).toBe('#000000');
    expect(root().getPropertyValue('--color-accent-700')).toBe(''); // brand orange stays
  });

  it('follows themeChanged and switches to dark-friendly shades', async () => {
    mockFetchRoutes({ [WEBAPP]: token, [PROFILE]: profile() });
    launch('/tg/account');
    await screen.findByRole('heading', { name: 'Профиль' });
    act(() => {
      fake.setTheme('dark', DARK);
      fake.emit('themeChanged');
    });
    expect(root().getPropertyValue('--color-cream-50')).toBe('#212121');
    expect(root().getPropertyValue('--color-accent-800')).toBe(
      DARK_OVERRIDES['--color-accent-800'],
    );
    act(() => {
      fake.setTheme('light', LIGHT);
      fake.emit('themeChanged');
    });
    expect(root().getPropertyValue('--color-accent-800')).toBe(''); // back to brand tokens
  });

  it('an unreadable or missing Telegram palette keeps our tokens', () => {
    expect(themeVariables({ bg_color: '#888888', text_color: '#777777' })).toEqual({});
    expect(themeVariables({})).toEqual({});
    expect(themeVariables({ bg_color: 'red', text_color: '#000000' })).toEqual({});
  });

  it.each([
    ['light', LIGHT],
    ['dark', DARK],
  ])('every text/background pair keeps WCAG AA contrast in the %s theme', (_name, params) => {
    const v = { ...brand(), ...themeVariables(params) };
    const pairs: [string, string][] = [
      ['--color-ink-900', '--color-cream-50'],
      ['--color-ink-900', '--color-surface'],
      ['--color-ink-900', '--color-cream-100'],
      ['--color-ink-600', '--color-cream-50'],
      ['--color-ink-600', '--color-surface'],
      ['--color-accent-800', '--color-surface'],
      ['--color-accent-800', '--color-accent-50'],
      ['--color-danger-700', '--color-surface'],
      ['--color-danger-700', '--color-danger-50'],
      ['--color-success-700', '--color-surface'],
      ['--color-success-700', '--color-success-50'],
    ];
    for (const [fg, bg] of pairs) {
      expect(contrastRatio(v[fg], v[bg]), `${fg} on ${bg}`).toBeGreaterThanOrEqual(MIN_CONTRAST);
    }
    // Buttons keep the brand orange with white text.
    expect(contrastRatio('#ffffff', v['--color-accent-700'])).toBeGreaterThanOrEqual(MIN_CONTRAST);
  });
});

// Brand tokens from styles/tokens.css (the values Telegram may override).
function brand(): Record<string, string> {
  return {
    '--color-cream-50': '#fffaf3',
    '--color-cream-100': '#fbf1e3',
    '--color-surface': '#ffffff',
    '--color-ink-900': '#1f2328',
    '--color-ink-600': '#4b525a',
    '--color-accent-50': '#fff4eb',
    '--color-accent-700': '#c2410c',
    '--color-accent-800': '#9a3412',
    '--color-danger-50': '#fef2f2',
    '--color-danger-700': '#b91c1c',
    '--color-success-50': '#ecfdf3',
    '--color-success-700': '#15803d',
  };
}

describe('language', () => {
  it('starts in Russian and then follows preferred_language, without localStorage', async () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    const getItem = vi.spyOn(Storage.prototype, 'getItem');
    mockFetchRoutes({ [WEBAPP]: token, [PROFILE]: profile('ky') });
    launch('/tg/account');
    await waitFor(() => expect(i18n.language).toBe('ky'));
    expect(setItem).not.toHaveBeenCalled();
    expect(getItem).not.toHaveBeenCalledWith('ui-language');
  });

  it('a change is saved with PATCH /users/me before the UI switches', async () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    const { calls } = mockFetchRoutes({
      [WEBAPP]: token,
      [PROFILE]: [profile('ru'), profile('uz')],
      [PATCH_PROFILE]: profile('uz'),
    });
    launch('/tg/account');
    fireEvent.click(await screen.findByRole('button', { name: /o.zbek/i }));
    await waitFor(() => expect(i18n.language).toBe('uz'));
    expect(callTo(calls, '/api/v1/users/me').method).toBe('GET');
    const patch = calls.find((c) => c.method === 'PATCH');
    expect(patch?.body).toEqual({ preferred_language: 'uz' });
    expect(patch?.headers.get('Authorization')).toBe('Bearer mini');
    expect(setItem).not.toHaveBeenCalled();
  });

  it('a failed save keeps the language and says so', async () => {
    mockFetchRoutes({
      [WEBAPP]: token,
      [PROFILE]: profile('ru'),
      [PATCH_PROFILE]: () => apiError('INTERNAL_ERROR', 500),
      // The profile page also lists the addresses; without an answer its
      // own error would be a second alert on the page.
      'GET /api/v1/users/me/addresses': () =>
        jsonResponse({ items: [], pagination: { page: 1, page_size: 100, total: 0, pages: 0 } }),
    });
    launch('/tg/account');
    fireEvent.click(await screen.findByRole('button', { name: /кыргыз/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось сохранить язык');
    expect(i18n.language).toBe('ru');
  });
});
