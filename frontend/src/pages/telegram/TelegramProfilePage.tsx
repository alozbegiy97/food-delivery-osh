import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { AddCredentialsForm } from '../../features/profile/components/AddCredentialsForm';
import { ProfileDetailsForm } from '../../features/profile/components/ProfileDetailsForm';
import { SavedAddressList } from '../../features/profile/components/SavedAddressList';
import { useGetProfileQuery } from '../../features/profile/profileApi';
import { ErrorState } from '../../shared/components/StateViews';
import { isSupportedLanguage } from '../../shared/i18n/languages';
import { formatPhoneInput } from '../../shared/lib/phone';

const BOX = 'flex flex-col gap-4 rounded-card border border-border bg-surface p-5';

/**
 * Profile page of the Mini App `/tg/account` (DEC-160 п. 1): its own page,
 * not a copy of the site's account page. Name, phone, email, the interface
 * language (changed in the header, DEC-160 п. 3) and the saved addresses
 * (DEC-160 п. 4). The name and the phone are edited in an inline form
 * opened by "Изменить" (DEC-160 п. 2); everything else is read only. No
 * links to the site, no sign-in, password or sign-out links.
 */
export function TelegramProfilePage() {
  const { t } = useTranslation();
  const profile = useGetProfileQuery();
  const [editing, setEditing] = useState(false);
  const [saved, setSaved] = useState(false);
  // Outcome of POST /auth/credentials kept by the page (DEC-160 п. 5): once
  // set, the form never comes back and the message stays, whether the next
  // reload of the profile fails (cache still `email: null`) or succeeds
  // (the email appears and the account no longer qualifies for the form).
  const [credentialsNotice, setCredentialsNotice] = useState<'added' | 'alreadySet' | null>(null);
  const editButton = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef(false);

  useEffect(() => {
    if (!editing && returnFocus.current) {
      returnFocus.current = false;
      editButton.current?.focus();
    }
  }, [editing]);

  const openForm = () => {
    setSaved(false);
    setEditing(true);
  };
  const closeForm = (afterSave: boolean) => {
    returnFocus.current = true;
    setSaved(afterSave);
    setEditing(false);
  };
  const heading = (
    <h1 className="text-3xl font-extrabold tracking-tight">{t('telegram.profile.title')}</h1>
  );

  if (profile.isLoading) {
    return (
      <div className="flex flex-col gap-6" aria-busy="true">
        {heading}
        <p role="status" className="text-ink-600">
          {t('telegram.profile.loading')}
        </p>
      </div>
    );
  }
  if (!profile.data) {
    // Only when the profile was never loaded; without it the addresses are
    // not shown either. A failed background reload (e.g. after a language
    // change) keeps the last data, so an open form and its values stay.
    return (
      <div className="flex flex-col gap-6">
        {heading}
        <ErrorState
          title={t('telegram.profile.errorTitle')}
          text={t('telegram.profile.errorText')}
          onRetry={() => void profile.refetch()}
          retrying={profile.isFetching}
        />
      </div>
    );
  }

  const data = profile.data;
  const language = data.preferred_language;
  // Only a Telegram-only account may add an email and a password (DEC-160 п. 5).
  const canAddCredentials = data.email === null && data.has_password === false;
  return (
    <div className="flex flex-col gap-6">
      {heading}

      <section className={BOX} aria-labelledby="profile-details">
        <h2 id="profile-details" className="text-lg font-bold">
          {t('telegram.profile.details')}
        </h2>
        {editing && (
          <ProfileDetailsForm
            profile={data}
            onSaved={() => closeForm(true)}
            onClose={() => closeForm(false)}
          />
        )}
        <dl className="flex flex-col gap-3 text-sm">
          {!editing && (
            <>
              <div className="flex flex-col gap-0.5">
                <dt className="text-ink-600">{t('auth.fields.fullName')}</dt>
                <dd className="font-semibold break-words">{data.full_name}</dd>
              </div>
              <div className="flex flex-col gap-0.5">
                <dt className="text-ink-600">{t('account.phone')}</dt>
                <dd className="font-semibold">
                  {data.phone ? formatPhoneInput(data.phone) : t('telegram.profile.phoneNotSet')}
                </dd>
              </div>
            </>
          )}
          <div className="flex flex-col gap-0.5">
            <dt className="text-ink-600">{t('auth.fields.email')}</dt>
            <dd className="font-semibold [overflow-wrap:anywhere]">
              {data.email ?? t('telegram.profile.emailNotSet')}
            </dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-ink-600">{t('language.label')}</dt>
            <dd className="font-semibold">
              {isSupportedLanguage(language) ? t(`language.names.${language}`) : language}
            </dd>
            <dd className="text-xs text-ink-600">{t('telegram.profile.languageHint')}</dd>
          </div>
        </dl>
        {!editing && (
          <>
            {saved && (
              <p role="status" className="text-sm font-semibold text-success-700">
                {t('telegram.profile.saved')}
              </p>
            )}
            <button
              ref={editButton}
              type="button"
              onClick={openForm}
              className="min-h-11 self-start rounded-md border border-border px-4 py-2 font-semibold text-ink-900 focus:outline-2 focus:outline-offset-2 focus:outline-accent-600"
            >
              {t('telegram.profile.edit')}
            </button>
          </>
        )}
      </section>

      {(credentialsNotice !== null || canAddCredentials) && (
        <section className={BOX} aria-labelledby="profile-credentials">
          <h2 id="profile-credentials" className="text-lg font-bold">
            {t('telegram.profile.credentials.title')}
          </h2>
          {credentialsNotice === 'added' && (
            <p role="status" className="text-sm font-semibold text-success-700">
              {t('telegram.profile.credentials.added')}
            </p>
          )}
          {credentialsNotice === 'alreadySet' && (
            <p role="status" className="text-sm font-semibold text-ink-900">
              {t('errors.codes.CREDENTIALS_ALREADY_SET')}
            </p>
          )}
          {credentialsNotice === null && (
            <>
              <p className="text-sm text-ink-600">{t('telegram.profile.credentials.text')}</p>
              <AddCredentialsForm
                onAdded={() => setCredentialsNotice('added')}
                onAlreadySet={() => setCredentialsNotice('alreadySet')}
              />
            </>
          )}
        </section>
      )}

      <section className={BOX} aria-labelledby="profile-addresses">
        <h2 id="profile-addresses" className="text-lg font-bold">
          {t('telegram.profile.addresses.title')}
        </h2>
        <SavedAddressList />
      </section>
    </div>
  );
}
