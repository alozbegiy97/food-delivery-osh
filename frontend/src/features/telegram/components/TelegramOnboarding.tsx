import type { SerializedError } from '@reduxjs/toolkit';
import type { FetchBaseQueryError } from '@reduxjs/toolkit/query';
import { useState, type ReactNode } from 'react';
import { useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { useDispatch } from 'react-redux';
import { useNavigate } from 'react-router';

import { baseApi } from '../../../shared/api/baseApi';
import { TextField } from '../../../shared/components/TextField';
import { MINI_APP_START } from '../../../shared/lib/miniAppMode';
import { zodResolver } from '../../../shared/lib/zodResolver';
import { sessionStarted } from '../../auth/authSlice';
import { FormAlert } from '../../auth/components/AuthCard';
import { FORGOT_PASSWORD_PATH } from '../../auth/paths';
import { loginSchema, type LoginValues } from '../../auth/validation';
import { openExternalLink, siteUrl } from '../linkGuard';
import { linkFailure, registerFailure, type OnboardingFailure } from '../onboardingErrors';
import { useTelegramLinkMutation, useTelegramRegisterMutation } from '../telegramAuthApi';
import { telegramPhaseChanged } from '../telegramSlice';

// First launch without a link (409 TELEGRAM_NOT_LINKED; UI_UX §3, DEC-152
// п. 2, MA-4.1): the user chooses between a new account and linking an
// existing site account. Nothing is created without that choice. After
// success the Mini App is signed in and opens /tg/menu.

type ApiError = FetchBaseQueryError | SerializedError;

const primary =
  'min-h-11 rounded-full bg-accent-700 px-5 font-semibold text-on-accent hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-60';
const secondary =
  'min-h-11 rounded-full border border-accent-700 px-5 font-semibold text-accent-800 focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-60';
const textButton =
  'self-start text-sm text-accent-800 underline focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-60';

function useOnboardingOutcome() {
  const dispatch = useDispatch();
  const navigate = useNavigate();
  return {
    async signedIn(token: string) {
      // The start page first, then the session: the page that was opened
      // (e.g. /tg/cart) never renders on its own.
      await navigate(MINI_APP_START, { replace: true });
      dispatch(sessionStarted(token));
      dispatch(baseApi.util.invalidateTags(['Me']));
      dispatch(telegramPhaseChanged('ready'));
    },
    /** A service screen, or the message key to show on the current step. */
    failed(failure: OnboardingFailure): string | null {
      if ('phase' in failure) {
        dispatch(telegramPhaseChanged(failure.phase));
        return null;
      }
      return failure.messageKey;
    },
  };
}

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mx-auto flex w-full max-w-md flex-col gap-4 rounded-[var(--radius-card)] border border-border bg-surface p-6">
      <h1 className="text-xl font-bold text-ink-900">{title}</h1>
      {children}
    </section>
  );
}

function ErrorText({ messageKey }: { messageKey: string | null }) {
  const { t } = useTranslation();
  if (!messageKey) {
    return null;
  }
  return <FormAlert>{t(messageKey, { defaultValue: t('errors.codes.default') })}</FormAlert>;
}

function ChoiceStep({ onHaveAccount }: { onHaveAccount: () => void }) {
  const { t } = useTranslation();
  const outcome = useOnboardingOutcome();
  const [register] = useTelegramRegisterMutation();
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const onNewCustomer = async () => {
    if (pending) {
      return;
    }
    setPending(true);
    setMessage(null);
    const request = register();
    try {
      const { access_token } = await request.unwrap();
      await outcome.signedIn(access_token);
    } catch (error) {
      setMessage(outcome.failed(registerFailure(error as ApiError)));
    } finally {
      request.reset();
      setPending(false);
    }
  };

  return (
    <Card title={t('telegram.onboarding.title')}>
      <p className="text-ink-600">{t('telegram.onboarding.text')}</p>
      <ErrorText messageKey={message} />
      <div className="flex flex-col gap-3">
        <button
          type="button"
          className={primary}
          disabled={pending}
          aria-busy={pending || undefined}
          onClick={() => void onNewCustomer()}
        >
          {pending ? t('auth.pending') : t('telegram.onboarding.newCustomer')}
        </button>
        <p className="rounded-md border border-border bg-cream-50 px-3 py-2 text-sm text-ink-600">
          {t('telegram.onboarding.warning')}
        </p>
        <button type="button" className={secondary} disabled={pending} onClick={onHaveAccount}>
          {t('telegram.onboarding.haveAccount')}
        </button>
      </div>
    </Card>
  );
}

function LinkStep({ onBack }: { onBack: () => void }) {
  const { t } = useTranslation();
  const outcome = useOnboardingOutcome();
  const [link] = useTelegramLinkMutation();
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    resetField,
    setFocus,
    formState: { errors },
  } = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: '', password: '' },
  });

  const onSubmit = handleSubmit(async (values) => {
    if (pending) {
      return;
    }
    setPending(true);
    setMessage(null);
    const request = link(values);
    try {
      const { access_token } = await request.unwrap();
      await outcome.signedIn(access_token);
    } catch (error) {
      const key = outcome.failed(linkFailure(error as ApiError));
      setMessage(key);
      if (key === 'errors.codes.INVALID_CREDENTIALS') {
        resetField('password');
        setFocus('password');
      }
    } finally {
      // Drops the request (and the password in its arguments) from the store.
      request.reset();
      setPending(false);
    }
  });

  return (
    <Card title={t('telegram.onboarding.linkTitle')}>
      <p className="text-ink-600">{t('telegram.onboarding.linkText')}</p>
      <form noValidate onSubmit={onSubmit} className="flex flex-col gap-4">
        <ErrorText messageKey={message} />
        <TextField
          label={t('auth.fields.email')}
          type="email"
          autoComplete="email"
          error={errors.email?.message && t(errors.email.message)}
          {...register('email')}
        />
        <TextField
          label={t('auth.fields.password')}
          type="password"
          autoComplete="current-password"
          error={errors.password?.message && t(errors.password.message)}
          {...register('password')}
        />
        <button
          type="submit"
          className={primary}
          disabled={pending}
          aria-busy={pending || undefined}
        >
          {pending ? t('auth.pending') : t('telegram.onboarding.linkSubmit')}
        </button>
        <button
          type="button"
          className={textButton}
          onClick={() => openExternalLink(siteUrl(FORGOT_PASSWORD_PATH))}
        >
          {t('auth.login.forgot')}
        </button>
        <button type="button" className={textButton} disabled={pending} onClick={onBack}>
          {t('telegram.onboarding.back')}
        </button>
      </form>
    </Card>
  );
}

export function TelegramOnboarding() {
  const [step, setStep] = useState<'choice' | 'link'>('choice');
  return step === 'choice' ? (
    <ChoiceStep onHaveAccount={() => setStep('link')} />
  ) : (
    <LinkStep onBack={() => setStep('choice')} />
  );
}
