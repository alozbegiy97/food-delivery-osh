import { useRef, useState } from 'react';
import { useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { useDispatch } from 'react-redux';

import { baseApi } from '../../../shared/api/baseApi';
import { apiErrorInfo } from '../../../shared/api/errors';
import { TextField } from '../../../shared/components/TextField';
import { zodResolver } from '../../../shared/lib/zodResolver';
import { useAddCredentialsMutation } from '../../auth/authApi';
import { FormAlert, SubmitButton } from '../../auth/components/AuthCard';
import { useApiErrorText } from '../../auth/useApiErrorText';
import { credentialsSchema, type CredentialsValues } from '../validation';

type ApiError = Parameters<typeof apiErrorInfo>[0];

/** Server field errors (422 `details`) shown under the matching input, as i18n keys. */
const SERVER_FIELD_MESSAGES = {
  email: 'validation.emailInvalid',
  password: 'auth.hints.password',
} as const;

function isFormField(field: string): field is keyof typeof SERVER_FIELD_MESSAGES {
  return field in SERVER_FIELD_MESSAGES;
}

/**
 * "Email + password" for a Telegram-only account (DEC-160 п. 5, DEC-142):
 * POST /auth/credentials with the registration rules (DEC-141), without a
 * password confirmation and without a "show password" button.
 *
 * The password exists only in its input until the request completes. After
 * every attempt (success or error) the request is reset, which removes its
 * arguments with the password from the Redux store, and the password input
 * is cleared; the email is kept. Server messages are never shown: only
 * localized texts by error code or field. Nothing is written to browser
 * storage or logs.
 */
interface AddCredentialsFormProps {
  /** After a confirmed 204. */
  onAdded: () => void;
  /** After 409 CREDENTIALS_ALREADY_SET: set meanwhile, e.g. on another device. */
  onAlreadySet: () => void;
}

export function AddCredentialsForm({ onAdded, onAlreadySet }: AddCredentialsFormProps) {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const errorText = useApiErrorText();
  const [addCredentials] = useAddCredentialsMutation();
  const [pending, setPending] = useState(false);
  // A ref, not only state: two quick submits must not both send a request.
  const running = useRef(false);
  const [message, setMessage] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    resetField,
    setError,
    formState: { errors },
  } = useForm<CredentialsValues>({
    resolver: zodResolver(credentialsSchema),
    defaultValues: { email: '', password: '' },
  });

  // A plain function, wrapped by handleSubmit only in the form's submit
  // event: the ref is read when the form is submitted, never during render.
  const submit = async (values: CredentialsValues) => {
    if (running.current) {
      return; // no second request while one is running
    }
    running.current = true;
    setPending(true);
    setMessage(null);
    const request = addCredentials({ email: values.email, password: values.password });
    let outcome: 'added' | 'alreadySet' | null = null;
    try {
      await request.unwrap();
      outcome = 'added';
    } catch (failure) {
      const info = apiErrorInfo(failure as ApiError);
      if (info?.code === 'CREDENTIALS_ALREADY_SET') {
        // The page keeps the message and does not show the form again; the
        // profile is reloaded separately (no automatic reload on errors).
        outcome = 'alreadySet';
        dispatch(baseApi.util.invalidateTags(['Me']));
      } else if (info?.code === 'EMAIL_ALREADY_EXISTS') {
        setError('email', { type: 'server', message: 'errors.codes.EMAIL_ALREADY_EXISTS' });
      } else if (
        info?.code === 'VALIDATION_ERROR' &&
        info.fields.some(({ field }) => isFormField(field))
      ) {
        for (const { field } of info.fields) {
          if (isFormField(field)) {
            setError(field, { type: 'server', message: SERVER_FIELD_MESSAGES[field] });
          }
        }
      } else {
        setMessage(errorText(failure as ApiError));
      }
    } finally {
      // Drops the request (and the password in its arguments) from the store.
      request.reset();
      // The password never outlives the attempt; a server error under the
      // field stays visible.
      resetField('password', { keepError: true });
      running.current = false;
      setPending(false);
    }
    if (outcome === 'added') {
      onAdded();
    } else if (outcome === 'alreadySet') {
      onAlreadySet();
    }
  };

  const fieldError = (key?: string) => (key ? t(key) : undefined);
  // An error under the password replaces the hint, so the policy text is
  // never shown twice; without an error the usual hint is shown.
  const passwordHint = errors.password ? undefined : t('auth.hints.password');

  return (
    <form
      noValidate
      onSubmit={(event) => void handleSubmit(submit)(event)}
      className="flex flex-col gap-4"
    >
      {message && <FormAlert>{message}</FormAlert>}
      <TextField
        label={t('auth.fields.email')}
        type="email"
        autoComplete="email"
        error={fieldError(errors.email?.message)}
        {...register('email')}
      />
      <TextField
        label={t('auth.fields.password')}
        type="password"
        autoComplete="new-password"
        hint={passwordHint}
        error={fieldError(errors.password?.message)}
        {...register('password')}
      />
      <SubmitButton pending={pending}>
        {pending ? t('telegram.profile.saving') : t('telegram.profile.credentials.submit')}
      </SubmitButton>
    </form>
  );
}
