import { useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';

import { useForgotPasswordMutation } from '../../features/auth/authApi';
import { AuthCard, FormAlert, SubmitButton } from '../../features/auth/components/AuthCard';
import { useApiErrorText } from '../../features/auth/useApiErrorText';
import { forgotSchema, type ForgotValues } from '../../features/auth/validation';
import { TextField } from '../../shared/components/TextField';
import { zodResolver } from '../../shared/lib/zodResolver';

export function ForgotPasswordPage() {
  const { t } = useTranslation();
  const [forgot, { isLoading, isSuccess, error }] = useForgotPasswordMutation();
  const errorText = useApiErrorText();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ForgotValues>({ resolver: zodResolver(forgotSchema), defaultValues: { email: '' } });

  const onSubmit = handleSubmit(async (values) => {
    try {
      await forgot(values).unwrap();
    } catch {
      // Shown below from the mutation state.
    }
  });

  return (
    <AuthCard title={t('auth.forgot.title')}>
      {isSuccess ? (
        // The same message for every e-mail (DEC-108).
        <div className="flex flex-col gap-4">
          <FormAlert tone="success">{t('auth.forgot.sent')}</FormAlert>
          <Link to="/login" className="text-sm text-accent-800 underline">
            {t('auth.backToLogin')}
          </Link>
        </div>
      ) : (
        <form noValidate onSubmit={onSubmit} className="flex flex-col gap-4">
          <p className="text-sm text-ink-600">{t('auth.forgot.description')}</p>
          {error && <FormAlert>{errorText(error)}</FormAlert>}
          <TextField
            label={t('auth.fields.email')}
            type="email"
            autoComplete="email"
            error={errors.email?.message && t(errors.email.message)}
            {...register('email')}
          />
          <SubmitButton pending={isLoading}>
            {isLoading ? t('auth.pending') : t('auth.forgot.submit')}
          </SubmitButton>
        </form>
      )}
    </AuthCard>
  );
}
