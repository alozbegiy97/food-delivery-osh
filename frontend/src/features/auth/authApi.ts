import { baseApi } from '../../shared/api/baseApi';
import { CSRF_HEADERS } from '../../shared/api/http';
import type {
  AcceptedResponse,
  CredentialsRequest,
  LoginRequest,
  MeResponse,
  PasswordChangeRequest,
  PasswordForgotRequest,
  PasswordResetRequest,
  RegisterRequest,
  TokenResponse,
} from '../../shared/types/api';
import { passwordChangeRequired, sessionEnded, sessionStarted } from './authSlice';

/** After login/register: keep the access token in memory and load /me. */
async function startSessionOnSuccess(
  _arg: unknown,
  {
    dispatch,
    queryFulfilled,
  }: {
    dispatch: (action: unknown) => unknown;
    queryFulfilled: Promise<{ data: TokenResponse }>;
  },
) {
  let data: TokenResponse;
  try {
    ({ data } = await queryFulfilled);
  } catch {
    return; // the form shows the error from the mutation state
  }
  dispatch(sessionStarted(data.access_token));
  dispatch(baseApi.util.invalidateTags(['Me']));
}

export const authApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    login: build.mutation<TokenResponse, LoginRequest>({
      query: (body) => ({ url: 'auth/login', method: 'POST', body }),
      onQueryStarted: startSessionOnSuccess,
    }),
    register: build.mutation<TokenResponse, RegisterRequest>({
      query: (body) => ({ url: 'auth/register', method: 'POST', body }),
      onQueryStarted: startSessionOnSuccess,
    }),
    me: build.query<MeResponse, void>({
      query: () => 'auth/me',
      providesTags: ['Me'],
      async onQueryStarted(_arg, { dispatch, queryFulfilled }) {
        try {
          const { data } = await queryFulfilled;
          dispatch(passwordChangeRequired(data.must_change_password));
        } catch {
          // Errors are shown by the component that uses the query.
        }
      },
    }),
    logout: build.mutation<void, void>({
      query: () => ({ url: 'auth/logout', method: 'POST', headers: CSRF_HEADERS }),
      async onQueryStarted(_arg, { dispatch, queryFulfilled }) {
        try {
          await queryFulfilled;
        } finally {
          // The local session is always cleared (UI_UX_GUIDELINES.md §7).
          dispatch(sessionEnded());
          dispatch(baseApi.util.resetApiState());
        }
      },
    }),
    changePassword: build.mutation<void, PasswordChangeRequest>({
      query: (body) => ({ url: 'auth/password/change', method: 'POST', body }),
      async onQueryStarted(_arg, { dispatch, queryFulfilled }) {
        try {
          await queryFulfilled;
        } catch {
          return; // the form shows the error; the session is unchanged
        }
        // Every session was revoked and the cookie cleared: sign in again.
        dispatch(sessionEnded());
        dispatch(baseApi.util.resetApiState());
      },
    }),
    forgotPassword: build.mutation<AcceptedResponse, PasswordForgotRequest>({
      query: (body) => ({ url: 'auth/password/forgot', method: 'POST', body }),
    }),
    resetPassword: build.mutation<void, PasswordResetRequest>({
      query: (body) => ({ url: 'auth/password/reset', method: 'POST', body }),
    }),
    // Email and password for a Telegram-only account (API §2.3, DEC-142,
    // DEC-160 п. 5): 204 without a body. The body is exactly {email, password}.
    // The profile is reloaded only after success; a failed request changes
    // nothing on the server. The caller must reset() the request when it
    // completes, so the password does not stay in the store.
    addCredentials: build.mutation<void, CredentialsRequest>({
      query: ({ email, password }) => ({
        url: 'auth/credentials',
        method: 'POST',
        body: { email, password },
      }),
      invalidatesTags: (_result, error) => (error ? [] : ['Me']),
    }),
  }),
});

export const {
  useLoginMutation,
  useRegisterMutation,
  useMeQuery,
  useLogoutMutation,
  useChangePasswordMutation,
  useForgotPasswordMutation,
  useResetPasswordMutation,
  useAddCredentialsMutation,
} = authApi;
