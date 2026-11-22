import {
  type BaseQueryFn,
  createApi,
  type FetchArgs,
  fetchBaseQuery,
  type FetchBaseQueryError,
} from '@reduxjs/toolkit/query/react';

import {
  passwordChangeRequired,
  selectAccessToken,
  sessionEnded,
  sessionStarted,
  type AuthState,
} from '../../features/auth/authSlice';
import { refreshAccessToken } from '../../features/auth/refreshSession';
import {
  selectTelegramActive,
  telegramPhaseChanged,
  type TelegramState,
} from '../../features/telegram/telegramSlice';
import { exchangeTelegramSession, phaseFor } from '../../features/telegram/telegramSession';
import { apiBaseUrl } from './http';

export { API_PREFIX } from './http';

const rawBaseQuery = fetchBaseQuery({
  baseUrl: apiBaseUrl(),
  credentials: 'include',
  prepareHeaders: (headers, { getState }) => {
    const token = selectAccessToken(getState() as { auth: AuthState });
    if (token && !headers.has('Authorization')) {
      headers.set('Authorization', `Bearer ${token}`);
    }
    return headers;
  },
});

// These endpoints answer 401 for reasons other than an expired access token
// (wrong credentials, invalid refresh cookie or initData): never retry them
// via refresh or a new initData exchange (API §2.3, DEC-152 п. 11).
const NO_REAUTH = new Set([
  'auth/login',
  'auth/register',
  'auth/refresh',
  'auth/logout',
  'auth/password/forgot',
  'auth/password/reset',
  'auth/telegram/webapp',
  'auth/telegram/webapp/register',
  'auth/telegram/webapp/link',
]);

function errorCode(error: FetchBaseQueryError | undefined): string | undefined {
  const data = error?.data as { error?: { code?: string } } | undefined;
  return data?.error?.code;
}

/**
 * RTK Query base query with re-authentication (UI_UX_GUIDELINES.md §7):
 * on 401 one refresh (shared mutex + navigator.locks) and one retry; if the
 * refresh fails the session is cleared and protected routes redirect to
 * /login. 403 PASSWORD_CHANGE_REQUIRED marks the session so that only the
 * password change screen is available (DEC-28).
 *
 * Telegram Mini App (DEC-142, DEC-152): once its bootstrap started, a 401
 * is answered by a new initData exchange instead — never by the refresh
 * cookie or navigator.locks; parallel 401s share one exchange. If it fails,
 * the session ends and the Mini App shows the matching screen.
 */
export const baseQueryWithReauth: BaseQueryFn<
  string | FetchArgs,
  unknown,
  FetchBaseQueryError
> = async (args, api, extraOptions) => {
  let result = await rawBaseQuery(args, api, extraOptions);
  const url = typeof args === 'string' ? args : args.url;

  if (result.error?.status === 401 && !NO_REAUTH.has(url)) {
    if (selectTelegramActive(api.getState() as { telegram?: TelegramState })) {
      const outcome = await exchangeTelegramSession();
      if (outcome.kind === 'ok') {
        api.dispatch(sessionStarted(outcome.token));
        result = await rawBaseQuery(args, api, extraOptions);
      } else {
        api.dispatch(sessionEnded());
        api.dispatch(telegramPhaseChanged(phaseFor(outcome)));
      }
    } else {
      const token = await refreshAccessToken();
      if (token) {
        api.dispatch(sessionStarted(token));
        result = await rawBaseQuery(args, api, extraOptions);
      } else {
        api.dispatch(sessionEnded());
      }
    }
  }
  if (result.error?.status === 403 && errorCode(result.error) === 'PASSWORD_CHANGE_REQUIRED') {
    api.dispatch(passwordChangeRequired(true));
  }
  return result;
};

// All frontend API access goes through RTK Query. Feature modules add their
// endpoints with `baseApi.injectEndpoints`.
export const baseApi = createApi({
  reducerPath: 'api',
  baseQuery: baseQueryWithReauth,
  tagTypes: [
    'Me',
    'AdminCategories',
    'AdminProducts',
    'AdminGroups',
    'Catalog',
    'Cart',
    'Addresses',
    'Orders',
    'AdminOrders',
    'Staff',
    'Settings',
    'Zones',
    'Dashboard',
    'Kitchen',
    'Couriers',
    'CourierOrders',
  ],
  endpoints: () => ({}),
});
