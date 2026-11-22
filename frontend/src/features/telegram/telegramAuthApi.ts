import { baseApi } from '../../shared/api/baseApi';
import type { TokenResponse } from '../../shared/types/api';
import { currentInitData } from './telegramSession';

// Registration and account linking from the Mini App (API §2.3, DEC-152
// п. 2, MA-4.1). Both answer only an access token. Like the initData
// exchange they send no cookie and no CSRF header. The baseApi never
// retries them with a new exchange: they are listed in NO_REAUTH, so a 401
// of the form never ends or replaces a session.
//
// The raw initData is read when the request is built, so it is not kept in
// the mutation's arguments in the Redux state; the form drops the mutation
// (and with it the password) as soon as the request has settled.

export interface TelegramLinkCredentials {
  email: string;
  password: string;
}

export const telegramAuthApi = baseApi.injectEndpoints({
  endpoints: (build) => ({
    telegramRegister: build.mutation<TokenResponse, void>({
      query: () => ({
        url: 'auth/telegram/webapp/register',
        method: 'POST',
        credentials: 'omit',
        body: { init_data: currentInitData() },
      }),
    }),
    telegramLink: build.mutation<TokenResponse, TelegramLinkCredentials>({
      query: ({ email, password }) => ({
        url: 'auth/telegram/webapp/link',
        method: 'POST',
        credentials: 'omit',
        body: { init_data: currentInitData(), email, password },
      }),
    }),
  }),
});

export const { useTelegramRegisterMutation, useTelegramLinkMutation } = telegramAuthApi;
