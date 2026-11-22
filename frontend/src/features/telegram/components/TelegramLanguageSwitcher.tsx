import { useTranslation } from 'react-i18next';

import { LanguageSwitcher } from '../../../shared/components/LanguageSwitcher';
import { useMiniAppSignedIn, useProfileLanguage, useSaveLanguage } from '../useMiniAppLanguage';

/**
 * Compact language switcher of the Mini App layout (decision Q4). It is
 * shown only when signed in, because the choice is stored in the profile
 * (PATCH /users/me), not in the browser.
 */
export function TelegramLanguageSwitcher() {
  const { t } = useTranslation();
  const signedIn = useMiniAppSignedIn();
  useProfileLanguage();
  const { save, saving, failed } = useSaveLanguage();

  if (!signedIn) {
    return null;
  }
  return (
    <div className="flex flex-col items-end gap-1">
      <LanguageSwitcher onSelect={save} disabled={saving} />
      {failed && (
        <p role="alert" className="text-xs text-danger-700">
          {t('telegram.languageSaveFailed')}
        </p>
      )}
    </div>
  );
}
