import { render } from '@testing-library/react';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router';

import { AppProviders } from '../app/providers/AppProviders';
import { makeStore } from '../app/store/store';
import type { AuthState } from '../features/auth/authSlice';

export const ANONYMOUS: AuthState = {
  accessToken: null,
  status: 'anonymous',
  passwordChangeRequired: false,
};

interface Options {
  // The session state at start; anonymous by default, so the bootstrap
  // refresh does not run unless a test asks for it with status 'unknown'.
  auth?: AuthState;
  // Wrap in a MemoryRouter at this entry (for components using links).
  route?: string;
}

/** Renders with a fresh store per test so RTK Query caches never leak. */
export function renderWithProviders(ui: ReactElement, { auth = ANONYMOUS, route }: Options = {}) {
  const store = makeStore({ auth });
  const content = route ? <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter> : ui;
  return { store, ...render(<AppProviders store={store}>{content}</AppProviders>) };
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

export function emptyResponse(status = 204): Response {
  return new Response(null, { status });
}

export function apiError(code: string, status: number, details: unknown = []): Response {
  return jsonResponse({ error: { code, message: 'x', details, request_id: 'r1' } }, status);
}
