import { apiUrl, CSRF_HEADERS } from '../../shared/api/http';
import type { TokenResponse } from '../../shared/types/api';

// Refresh rotation is strict: re-using a rotated token revokes the whole
// family (DEC-65, DEC-110). Therefore only one refresh may run at a time:
// - inside a tab, concurrent callers share one in-flight promise (mutex);
// - between tabs, the refresh runs under navigator.locks; after getting the
//   lock the tab sends the current cookie, already rotated by another tab if
//   that tab refreshed first.
const LOCK_NAME = 'auth-refresh';

let inFlight: Promise<string | null> | null = null;

async function requestRefresh(): Promise<string | null> {
  const response = await fetch(apiUrl('auth/refresh'), {
    method: 'POST',
    credentials: 'include',
    headers: CSRF_HEADERS,
  });
  if (!response.ok) {
    return null;
  }
  const body = (await response.json()) as Partial<TokenResponse>;
  return typeof body.access_token === 'string' ? body.access_token : null;
}

async function underCrossTabLock(): Promise<string | null> {
  const locks = typeof navigator !== 'undefined' ? navigator.locks : undefined;
  if (locks?.request) {
    return locks.request(LOCK_NAME, () => requestRefresh());
  }
  return requestRefresh();
}

/** Returns a new access token, or null when the session cannot be restored. */
export function refreshAccessToken(): Promise<string | null> {
  if (!inFlight) {
    inFlight = underCrossTabLock()
      .catch(() => null)
      .finally(() => {
        inFlight = null;
      });
  }
  return inFlight;
}
