import { describe, expect, it } from 'vitest';

import { makeStore } from '../../app/store/store';
import { authApi } from '../../features/auth/authApi';
import { mockFetchRoutes } from '../../test/fetchRoutes';
import { apiError, jsonResponse } from '../../test/renderWithProviders';

const ME = {
  id: '00000000-0000-0000-0000-000000000001',
  email: 'user@example.com',
  full_name: 'User',
  phone: null,
  preferred_language: 'ru',
  roles: ['customer'],
  must_change_password: false,
  has_password: true,
};

function authenticatedStore(token = 'old-access') {
  return makeStore({
    auth: { accessToken: token, status: 'authenticated', passwordChangeRequired: false },
  });
}

describe('baseQueryWithReauth', () => {
  it('sends the access token from memory', async () => {
    const { calls } = mockFetchRoutes({ 'GET /api/v1/auth/me': () => jsonResponse(ME) });
    const store = authenticatedStore();

    await store.dispatch(authApi.endpoints.me.initiate());

    expect(calls[0].headers.get('Authorization')).toBe('Bearer old-access');
  });

  it('on 401 refreshes once and retries with the new token', async () => {
    const { calls } = mockFetchRoutes({
      'GET /api/v1/auth/me': [() => apiError('UNAUTHORIZED', 401), () => jsonResponse(ME)],
      'POST /api/v1/auth/refresh': () =>
        jsonResponse({ access_token: 'fresh-access', token_type: 'bearer', expires_in: 900 }),
    });
    const store = authenticatedStore();

    const result = await store.dispatch(authApi.endpoints.me.initiate());

    expect(result.data?.email).toBe('user@example.com');
    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual([
      'GET /api/v1/auth/me',
      'POST /api/v1/auth/refresh',
      'GET /api/v1/auth/me',
    ]);
    expect(calls[2].headers.get('Authorization')).toBe('Bearer fresh-access');
    expect(store.getState().auth.accessToken).toBe('fresh-access');
  });

  it('ends the session when the refresh fails', async () => {
    mockFetchRoutes({
      'GET /api/v1/auth/me': () => apiError('UNAUTHORIZED', 401),
      'POST /api/v1/auth/refresh': () => apiError('INVALID_REFRESH_TOKEN', 401),
    });
    const store = authenticatedStore();

    await store.dispatch(authApi.endpoints.me.initiate());

    expect(store.getState().auth).toEqual({
      accessToken: null,
      status: 'anonymous',
      passwordChangeRequired: false,
    });
  });

  it('never refreshes for a failed login', async () => {
    const { calls } = mockFetchRoutes({
      'POST /api/v1/auth/login': () => apiError('INVALID_CREDENTIALS', 401),
    });
    const store = makeStore();

    await store.dispatch(authApi.endpoints.login.initiate({ email: 'a@b.c', password: 'x' }));

    expect(calls.map((c) => c.path)).toEqual(['/api/v1/auth/login']);
  });

  it('marks PASSWORD_CHANGE_REQUIRED', async () => {
    mockFetchRoutes({
      'GET /api/v1/auth/me': () => apiError('PASSWORD_CHANGE_REQUIRED', 403),
    });
    const store = authenticatedStore();

    await store.dispatch(authApi.endpoints.me.initiate());

    expect(store.getState().auth.passwordChangeRequired).toBe(true);
  });
});
