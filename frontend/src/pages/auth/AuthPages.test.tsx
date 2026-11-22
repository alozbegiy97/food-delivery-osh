import { fireEvent, render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { describe, expect, it } from 'vitest';

import { AppProviders } from '../../app/providers/AppProviders';
import { routes } from '../../app/router/routes';
import { makeStore } from '../../app/store/store';
import type { AuthState } from '../../features/auth/authSlice';
import { callTo, mockFetchRoutes } from '../../test/fetchRoutes';
import { ANONYMOUS, apiError, emptyResponse, jsonResponse } from '../../test/renderWithProviders';

const TOKEN = { access_token: 'access-1', token_type: 'bearer', expires_in: 900 };
const ME = {
  id: '00000000-0000-0000-0000-000000000001',
  email: 'user@example.com',
  full_name: 'Айгуль',
  phone: '+996700123456',
  preferred_language: 'ru',
  roles: ['customer'],
  must_change_password: false,
  has_password: true,
};

function renderApp(path: string, auth: AuthState = ANONYMOUS) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const store = makeStore({ auth });
  render(
    <AppProviders store={store}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return { router, store };
}

function type(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

describe('login', () => {
  it('signs in and returns to the requested page', async () => {
    const { calls } = mockFetchRoutes({
      'POST /api/v1/auth/login': () => jsonResponse(TOKEN),
      'GET /api/v1/auth/me': () => jsonResponse(ME),
    });
    const { router, store } = renderApp('/login?returnTo=%2Faccount');

    type('Email', 'user@example.com');
    type('Пароль', 'correct1horse');
    fireEvent.click(screen.getByRole('button', { name: 'Войти' }));

    expect(await screen.findByRole('heading', { name: 'Мой аккаунт' })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/account');
    expect(store.getState().auth.accessToken).toBe('access-1');
    expect(callTo(calls, '/api/v1/auth/login').body).toEqual({
      email: 'user@example.com',
      password: 'correct1horse',
    });
    expect(await screen.findByText('Айгуль', { selector: 'dd' })).toBeInTheDocument();
  });

  it('shows one message for wrong credentials and validates empty fields', async () => {
    mockFetchRoutes({ 'POST /api/v1/auth/login': () => apiError('INVALID_CREDENTIALS', 401) });
    renderApp('/login');

    fireEvent.click(screen.getByRole('button', { name: 'Войти' }));
    expect(await screen.findAllByText('Заполните поле')).toHaveLength(2);

    type('Email', 'user@example.com');
    type('Пароль', 'wrong1pass');
    fireEvent.click(screen.getByRole('button', { name: 'Войти' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Неверный email или пароль');
  });

  it('does not follow an external returnTo', async () => {
    mockFetchRoutes({
      'POST /api/v1/auth/login': () => jsonResponse(TOKEN),
      'GET /api/v1/auth/me': () => jsonResponse(ME),
    });
    const { router } = renderApp('/login?returnTo=%2F%2Fevil.example');
    type('Email', 'user@example.com');
    type('Пароль', 'correct1horse');
    fireEvent.click(screen.getByRole('button', { name: 'Войти' }));
    await screen.findByRole('heading', { name: 'Мой аккаунт' });
    expect(router.state.location.pathname).toBe('/account');
  });
});

describe('register', () => {
  it('validates with the backend policy and sends the UI language', async () => {
    const { calls } = mockFetchRoutes({
      'POST /api/v1/auth/register': () => jsonResponse(TOKEN, 201),
      'GET /api/v1/auth/me': () => jsonResponse(ME),
    });
    renderApp('/register');

    type('Имя', '  Айгуль  ');
    type('Email', 'user@example.com');
    type('Телефон (необязательно)', '0700123456');
    expect(screen.getByLabelText('Телефон (необязательно)')).toHaveValue('+996 700 12 34 56');

    type('Пароль', 'парольбезцифр');
    fireEvent.click(screen.getByRole('button', { name: 'Зарегистрироваться' }));
    expect(
      await screen.findByText('Пароль должен содержать хотя бы одну цифру'),
    ).toBeInTheDocument();
    expect(calls.filter((c) => c.path === '/api/v1/auth/register')).toHaveLength(0);

    type('Пароль', 'пароль12'); // Cyrillic letters count as letters (DEC-96)
    fireEvent.click(screen.getByRole('button', { name: 'Зарегистрироваться' }));
    await screen.findByRole('heading', { name: 'Мой аккаунт' });
    expect(callTo(calls, '/api/v1/auth/register').body).toEqual({
      email: 'user@example.com',
      full_name: 'Айгуль',
      password: 'пароль12',
      phone: '+996 700 12 34 56',
      preferred_language: 'ru',
    });
  });

  it('shows a taken email', async () => {
    mockFetchRoutes({ 'POST /api/v1/auth/register': () => apiError('EMAIL_ALREADY_EXISTS', 409) });
    renderApp('/register');
    type('Имя', 'A');
    type('Email', 'user@example.com');
    type('Пароль', 'correct1horse');
    fireEvent.click(screen.getByRole('button', { name: 'Зарегистрироваться' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Этот email уже зарегистрирован');
  });
});

describe('password reset', () => {
  it('shows the same answer after a forgot request', async () => {
    const { calls } = mockFetchRoutes({
      'POST /api/v1/auth/password/forgot': () =>
        jsonResponse({ message: 'Если аккаунт существует, мы отправили письмо' }, 202),
    });
    renderApp('/forgot-password');
    type('Email', 'User@Example.com');
    fireEvent.click(screen.getByRole('button', { name: 'Отправить ссылку' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Если аккаунт существует');
    expect(callTo(calls, '/api/v1/auth/password/forgot').body).toEqual({
      email: 'User@Example.com',
    });
  });

  it('sets a new password with the token from the link', async () => {
    const { calls } = mockFetchRoutes({
      'POST /api/v1/auth/password/reset': () => emptyResponse(),
    });
    const { router } = renderApp('/reset-password?token=abc123');
    type('Новый пароль', 'battery2staple');
    type('Повторите пароль', 'battery2staple');
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить пароль' }));
    expect(await screen.findByText('Пароль изменён. Войдите с новым паролем.')).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/login');
    expect(callTo(calls, '/api/v1/auth/password/reset').body).toEqual({
      token: 'abc123',
      new_password: 'battery2staple',
    });
  });

  it('reports an expired link', async () => {
    mockFetchRoutes({
      'POST /api/v1/auth/password/reset': () => apiError('INVALID_OR_EXPIRED_TOKEN', 400),
    });
    renderApp('/reset-password?token=old');
    type('Новый пароль', 'battery2staple');
    type('Повторите пароль', 'battery2staple');
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить пароль' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Ссылка недействительна или устарела',
    );
  });
});

describe('protected routes and session', () => {
  it('sends guests to login with returnTo', async () => {
    const { router } = renderApp('/account');
    await screen.findByRole('heading', { name: 'Вход' });
    expect(router.state.location.pathname).toBe('/login');
    expect(router.state.location.search).toBe('?returnTo=%2Faccount');
  });

  it('restores the session from the refresh cookie on load', async () => {
    const { calls } = mockFetchRoutes({
      'POST /api/v1/auth/refresh': () => jsonResponse(TOKEN),
      'GET /api/v1/auth/me': () => jsonResponse(ME),
    });
    renderApp('/account', { accessToken: null, status: 'unknown', passwordChangeRequired: false });
    expect(await screen.findByRole('heading', { name: 'Мой аккаунт' })).toBeInTheDocument();
    expect(callTo(calls, '/api/v1/auth/refresh').method).toBe('POST');
  });

  it('keeps a user with a temporary password on the change screen', async () => {
    const { calls } = mockFetchRoutes({
      'GET /api/v1/auth/me': () =>
        jsonResponse({ ...ME, roles: ['cook'], must_change_password: true }),
      'POST /api/v1/auth/password/change': [
        () => apiError('CURRENT_PASSWORD_INVALID', 422),
        () => emptyResponse(),
      ],
    });
    const { router } = renderApp('/account', {
      accessToken: 'a',
      status: 'authenticated',
      passwordChangeRequired: false,
    });
    expect(await screen.findByRole('heading', { name: 'Смена пароля' })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/change-password');

    type('Текущий пароль', 'wrong1pass');
    type('Новый пароль', 'battery2staple');
    type('Повторите пароль', 'battery2staple');
    fireEvent.click(screen.getByRole('button', { name: 'Сменить пароль' }));
    expect(await screen.findByText('Текущий пароль указан неверно')).toBeInTheDocument();

    type('Текущий пароль', 'temporary1');
    fireEvent.click(screen.getByRole('button', { name: 'Сменить пароль' }));
    expect(
      await screen.findByText('Пароль изменён. Войдите снова с новым паролем.'),
    ).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/login');
    expect(calls.filter((c) => c.path === '/api/v1/auth/password/change')).toHaveLength(2);
  });

  it('logs out and clears the session', async () => {
    const { calls } = mockFetchRoutes({
      'GET /api/v1/auth/me': () => jsonResponse(ME),
      'POST /api/v1/auth/logout': () => emptyResponse(),
    });
    const { router, store } = renderApp('/account', {
      accessToken: 'a',
      status: 'authenticated',
      passwordChangeRequired: false,
    });
    fireEvent.click(await screen.findByRole('button', { name: 'Выйти' }));
    await screen.findByRole('link', { name: 'Вход' });
    expect(router.state.location.pathname).toBe('/');
    expect(store.getState().auth.status).toBe('anonymous');
    const logout = calls.find((c) => c.path === '/api/v1/auth/logout');
    expect(logout?.headers.get('X-CSRF-Protection')).toBe('1');
  });
});
