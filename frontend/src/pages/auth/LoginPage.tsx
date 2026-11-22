import { useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useSearchParams } from 'react-router';

import { useLoginMutation } from '../../features/auth/authApi';
import { AuthCard, FormAlert, SubmitButton } from '../../features/auth/components/AuthCard';
import { safeReturnTo } from '../../features/auth/paths';
import { useApiErrorText } from '../../features/auth/useApiErrorText';
import { loginSchema, type LoginValues } from '../../features/auth/validation';
import { TextField } from '../../shared/components/TextField';
import { zodResolver } from '../../shared/lib/zodResolver';

export function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [login, { isLoading, error }] = useLoginMutation();
  const errorText = useApiErrorText();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: '', password: '' },
  });

  const onSubmit = handleSubmit(async (values) => {
    try {
      await login(values).unwrap();
      navigate(safeReturnTo(params.get('returnTo')), { replace: true });
    } catch {
      // Shown below from the mutation state.
    }
  });

  return (
    <AuthCard title={t('auth.login.title')}>
      <form noValidate onSubmit={onSubmit} className="flex flex-col gap-4">
        {params.get('reset') === 'done' && (
          <FormAlert tone="success">{t('auth.reset.done')}</FormAlert>
        )}
        {params.get('changed') === 'done' && (
          <FormAlert tone="success">{t('auth.change.done')}</FormAlert>
        )}
        {error && <FormAlert>{errorText(error)}</FormAlert>}
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
        <SubmitButton pending={isLoading}>
          {isLoading ? t('auth.pending') : t('auth.login.submit')}
        </SubmitButton>
        <div className="flex flex-wrap justify-between gap-2 text-sm">
          <Link to="/forgot-password" className="text-accent-800 underline">
            {t('auth.login.forgot')}
          </Link>
          <Link to="/register" className="text-accent-800 underline">
            {t('auth.login.toRegister')}
          </Link>
        </div>
      </form>
    </AuthCard>
  );
}
