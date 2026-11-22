import { afterEach, describe, expect, it, vi } from 'vitest';

import { apiError, jsonResponse } from '../../test/renderWithProviders';
import { mockFetchRoutes } from '../../test/fetchRoutes';
import { refreshAccessToken } from './refreshSession';

const TOKEN = { access_token: 'new-access', token_type: 'bearer', expires_in: 900 };

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('refreshAccessToken', () => {
  it('sends the cookie with the CSRF header and returns the new token', async () => {
    const { calls } = mockFetchRoutes({ 'POST /api/v1/auth/refresh': () => jsonResponse(TOKEN) });

    await expect(refreshAccessToken()).resolves.toBe('new-access');

    expect(calls).toHaveLength(1);
    expect(calls[0].credentials).toBe('include');
    expect(calls[0].headers.get('X-CSRF-Protection')).toBe('1');
  });

  it('shares one request between concurrent callers in a tab (mutex)', async () => {
    let release: (value: Response) => void = () => {};
    const { calls } = mockFetchRoutes({
      'POST /api/v1/auth/refresh': () => new Promise<Response>((resolve) => (release = resolve)),
    });

    const results = Promise.all([refreshAccessToken(), refreshAccessToken(), refreshAccessToken()]);
    await vi.waitFor(() => expect(calls).toHaveLength(1));
    release(jsonResponse(TOKEN));

    await expect(results).resolves.toEqual(['new-access', 'new-access', 'new-access']);
    expect(calls).toHaveLength(1);
  });

  it('runs under navigator.locks between tabs', async () => {
    const request = vi.fn((_name: string, callback: () => Promise<unknown>) => callback());
    vi.stubGlobal('navigator', { ...navigator, locks: { request } });
    mockFetchRoutes({ 'POST /api/v1/auth/refresh': () => jsonResponse(TOKEN) });

    await expect(refreshAccessToken()).resolves.toBe('new-access');
    expect(request).toHaveBeenCalledWith('auth-refresh', expect.any(Function));
  });

  it('returns null when the refresh is refused or the network fails', async () => {
    mockFetchRoutes({ 'POST /api/v1/auth/refresh': () => apiError('INVALID_REFRESH_TOKEN', 401) });
    await expect(refreshAccessToken()).resolves.toBeNull();

    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('offline'));
    await expect(refreshAccessToken()).resolves.toBeNull();
  });
});
