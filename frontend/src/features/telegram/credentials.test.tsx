// MA-4.4.5: "Вход на сайте" — email and password for a Telegram-only account
// of the Mini App (DEC-160 п. 5, DEC-142, DEC-141). Only the mocked API is
// used. The password must not outlive the request: it is cleared from the
// input and the finished mutation leaves no arguments in the Redux store.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { AppProviders } from '../../app/providers/AppProviders';
import { miniAppRoutes } from '../../app/router/miniAppRoutes';
import { makeStore } from '../../app/store/store';
import { mockFetchRoutes, type RecordedRequest } from '../../test/fetchRoutes';
import { BASE } from '../../test/orderFixtures';
import { apiError, emptyResponse, jsonResponse } from '../../test/renderWithProviders';
import { installTelegram, openAt, uninstallTelegram } from '../../test/telegramMock';
import { profileApi } from '../profile/profileApi';

type Routes = Parameters<typeof mockFetchRoutes>[0];
type Handler = (request: RecordedRequest) => Response | Promise<Response>;

const PROFILE = 'GET /api/v1/users/me';
const CREDENTIALS = 'POST /api/v1/auth/credentials';

const PASSWORD = 'Parol2026x';
const NEW_EMAIL = 'new@example.com';
const HINT = 'От 8 до 128 символов, минимум одна буква и одна цифра.';
const SUBMIT = 'Добавить email и пароль';

const TELEGRAM_ONLY = { email: null, has_password: false };
const WITH_CREDENTIALS = { email: NEW_EMAIL, has_password: true };

function me(extra: Record<string, unknown> = {}) {
  return jsonResponse({
    id: 'u-1',
    email: 'buyer@example.com',
    full_name: 'Айбек Токтогулов',
    phone: '+996700123456',
    preferred_language: 'ru',
    roles: ['customer'],
    must_change_password: false,
    has_password: true,
    ...extra,
  });
}

function signedIn(routes: Routes = {}): Routes {
  return {
    ...BASE,
    'POST /api/v1/auth/telegram/webapp': () =>
      jsonResponse({ access_token: 'mini', token_type: 'bearer', expires_in: 900 }),
    [PROFILE]: () => me(TELEGRAM_ONLY),
    'GET /api/v1/users/me/addresses': () =>
      jsonResponse({ items: [], pagination: { page: 1, page_size: 100, total: 0, pages: 0 } }),
    ...routes,
  };
}

/**
 * A Telegram-only profile until POST /auth/credentials succeeds (204); then
 * GET /users/me answers with the email and `has_password: true`.
 */
function addable(): Routes & { [CREDENTIALS]: Handler } {
  let added = false;
  return {
    [PROFILE]: () => me(added ? WITH_CREDENTIALS : TELEGRAM_ONLY),
    [CREDENTIALS]: () => {
      added = true;
      return emptyResponse(204);
    },
  };
}

function launch(store = makeStore()) {
  openAt('/tg/account');
  const router = createMemoryRouter(miniAppRoutes, {
    initialEntries: ['/tg/account'],
    basename: '/tg',
  });
  render(
    <AppProviders store={store}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return store;
}

function section() {
  return screen.getByRole('region', { name: 'Вход на сайте' });
}

function emailInput() {
  return screen.getByLabelText('Email');
}

function passwordInput() {
  return screen.getByLabelText('Пароль');
}

function fill(email: string, password: string) {
  fireEvent.change(emailInput(), { target: { value: email } });
  fireEvent.change(passwordInput(), { target: { value: password } });
}

function submit() {
  fireEvent.click(screen.getByRole('button', { name: SUBMIT }));
}

function credentialCalls(calls: RecordedRequest[]) {
  return calls.filter((c) => c.method === 'POST' && c.path === '/api/v1/auth/credentials');
}

function profileCalls(calls: RecordedRequest[]) {
  return calls.filter((c) => c.method === 'GET' && c.path === '/api/v1/users/me');
}

/** The value (dd) after the term (dt) in "Личные данные". */
function valueOf(term: string): string {
  const region = screen.getByRole('region', { name: 'Личные данные' });
  const dt = within(region).getByText(term, { selector: 'dt' });
  return dt.nextElementSibling?.textContent ?? '';
}

/** Nothing the app keeps holds the password: Redux store and browser storage. */
function expectPasswordNowhere(store: ReturnType<typeof makeStore>) {
  expect(JSON.stringify(store.getState())).not.toContain(PASSWORD);
  for (const storage of [window.localStorage, window.sessionStorage]) {
    for (let i = 0; i < storage.length; i += 1) {
      const key = storage.key(i) ?? '';
      expect(`${key}=${storage.getItem(key)}`).not.toContain(PASSWORD);
    }
  }
}

beforeEach(() => {
  installTelegram();
});

afterEach(() => {
  uninstallTelegram();
  openAt('/');
});

describe('who sees the form', () => {
  it('a Telegram-only account (email null, no password) sees "Вход на сайте" with the form', async () => {
    mockFetchRoutes(signedIn());
    launch();
    const region = await screen.findByRole('region', { name: 'Вход на сайте' });
    expect(
      within(region).getByText('Добавьте email и пароль, чтобы входить на сайте ресторана'),
    ).toBeInTheDocument();
    expect(within(region).getByLabelText('Email')).toHaveAttribute('type', 'email');
    expect(within(region).getByLabelText('Пароль')).toHaveAttribute('type', 'password');
    expect(within(region).getByRole('button', { name: SUBMIT })).toBeEnabled();
    // No password confirmation and no "show password" button.
    expect(region.querySelectorAll('input')).toHaveLength(2);
    expect(within(region).getAllByRole('button')).toHaveLength(1);

    // Placed between "Личные данные" and "Сохранённые адреса".
    const titles = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent);
    expect(titles).toEqual(['Личные данные', 'Вход на сайте', 'Сохранённые адреса']);
  });

  it.each([
    ['an account with email and password', WITH_CREDENTIALS],
    [
      'an inconsistent profile without email but with a password',
      { email: null, has_password: true },
    ],
  ])('%s does not see the form', async (_name, profile) => {
    mockFetchRoutes(signedIn({ [PROFILE]: () => me(profile) }));
    launch();
    await screen.findByRole('region', { name: 'Личные данные' });
    expect(screen.queryByRole('region', { name: 'Вход на сайте' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Пароль')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: SUBMIT })).not.toBeInTheDocument();
  });
});

describe('client validation (DEC-141)', () => {
  it('wrong email or password rules send nothing; the typed password stays to be corrected', async () => {
    const { calls } = mockFetchRoutes(signedIn(addable()));
    launch();
    await screen.findByRole('region', { name: 'Вход на сайте' });

    submit();
    expect(await within(section()).findByText('Заполните поле')).toBeInTheDocument();
    expect(
      within(section()).getByText('Пароль должен быть от 8 до 128 символов'),
    ).toBeInTheDocument();

    fill('not-an-email', 'short1');
    submit();
    expect(await within(section()).findByText('Проверьте email')).toBeInTheDocument();
    expect(
      within(section()).getByText('Пароль должен быть от 8 до 128 символов'),
    ).toBeInTheDocument();

    fill(NEW_EMAIL, 'onlyletters');
    submit();
    expect(
      await within(section()).findByText('Пароль должен содержать хотя бы одну цифру'),
    ).toBeInTheDocument();

    fill(NEW_EMAIL, '12345678');
    submit();
    expect(
      await within(section()).findByText('Пароль должен содержать хотя бы одну букву'),
    ).toBeInTheDocument();
    expect(passwordInput()).toHaveValue('12345678'); // no request: kept for correction

    expect(credentialCalls(calls)).toHaveLength(0);
  });
});

describe('adding email and password', () => {
  it('sends exactly {email, password}, shows success and hides the form; the password is gone', async () => {
    const { calls } = mockFetchRoutes(signedIn(addable()));
    const store = launch();
    await screen.findByRole('region', { name: 'Вход на сайте' });
    fill(`  ${NEW_EMAIL}  `, PASSWORD);
    submit();

    expect(await within(section()).findByRole('status')).toHaveTextContent(
      'Email и пароль добавлены. Теперь можно входить на сайте по email и паролю.',
    );
    const [call] = credentialCalls(calls);
    expect(call.body).toEqual({ email: NEW_EMAIL, password: PASSWORD });
    expect(call.headers.get('Authorization')).toBe('Bearer mini');
    expect(screen.queryByLabelText('Пароль')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: SUBMIT })).not.toBeInTheDocument();

    // The profile is reloaded after success and shows the new email.
    await waitFor(() => expect(valueOf('Email')).toBe(NEW_EMAIL));
    expect(within(section()).getByRole('status')).toBeInTheDocument();
    expectPasswordNowhere(store);
  });

  it('the success message stays when the following profile reload fails', async () => {
    let loaded = false;
    const routes = addable();
    mockFetchRoutes(
      signedIn({
        ...routes,
        [PROFILE]: () => {
          if (loaded) {
            return apiError('INTERNAL_ERROR', 500);
          }
          loaded = true;
          return me(TELEGRAM_ONLY);
        },
      }),
    );
    const store = launch();
    await screen.findByRole('region', { name: 'Вход на сайте' });
    fill(NEW_EMAIL, PASSWORD);
    submit();
    await within(section()).findByRole('status');
    await waitFor(() =>
      expect(profileApi.endpoints.getProfile.select()(store.getState()).isError).toBe(true),
    );

    // The cache still says "email: null", yet the form does not come back.
    expect(within(section()).getByRole('status')).toHaveTextContent('Email и пароль добавлены.');
    expect(screen.queryByLabelText('Пароль')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: SUBMIT })).not.toBeInTheDocument();
    expect(valueOf('Email')).toBe('Не добавлен');
  });

  it('a second submit while the request is pending sends no second POST', async () => {
    const routes = addable();
    let release!: () => void;
    const { calls } = mockFetchRoutes(
      signedIn({
        ...routes,
        [CREDENTIALS]: (request) =>
          new Promise<Response>((resolve) => {
            release = () => resolve(routes[CREDENTIALS](request));
          }),
      }),
    );
    launch();
    await screen.findByRole('region', { name: 'Вход на сайте' });
    fill(NEW_EMAIL, PASSWORD);
    const form = screen.getByRole('button', { name: SUBMIT }).closest('form')!;
    fireEvent.submit(form);
    fireEvent.submit(form);

    expect(await screen.findByRole('button', { name: 'Сохраняем…' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Сохраняем…' }));
    expect(credentialCalls(calls)).toHaveLength(1);
    expect(within(section()).queryByRole('status')).not.toBeInTheDocument();

    release();
    expect(await within(section()).findByRole('status')).toBeInTheDocument();
    expect(credentialCalls(calls)).toHaveLength(1);
  });
});

describe('errors', () => {
  it('EMAIL_ALREADY_EXISTS: error under the email, password cleared, a new attempt works', async () => {
    const routes = addable();
    const { calls } = mockFetchRoutes(
      signedIn({
        ...routes,
        [CREDENTIALS]: [() => apiError('EMAIL_ALREADY_EXISTS', 409), routes[CREDENTIALS]],
      }),
    );
    const store = launch();
    await screen.findByRole('region', { name: 'Вход на сайте' });
    fill('taken@example.com', PASSWORD);
    submit();

    expect(
      await within(section()).findByText('Этот email уже зарегистрирован'),
    ).toBeInTheDocument();
    expect(emailInput()).toHaveAttribute('aria-invalid', 'true');
    expect(emailInput()).toHaveValue('taken@example.com');
    await waitFor(() => expect(passwordInput()).toHaveValue(''));
    expect(screen.getByRole('button', { name: SUBMIT })).toBeEnabled();
    expectPasswordNowhere(store);
    expect(document.body.textContent).not.toContain(PASSWORD);

    fill(NEW_EMAIL, PASSWORD);
    submit();
    expect(await within(section()).findByRole('status')).toHaveTextContent(
      'Email и пароль добавлены.',
    );
    expect(credentialCalls(calls)).toHaveLength(2);
  });

  it('CREDENTIALS_ALREADY_SET: the form is hidden, a lasting message is shown and the profile is reloaded', async () => {
    let setElsewhere = false;
    const { calls } = mockFetchRoutes(
      signedIn({
        [PROFILE]: () =>
          me(setElsewhere ? { email: 'other@example.com', has_password: true } : TELEGRAM_ONLY),
        [CREDENTIALS]: () => {
          setElsewhere = true; // e.g. added on another device meanwhile
          return apiError('CREDENTIALS_ALREADY_SET', 409);
        },
      }),
    );
    const store = launch();
    await screen.findByRole('region', { name: 'Вход на сайте' });
    const profileBefore = profileCalls(calls).length;
    fill(NEW_EMAIL, PASSWORD);
    submit();

    expect(await within(section()).findByRole('status')).toHaveTextContent(
      'Email и пароль уже добавлены',
    );
    expect(screen.queryByLabelText('Пароль')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: SUBMIT })).not.toBeInTheDocument();
    await waitFor(() => expect(profileCalls(calls).length).toBeGreaterThan(profileBefore));
    expectPasswordNowhere(store);
  });

  it('CREDENTIALS_ALREADY_SET: the message stays after the profile reload brings the email', async () => {
    let setElsewhere = false;
    mockFetchRoutes(
      signedIn({
        [PROFILE]: () =>
          me(setElsewhere ? { email: 'other@example.com', has_password: true } : TELEGRAM_ONLY),
        [CREDENTIALS]: () => {
          setElsewhere = true;
          return apiError('CREDENTIALS_ALREADY_SET', 409);
        },
      }),
    );
    launch();
    await screen.findByRole('region', { name: 'Вход на сайте' });
    fill(NEW_EMAIL, PASSWORD);
    submit();

    // The reloaded profile no longer qualifies for the form...
    await waitFor(() => expect(valueOf('Email')).toBe('other@example.com'));
    // ...but the section with the message is still there.
    expect(within(section()).getByRole('status')).toHaveTextContent('Email и пароль уже добавлены');
    expect(screen.queryByRole('button', { name: SUBMIT })).not.toBeInTheDocument();
  });

  it('422 field errors go under the fields; the password error replaces the hint', async () => {
    const routes = addable();
    const { calls } = mockFetchRoutes(
      signedIn({
        ...routes,
        [CREDENTIALS]: () =>
          apiError('VALIDATION_ERROR', 422, [
            { field: 'email', message: 'x' },
            { field: 'password', message: 'x' },
          ]),
      }),
    );
    const store = launch();
    await screen.findByRole('region', { name: 'Вход на сайте' });
    // Before any error: the hint is shown once.
    expect(within(section()).getAllByText(HINT)).toHaveLength(1);
    fill(NEW_EMAIL, PASSWORD);
    submit();

    expect(await within(section()).findByText('Проверьте email')).toBeInTheDocument();
    expect(emailInput()).toHaveAttribute('aria-invalid', 'true');
    await waitFor(() => expect(passwordInput()).toHaveValue(''));
    // The policy text is now the error under the password, not also the hint.
    const shown = within(section()).getAllByText(HINT);
    expect(shown).toHaveLength(1);
    expect(shown[0].id).toMatch(/-error$/);
    expect(passwordInput()).toHaveAttribute('aria-invalid', 'true');
    expect(passwordInput().getAttribute('aria-describedby')).not.toMatch(/-hint/);
    // Server messages are not shown, only the localized texts.
    expect(within(section()).queryByRole('alert')).not.toBeInTheDocument();
    expect(credentialCalls(calls)).toHaveLength(1);
    expectPasswordNowhere(store);
  });

  it('server and network errors keep the form; the password is cleared and sending again works', async () => {
    const routes = addable();
    const { calls } = mockFetchRoutes(
      signedIn({
        ...routes,
        [CREDENTIALS]: [
          () => apiError('INTERNAL_ERROR', 500),
          () => {
            throw new TypeError('Failed to fetch');
          },
          routes[CREDENTIALS],
        ],
      }),
    );
    const store = launch();
    await screen.findByRole('region', { name: 'Вход на сайте' });

    fill(NEW_EMAIL, PASSWORD);
    submit();
    expect(await within(section()).findByRole('alert')).toHaveTextContent(
      'Ошибка сервера. Попробуйте позже.',
    );
    await waitFor(() => expect(passwordInput()).toHaveValue(''));
    expect(emailInput()).toHaveValue(NEW_EMAIL);
    expect(screen.getByRole('button', { name: SUBMIT })).toBeEnabled();
    expectPasswordNowhere(store);

    fill(NEW_EMAIL, PASSWORD);
    submit();
    expect(
      await within(section()).findByText('Нет связи с сервером. Проверьте подключение.'),
    ).toBeInTheDocument();
    await waitFor(() => expect(passwordInput()).toHaveValue(''));
    expect(screen.getByRole('button', { name: SUBMIT })).toBeEnabled();
    expectPasswordNowhere(store);
    expect(document.body.textContent).not.toContain(PASSWORD);

    fill(NEW_EMAIL, PASSWORD);
    submit();
    expect(await within(section()).findByRole('status')).toHaveTextContent(
      'Email и пароль добавлены.',
    );
    expect(credentialCalls(calls)).toHaveLength(3);
    expectPasswordNowhere(store);
  });
});

describe('no external links', () => {
  it('the profile of a Telegram-only account has no links to the site, sign-in or password pages', async () => {
    mockFetchRoutes(signedIn());
    launch();
    const region = await screen.findByRole('region', { name: 'Вход на сайте' });
    expect(within(region).queryAllByRole('link')).toHaveLength(0);
    expect(within(document.getElementById('main')!).queryAllByRole('link')).toHaveLength(0);
    for (const a of document.querySelectorAll('a[href]')) {
      expect(a.getAttribute('href')).toMatch(/^\/tg\//); // only the Mini App tabs
    }
  });
});
