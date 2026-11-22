import type { SerializedError } from '@reduxjs/toolkit';
import type { FetchBaseQueryError } from '@reduxjs/toolkit/query';

import { apiErrorInfo } from '../../shared/api/errors';
import type { TelegramPhase } from './telegramSlice';

// What a failed registration or linking means for the Mini App (API §1.1,
// §2.3; MA-4.1). Either the launch cannot go on and a service screen is
// shown (`phase`), or the user stays on the choice screen / the form and
// sees a localized text (`messageKey`, an i18n key). Texts never reveal
// why credentials were rejected (DEC-103).

export type OnboardingFailure =
  { phase: Extract<TelegramPhase, 'restart' | 'forbidden' | 'disabled'> } | { messageKey: string };

type ApiError = FetchBaseQueryError | SerializedError | undefined;

function statusOf(error: ApiError): unknown {
  return error && 'status' in error ? error.status : undefined;
}

function codeMessage(error: ApiError): OnboardingFailure {
  // TELEGRAM_BUSY, RATE_LIMITED (429), VALIDATION_ERROR, INTERNAL_ERROR,
  // NETWORK_ERROR, … — each has its text; unknown codes get the default.
  return { messageKey: `errors.codes.${apiErrorInfo(error)?.code ?? 'default'}` };
}

function launchFailure(error: ApiError): OnboardingFailure | null {
  const code = apiErrorInfo(error)?.code;
  if (statusOf(error) === 401 && code === 'INVALID_TELEGRAM_AUTH') {
    return { phase: 'restart' }; // initData expired or invalid: reopen the Mini App
  }
  if (statusOf(error) === 409 && code === 'TELEGRAM_DISABLED') {
    return { phase: 'disabled' };
  }
  return null;
}

/** `POST /auth/telegram/webapp/register`. */
export function registerFailure(error: ApiError): OnboardingFailure {
  const launch = launchFailure(error);
  if (launch) {
    return launch;
  }
  if (statusOf(error) === 401) {
    // The link appeared meanwhile and its user is inactive: same answer as
    // the sign-in, the reason is not shown.
    return { phase: 'restart' };
  }
  if (statusOf(error) === 403) {
    // The link appeared meanwhile and belongs to a staff account.
    return { phase: 'forbidden' };
  }
  return codeMessage(error);
}

/** `POST /auth/telegram/webapp/link`. */
export function linkFailure(error: ApiError): OnboardingFailure {
  const launch = launchFailure(error);
  if (launch) {
    return launch;
  }
  if (statusOf(error) === 401) {
    // INVALID_CREDENTIALS: wrong email or password, no email, inactive.
    return { messageKey: 'errors.codes.INVALID_CREDENTIALS' };
  }
  if (statusOf(error) === 403) {
    // The password is right but the account is not a customer one; this
    // Telegram stays unlinked, so the user may still choose another way.
    return { messageKey: 'telegram.onboarding.linkForbidden' };
  }
  return codeMessage(error);
}
