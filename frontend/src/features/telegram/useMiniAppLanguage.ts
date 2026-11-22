import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import { isSupportedLanguage, type Language } from '../../shared/i18n/languages';
import { selectSessionStatus } from '../auth/authSlice';
import { useGetProfileQuery, useUpdateProfileMutation } from '../profile/profileApi';
import { selectTelegramPhase } from './telegramSlice';

// Language of the Mini App (DEC-152 п. 10, decisions Q3/Q4): Russian until
// the profile is loaded, then `preferred_language` from GET /users/me; a
// change is saved with PATCH /users/me first and applied only after the
// backend accepted it. The site's localStorage is never used (see i18n).

export function useMiniAppSignedIn(): boolean {
  const phase = useSelector(selectTelegramPhase);
  const status = useSelector(selectSessionStatus);
  return phase === 'ready' && status === 'authenticated';
}

/** Applies the profile language once the Mini App is signed in. */
export function useProfileLanguage(): void {
  const { i18n } = useTranslation();
  const signedIn = useMiniAppSignedIn();
  const { data } = useGetProfileQuery(undefined, { skip: !signedIn });
  const preferred = data?.preferred_language;

  useEffect(() => {
    if (isSupportedLanguage(preferred) && i18n.language !== preferred) {
      void i18n.changeLanguage(preferred);
    }
  }, [i18n, preferred]);
}

/** Saves a new language in the profile, then switches the UI. */
export function useSaveLanguage() {
  const { i18n } = useTranslation();
  const [updateProfile, { isLoading }] = useUpdateProfileMutation();
  const [failed, setFailed] = useState(false);

  const save = async (language: Language) => {
    if (language === i18n.language) {
      return;
    }
    setFailed(false);
    try {
      await updateProfile({ preferred_language: language }).unwrap();
    } catch {
      setFailed(true); // the UI keeps the current language
      return;
    }
    await i18n.changeLanguage(language);
  };

  return { save, saving: isLoading, failed };
}
