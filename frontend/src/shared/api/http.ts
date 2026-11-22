// Single origin (DEC-68): the API lives under /api/v1 on the same host as the
// frontend (Vite proxy in dev, nginx in demo). An absolute URL is built from
// the current origin so requests work the same in the browser and in tests.
export const API_PREFIX = '/api/v1/';

export function apiBaseUrl(): string {
  return new URL(API_PREFIX, window.location.origin).toString();
}

export function apiUrl(path: string): string {
  return new URL(path, apiBaseUrl()).toString();
}

// Cookie-based operations (/auth/refresh, /auth/logout) need this header in
// addition to the browser's Origin (DEC-68, DEC-140).
export const CSRF_HEADERS = { 'X-CSRF-Protection': '1' } as const;
