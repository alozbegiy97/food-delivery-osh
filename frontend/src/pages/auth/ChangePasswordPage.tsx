import { useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { useNavigate } from 'react-router';

import { useChangePasswordMutation } from '../../features/auth/authApi';
import { selectPasswordChangeRequired } from '../../features/auth/authSlice';
import { AuthCard, FormAlert, SubmitButton } from '../../features/auth/components/AuthCard';
import { useApiErrorText } from '../../features/auth/useApiErrorText';
import { changePasswordSchema, type ChangePasswordValues } from '../../features/auth/validation';
import { TextField } from '../../shared/components/TextField';
import { zodResolver } from '../../shared/lib/zodResolver';

export function ChangePasswordPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const required = useSelector(selectPasswordChangeRequired);
  const [changePassword, { isLoading, error }] = useChangePasswordMutation();
  const errorText = useApiErrorText();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ChangePasswordValues>({
    resolver: zodResolver(changePasswordSchema),
    defaultValues: { current_password: '', new_password: '', confirm: '' },
  });

  const onSubmit = handleSubmit(async (values) => {
    try {
      await changePassword({
        current_password: values.current_password,
        new_password: values.new_password,
      }).unwrap();
      // All sessions were revoked by the server: sign in with the new password.
      navigate('/login?changed=done', { replace: true });
    } catch {
      // Shown below from the mutation state.
    }
  });

  return (
    <AuthCard title={t('auth.change.title')}>
      <form noValidate onSubmit={onSubmit} className="flex flex-col gap-4">
        {required && <FormAlert>{t('auth.change.required')}</FormAlert>}
        {error && <FormAlert>{errorText(error)}</FormAlert>}
        <TextField
          label={t('auth.fields.currentPassword')}
          type="password"
          autoComplete="current-password"
          error={errors.current_password?.message && t(errors.current_password.message)}
          {...register('current_password')}
        />
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
          {isLoading ? t('auth.pending') : t('auth.change.submit')}
        </SubmitButton>
      </form>
    </AuthCard>
  );
}
