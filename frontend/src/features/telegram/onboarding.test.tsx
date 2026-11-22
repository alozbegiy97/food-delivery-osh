// MA-4.1: first launch without a link — choice, registration, linking of a
// site account and every error the backend can answer (API §1.1, §2.3).
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AppProviders } from '../../app/providers/AppProviders';
import { miniAppRoutes } from '../../app/router/miniAppRoutes';
import { makeStore } from '../../app/store/store';
import i18n, { resources } from '../../shared/i18n';
import { SUPPORTED_LANGUAGES } from '../../shared/i18n/languages';
import { CATEGORIES, MARGHERITA_SUMMARY, productList } from '../../test/catalogFixtures';
import { callTo, mockFetchRoutes, type RecordedRequest } from '../../test/fetchRoutes';
import { BASE } from '../../test/orderFixtures';
import { apiError, jsonResponse } from '../../test/renderWithProviders';
import {
  FAKE_INIT_DATA,
  installTelegram,
  openAt,
  uninstallTelegram,
  type FakeTelegram,
} from '../../test/telegramMock';

const WEBAPP = 'POST /api/v1/auth/telegram/webapp';
const REGISTER = 'POST /api/v1/auth/telegram/webapp/register';
const LINK = 'POST /api/v1/auth/telegram/webapp/link';
const PASSWORD = 'Secret-pass1';

const token =
  (value = 'issued') =>
  () =>
    jsonResponse({ access_token: value, token_type: 'bearer', expires_in: 900 });
const notLinked = () => apiError('TELEGRAM_NOT_LINKED', 409);

// The pages the start page needs once signed in.
const PAGES = {
  ...BASE,
  'GET /api/v1/users/me': () =>
    jsonResponse({
      id: 'u-1',
      email: null,
      full_name: 'Айбек',
      phone: null,
      preferred_language: 'ru',
      roles: ['customer'],
      must_change_password: false,
      has_password: false,
    }),
  'GET /api/v1/catalog/categories': () => jsonResponse({ items: CATEGORIES }),
  'GET /api/v1/catalog/products': () => jsonResponse(productList([MARGHERITA_SUMMARY])),
};

const CHOICE = 'Как вы хотите продолжить?';
const LINK_TITLE = 'Вход в аккаунт сайта';

let fake: FakeTelegram;

function launch(path = '/tg') {
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

const requestsTo = (calls: RecordedRequest[], path: string) =>
  calls.filter((c) => c.method === 'POST' && c.path === path);

async function openLinkForm() {
  fireEvent.click(await screen.findByRole('button', { name: 'У меня уже есть аккаунт' }));
  expect(await screen.findByRole('heading', { name: LINK_TITLE })).toBeInTheDocument();
}

function fillAndSubmit(email = '  client@example.com ', password = PASSWORD) {
  fireEvent.input(screen.getByLabelText('Email'), { target: { value: email } });
  fireEvent.input(screen.getByLabelText('Пароль'), { target: { value: password } });
  fireEvent.click(screen.getByRole('button', { name: 'Войти и связать' }));
}

async function expectSignedInOnMenu(router: ReturnType<typeof launch>['router']) {
  await waitFor(() => expect(router.state.location.pathname).toBe('/tg/menu'));
  await waitFor(() =>
    expect(screen.getByRole('heading', { level: 1, name: 'Меню' })).toBeInTheDocument(),
  );
  expect(screen.getByRole('navigation', { name: 'Разделы Mini App' })).toBeInTheDocument();
}

beforeEach(() => {
  fake = installTelegram();
});

afterEach(() => {
  uninstallTelegram();
  openAt('/');
});

describe('choice screen', () => {
  it('without a link: two choices and the warning; nothing is created by itself', async () => {
    const { calls } = mockFetchRoutes({ [WEBAPP]: notLinked });
    const { router } = launch('/tg');
    expect(await screen.findByRole('heading', { name: CHOICE })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Я новый клиент' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'У меня уже есть аккаунт' })).toBeEnabled();
    expect(
      screen.getByText(
        'После создания нового аккаунта связать этот Telegram с аккаунтом сайта будет нельзя.',
      ),
    ).toBeInTheDocument();
    expect(requestsTo(calls, '/api/v1/auth/telegram/webapp/register')).toHaveLength(0);
    expect(requestsTo(calls, '/api/v1/auth/telegram/webapp/link')).toHaveLength(0);
    // Not signed in: no tabs, no site links, still inside the Mini App.
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
    expect(document.querySelectorAll('a[href]')).toHaveLength(0);
    expect(router.state.location.pathname).toBe('/tg');
  });
});

describe('new customer', () => {
  it('registers with the raw initData only, then opens /tg/menu signed in', async () => {
    const { calls } = mockFetchRoutes({ ...PAGES, [WEBAPP]: notLinked, [REGISTER]: token('new') });
    const { router } = launch('/tg');
    fireEvent.click(await screen.findByRole('button', { name: 'Я новый клиент' }));
    await expectSignedInOnMenu(router);

    const request = callTo(calls, '/api/v1/auth/telegram/webapp/register');
    expect(request.body).toEqual({ init_data: FAKE_INIT_DATA });
    expect(request.credentials).toBe('omit');
    expect(request.headers.get('Authorization')).toBeNull();
    expect(request.headers.get('X-CSRF-Protection')).toBeNull();
    // The new token is used afterwards.
    expect(callTo(calls, '/api/v1/users/me').headers.get('Authorization')).toBe('Bearer new');
    expect(requestsTo(calls, '/api/v1/auth/telegram/webapp')).toHaveLength(1);
  });

  it('opened on a deep path, it still lands on /tg/menu', async () => {
    const { calls } = mockFetchRoutes({ ...PAGES, [WEBAPP]: notLinked, [REGISTER]: token() });
    const { router } = launch('/tg/cart');
    fireEvent.click(await screen.findByRole('button', { name: 'Я новый клиент' }));
    await expectSignedInOnMenu(router);
    expect(calls.some((c) => c.path === '/api/v1/cart' && c.method === 'GET')).toBe(true); // tab badge
    expect(screen.queryByRole('heading', { name: 'Корзина' })).not.toBeInTheDocument();
  });

  it('a double tap sends one request; the buttons wait for the answer', async () => {
    let release: (r: Response) => void = () => undefined;
    const pending = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const { calls } = mockFetchRoutes({ ...PAGES, [WEBAPP]: notLinked, [REGISTER]: () => pending });
    const { router } = launch('/tg');
    const button = await screen.findByRole('button', { name: 'Я новый клиент' });
    fireEvent.click(button);
    fireEvent.click(button);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Отправляем…' })).toBeDisabled());
    expect(screen.getByRole('button', { name: 'У меня уже есть аккаунт' })).toBeDisabled();
    release(token()());
    await expectSignedInOnMenu(router);
    expect(requestsTo(calls, '/api/v1/auth/telegram/webapp/register')).toHaveLength(1);
  });

  it.each([
    ['TELEGRAM_BUSY', 409],
    ['RATE_LIMITED', 429],
    ['INTERNAL_ERROR', 500],
  ])('%s: a message on the choice screen, and a retry works', async (code, status) => {
    const { calls } = mockFetchRoutes({
      ...PAGES,
      [WEBAPP]: notLinked,
      [REGISTER]: [() => apiError(code, status), token()],
    });
    const { router } = launch('/tg');
    fireEvent.click(await screen.findByRole('button', { name: 'Я новый клиент' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(i18n.t(`errors.codes.${code}`));
    expect(screen.getByRole('heading', { name: CHOICE })).toBeInTheDocument();
    expect(requestsTo(calls, '/api/v1/auth/telegram/webapp')).toHaveLength(1); // no re-exchange

    fireEvent.click(screen.getByRole('button', { name: 'Я новый клиент' }));
    await expectSignedInOnMenu(router);
    expect(requestsTo(calls, '/api/v1/auth/telegram/webapp/register')).toHaveLength(2);
  });

  it('network failure: a message, the choice stays', async () => {
    mockFetchRoutes({
      [WEBAPP]: notLinked,
      [REGISTER]: () => Promise.reject(new TypeError('Failed to fetch')),
    });
    launch('/tg');
    fireEvent.click(await screen.findByRole('button', { name: 'Я новый клиент' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      i18n.t('errors.codes.NETWORK_ERROR'),
    );
    expect(screen.getByRole('heading', { name: CHOICE })).toBeInTheDocument();
  });

  it.each([
    [apiError('INVALID_TELEGRAM_AUTH', 401), 'Сессия Telegram истекла'],
    [apiError('FORBIDDEN', 403), 'Mini App доступен только клиентам'],
    [apiError('TELEGRAM_DISABLED', 409), 'Telegram временно недоступен'],
  ])('launch-level error %#: its service screen', async (response, title) => {
    const { calls } = mockFetchRoutes({ [WEBAPP]: notLinked, [REGISTER]: () => response });
    const { router } = launch('/tg');
    fireEvent.click(await screen.findByRole('button', { name: 'Я новый клиент' }));
    expect(await screen.findByRole('heading', { name: title })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Я новый клиент' })).not.toBeInTheDocument();
    expect(requestsTo(calls, '/api/v1/auth/telegram/webapp')).toHaveLength(1);
    expect(router.state.location.pathname).toBe('/tg');
  });
});

describe('existing site account', () => {
  it('validates the form before sending anything', async () => {
    const { calls } = mockFetchRoutes({ [WEBAPP]: notLinked });
    launch('/tg');
    await openLinkForm();
    fireEvent.click(screen.getByRole('button', { name: 'Войти и связать' }));
    await waitFor(() => expect(screen.getAllByText(i18n.t('validation.required'))).toHaveLength(2));
    expect(requestsTo(calls, '/api/v1/auth/telegram/webapp/link')).toHaveLength(0);
  });

  it('links with initData, email and password, then opens /tg/menu signed in', async () => {
    const { calls } = mockFetchRoutes({ ...PAGES, [WEBAPP]: notLinked, [LINK]: token('linked') });
    const { router } = launch('/tg/orders');
    await openLinkForm();
    fillAndSubmit();
    await expectSignedInOnMenu(router);

    const request = callTo(calls, '/api/v1/auth/telegram/webapp/link');
    expect(request.body).toEqual({
      init_data: FAKE_INIT_DATA,
      email: 'client@example.com',
      password: PASSWORD,
    });
    expect(request.credentials).toBe('omit');
    expect(request.headers.get('Authorization')).toBeNull();
    expect(callTo(calls, '/api/v1/users/me').headers.get('Authorization')).toBe('Bearer linked');
  });

  it('wrong credentials: one general message, the form stays, the password is cleared', async () => {
    const { calls } = mockFetchRoutes({
      [WEBAPP]: notLinked,
      [LINK]: () => apiError('INVALID_CREDENTIALS', 401),
    });
    const { router, store } = launch('/tg');
    await openLinkForm();
    fillAndSubmit();
    expect(await screen.findByRole('alert')).toHaveTextContent('Неверный email или пароль');
    expect(screen.getByRole('heading', { name: LINK_TITLE })).toBeInTheDocument();
    // type=email inputs drop surrounding spaces from their value.
    expect(screen.getByLabelText('Email')).toHaveValue('client@example.com');
    await waitFor(() => expect(screen.getByLabelText('Пароль')).toHaveValue(''));
    // A 401 of the form is not an expired session: no new exchange, no screen change.
    expect(requestsTo(calls, '/api/v1/auth/telegram/webapp')).toHaveLength(1);
    expect(store.getState().telegram.phase).toBe('not_linked');
    expect(router.state.location.pathname).toBe('/tg');
  });

  it.each([
    ['FORBIDDEN', 403, 'Mini App доступен только клиентам. Войдите в клиентский аккаунт'],
    ['TELEGRAM_ALREADY_LINKED', 409, 'Этот Telegram уже связан с другим аккаунтом'],
    ['ACCOUNT_ALREADY_LINKED', 409, 'Этот аккаунт уже связан с другим Telegram'],
    ['TELEGRAM_BUSY', 409, null],
    ['RATE_LIMITED', 429, null],
    ['VALIDATION_ERROR', 422, null],
    ['INTERNAL_ERROR', 500, null],
    ['SOMETHING_NEW', 409, null],
  ])('%s: a message on the form, nothing else changes', async (code, status, text) => {
    const { calls } = mockFetchRoutes({
      [WEBAPP]: notLinked,
      [LINK]: () => apiError(code, status),
    });
    const { store } = launch('/tg');
    await openLinkForm();
    fillAndSubmit();
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(
      text ?? i18n.t(`errors.codes.${code}`, { defaultValue: i18n.t('errors.codes.default') }),
    );
    expect(screen.getByRole('heading', { name: LINK_TITLE })).toBeInTheDocument();
    expect(screen.getByLabelText('Пароль')).toHaveValue(PASSWORD); // only wrong credentials clear it
    expect(store.getState().telegram.phase).toBe('not_linked');
    expect(requestsTo(calls, '/api/v1/auth/telegram/webapp')).toHaveLength(1);
  });

  it('TELEGRAM_BUSY: sending again succeeds', async () => {
    mockFetchRoutes({
      ...PAGES,
      [WEBAPP]: notLinked,
      [LINK]: [() => apiError('TELEGRAM_BUSY', 409), token()],
    });
    const { router } = launch('/tg');
    await openLinkForm();
    fillAndSubmit();
    expect(await screen.findByRole('alert')).toHaveTextContent(
      i18n.t('errors.codes.TELEGRAM_BUSY'),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Войти и связать' }));
    await expectSignedInOnMenu(router);
  });

  it('network failure: a message on the form', async () => {
    mockFetchRoutes({
      [WEBAPP]: notLinked,
      [LINK]: () => Promise.reject(new TypeError('Failed to fetch')),
    });
    launch('/tg');
    await openLinkForm();
    fillAndSubmit();
    expect(await screen.findByRole('alert')).toHaveTextContent(
      i18n.t('errors.codes.NETWORK_ERROR'),
    );
  });

  it.each([
    [apiError('INVALID_TELEGRAM_AUTH', 401), 'Сессия Telegram истекла'],
    [apiError('TELEGRAM_DISABLED', 409), 'Telegram временно недоступен'],
  ])('launch-level error %#: its service screen', async (response, title) => {
    mockFetchRoutes({ [WEBAPP]: notLinked, [LINK]: () => response });
    launch('/tg');
    await openLinkForm();
    fillAndSubmit();
    expect(await screen.findByRole('heading', { name: title })).toBeInTheDocument();
    expect(screen.queryByLabelText('Пароль')).not.toBeInTheDocument();
  });

  it('a double submit sends one request', async () => {
    let release: (r: Response) => void = () => undefined;
    const pending = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const { calls } = mockFetchRoutes({ ...PAGES, [WEBAPP]: notLinked, [LINK]: () => pending });
    const { router } = launch('/tg');
    await openLinkForm();
    fillAndSubmit();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Отправляем…' })).toBeDisabled());
    fireEvent.submit(screen.getByRole('button', { name: 'Отправляем…' }).closest('form')!);
    release(token()());
    await expectSignedInOnMenu(router);
    expect(requestsTo(calls, '/api/v1/auth/telegram/webapp/link')).toHaveLength(1);
  });

  it('"Назад" returns to the choice', async () => {
    mockFetchRoutes({ [WEBAPP]: notLinked });
    launch('/tg');
    await openLinkForm();
    fireEvent.click(screen.getByRole('button', { name: 'Назад' }));
    expect(await screen.findByRole('heading', { name: CHOICE })).toBeInTheDocument();
  });

  it('"Забыли пароль?" opens the site reset page outside the Mini App', async () => {
    const openLink = (fake.app.openLink = vi.fn());
    const { calls } = mockFetchRoutes({ [WEBAPP]: notLinked });
    const { router } = launch('/tg');
    await openLinkForm();
    fireEvent.click(screen.getByRole('button', { name: 'Забыли пароль?' }));
    expect(openLink).toHaveBeenCalledWith(`${window.location.origin}/forgot-password`);
    expect(router.state.location.pathname).toBe('/tg');
    expect(screen.getByRole('heading', { name: LINK_TITLE })).toBeInTheDocument();
    expect(calls).toHaveLength(1); // only the initial exchange
  });

  it('"Забыли пароль?" without openLink support: a new tab, never this frame', async () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);
    mockFetchRoutes({ [WEBAPP]: notLinked });
    launch('/tg');
    await openLinkForm();
    fireEvent.click(screen.getByRole('button', { name: 'Забыли пароль?' }));
    expect(open).toHaveBeenCalledWith(
      `${window.location.origin}/forgot-password`,
      '_blank',
      'noopener,noreferrer',
    );
  });
});

describe('secrets', () => {
  it('neither the password nor initData stays in the store or reaches the console', async () => {
    const log = vi.spyOn(console, 'log');
    const warn = vi.spyOn(console, 'warn');
    const error = vi.spyOn(console, 'error');
    mockFetchRoutes({
      [WEBAPP]: notLinked,
      [LINK]: () => apiError('INVALID_CREDENTIALS', 401),
      [REGISTER]: () => apiError('TELEGRAM_BUSY', 409),
    });
    const { store } = launch('/tg');
    fireEvent.click(await screen.findByRole('button', { name: 'Я новый клиент' }));
    await screen.findByRole('alert');
    await openLinkForm();
    fillAndSubmit();
    expect(await screen.findByRole('alert')).toHaveTextContent('Неверный email или пароль');

    const state = JSON.stringify(store.getState());
    expect(state).not.toContain(PASSWORD);
    expect(state).not.toContain(FAKE_INIT_DATA);
    for (const spy of [log, warn, error]) {
      const printed = JSON.stringify(spy.mock.calls);
      expect(printed).not.toContain(PASSWORD);
      expect(printed).not.toContain(FAKE_INIT_DATA);
    }
  });
});

describe('translations', () => {
  it.each(SUPPORTED_LANGUAGES)('%s has every onboarding text', (language) => {
    const telegram = (resources[language].common as { telegram: Record<string, unknown> }).telegram;
    expect(Object.keys(telegram.onboarding as object).sort()).toEqual(
      [
        'back',
        'haveAccount',
        'linkForbidden',
        'linkSubmit',
        'linkText',
        'linkTitle',
        'newCustomer',
        'text',
        'title',
        'warning',
      ].sort(),
    );
    expect(telegram).not.toHaveProperty('not_linked');
  });
});
