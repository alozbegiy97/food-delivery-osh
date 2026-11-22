import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router';

import { useLogoutMutation, useMeQuery } from '../../features/auth/authApi';
import { FormAlert } from '../../features/auth/components/AuthCard';
import { useApiErrorText } from '../../features/auth/useApiErrorText';

/** Minimal account page: proves the protected API works end to end. */
export function AccountPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { data, error, isLoading } = useMeQuery();
  const [logout, { isLoading: loggingOut }] = useLogoutMutation();
  const errorText = useApiErrorText();

  if (isLoading) {
    return <p role="status">{t('auth.checkingSession')}</p>;
  }
  if (error || !data) {
    return <FormAlert>{errorText(error)}</FormAlert>;
  }

  const onLogout = async () => {
    try {
      await logout().unwrap();
    } finally {
      navigate('/', { replace: true });
    }
  };

  return (
    <section className="mx-auto flex w-full max-w-md flex-col gap-4 rounded-[var(--radius-card)] border border-border bg-surface p-6">
      <h1 className="text-2xl font-bold">{t('account.title')}</h1>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
        <dt className="text-ink-600">{t('auth.fields.fullName')}</dt>
        <dd>{data.full_name}</dd>
        <dt className="text-ink-600">{t('auth.fields.email')}</dt>
        <dd>{data.email ?? '—'}</dd>
        <dt className="text-ink-600">{t('account.phone')}</dt>
        <dd>{data.phone ?? '—'}</dd>
        <dt className="text-ink-600">{t('account.roles')}</dt>
        <dd>
          {data.roles
            .map((role) => t(`account.roleNames.${role}`, { defaultValue: role }))
            .join(', ')}
        </dd>
      </dl>
      <div className="flex flex-wrap gap-3">
        <Link to="/change-password" className="text-sm text-accent-800 underline">
          {t('account.changePassword')}
        </Link>
        <button
          type="button"
          onClick={onLogout}
          disabled={loggingOut}
          className="text-sm text-danger-700 underline disabled:opacity-60"
        >
          {t('auth.logout')}
        </button>
      </div>
    </section>
  );
}
