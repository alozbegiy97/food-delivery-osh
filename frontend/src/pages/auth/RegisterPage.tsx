import { Controller, useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router';

import { useRegisterMutation } from '../../features/auth/authApi';
import { AuthCard, FormAlert, SubmitButton } from '../../features/auth/components/AuthCard';
import { DEFAULT_AFTER_LOGIN } from '../../features/auth/paths';
import { useApiErrorText } from '../../features/auth/useApiErrorText';
import { registerSchema, type RegisterValues } from '../../features/auth/validation';
import { TextField } from '../../shared/components/TextField';
import { isSupportedLanguage } from '../../shared/i18n/languages';
import { formatPhoneInput } from '../../shared/lib/phone';
import { zodResolver } from '../../shared/lib/zodResolver';

export function RegisterPage() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const [registerUser, { isLoading, error }] = useRegisterMutation();
  const errorText = useApiErrorText();
  const {
    register,
    control,
    handleSubmit,
    formState: { errors },
  } = useForm<RegisterValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: { email: '', full_name: '', phone: '', password: '' },
  });

  const onSubmit = handleSubmit(async (values) => {
    const language = isSupportedLanguage(i18n.language) ? i18n.language : 'ru';
    try {
      await registerUser({
        email: values.email,
        full_name: values.full_name,
        password: values.password,
        phone: values.phone || null,
        // The current interface language becomes the account language (DEC-141).
        preferred_language: language,
      }).unwrap();
      navigate(DEFAULT_AFTER_LOGIN, { replace: true });
    } catch {
      // Shown below from the mutation state.
    }
  });

  const fieldError = (message?: string) => (message ? t(message) : undefined);

  return (
    <AuthCard title={t('auth.register.title')}>
      <form noValidate onSubmit={onSubmit} className="flex flex-col gap-4">
        {error && <FormAlert>{errorText(error)}</FormAlert>}
        <TextField
          label={t('auth.fields.fullName')}
          autoComplete="name"
          error={fieldError(errors.full_name?.message)}
          {...register('full_name')}
        />
        <TextField
          label={t('auth.fields.email')}
          type="email"
          autoComplete="email"
          error={fieldError(errors.email?.message)}
          {...register('email')}
        />
        <Controller
          control={control}
          name="phone"
          render={({ field }) => (
            <TextField
              label={t('auth.fields.phoneOptional')}
              type="tel"
              inputMode="tel"
              autoComplete="tel"
              placeholder="+996 700 12 34 56"
              hint={t('auth.hints.phone')}
              error={fieldError(errors.phone?.message)}
              name={field.name}
              ref={field.ref}
              value={field.value}
              onBlur={field.onBlur}
              onChange={(event) => field.onChange(formatPhoneInput(event.target.value))}
            />
          )}
        />
        <TextField
          label={t('auth.fields.password')}
          type="password"
          autoComplete="new-password"
          hint={t('auth.hints.password')}
          error={fieldError(errors.password?.message)}
          {...register('password')}
        />
        <SubmitButton pending={isLoading}>
          {isLoading ? t('auth.pending') : t('auth.register.submit')}
        </SubmitButton>
        <p className="text-sm">
          <Link to="/login" className="text-accent-800 underline">
            {t('auth.register.toLogin')}
          </Link>
        </p>
      </form>
    </AuthCard>
  );
}
