export const CHANGE_PASSWORD_PATH = '/change-password';
export const DEFAULT_AFTER_LOGIN = '/account';
// Site page of the password reset request; the Mini App opens it with openLink.
export const FORGOT_PASSWORD_PATH = '/forgot-password';

/** Only internal paths are accepted as a return target (no open redirects). */
export function safeReturnTo(value: string | null): string {
  if (value && value.startsWith('/') && !value.startsWith('//') && !value.startsWith('/\\')) {
    return value;
  }
  return DEFAULT_AFTER_LOGIN;
}
