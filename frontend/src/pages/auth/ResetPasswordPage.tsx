import { useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useSearchParams } from 'react-router';

import { useResetPasswordMutation } from '../../features/auth/authApi';
import { AuthCard, FormAlert, SubmitButton } from '../../features/auth/components/AuthCard';
import { useApiErrorText } from '../../features/auth/useApiErrorText';
import { resetSchema, type ResetValues } from '../../features/auth/validation';
import { TextField } from '../../shared/components/TextField';
import { zodResolver } from '../../shared/lib/zodResolver';

export function ResetPasswordPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const token = params.get('token') ?? '';
  const [resetPassword, { isLoading, error }] = useResetPasswordMutation();
  const errorText = useApiErrorText();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ResetValues>({
    resolver: zodResolver(resetSchema),
    defaultValues: { new_password: '', confirm: '' },
  });

  const onSubmit = handleSubmit(async (values) => {
    try {
      await resetPassword({ token, new_password: values.new_password }).unwrap();
      navigate('/login?reset=done', { replace: true });
    } catch {
      // Shown below from the mutation state.
    }
  });

  if (!token) {
    return (
      <AuthCard title={t('auth.reset.title')}>
        <FormAlert>{t('errors.codes.INVALID_OR_EXPIRED_TOKEN')}</FormAlert>
        <Link to="/forgot-password" className="mt-4 inline-block text-sm text-accent-800 underline">
          {t('auth.reset.requestNew')}
        </Link>
      </AuthCard>
    );
  }

  return (
    <AuthCard title={t('auth.reset.title')}>
      <form noValidate onSubmit={onSubmit} className="flex flex-col gap-4">
        {error && <FormAlert>{errorText(error)}</FormAlert>}
        <TextField
          label={t('auth.fields.newPassword')}
          type="password"
          autoComplete="new-password"
          hint={t('auth.hints.password')}
          error={errors.new_password?.message && t(errors.new_password.message)}
          {...register('new_password')}
        />
        <TextField
          label={t('auth.fields.confirmPassword')}
          type="password"
          autoComplete="new-password"
          error={errors.confirm?.message && t(errors.confirm.message)}
          {...register('confirm')}
        />
        <SubmitButton pending={isLoading}>
          {isLoading ? t('auth.pending') : t('auth.reset.submit')}
        </SubmitButton>
      </form>
    </AuthCard>
  );
}
