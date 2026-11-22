import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import { isMiniAppLocation } from '../lib/miniAppMode';
import {
  DEFAULT_LANGUAGE,
  isSupportedLanguage,
  SUPPORTED_LANGUAGES,
  type Language,
} from './languages';
import ky from './locales/ky/common.json';
import ru from './locales/ru/common.json';
import uz from './locales/uz/common.json';

const STORAGE_KEY = 'ui-language';

// Browser storage is only a per-viewer convenience and may be unavailable
// (private mode, blocked storage), so every access is guarded.
// The Telegram Mini App neither reads nor writes the site's stored language
// (DEC-152 п. 10): it starts in Russian and then follows the profile.
function readStoredLanguage(): Language {
  if (isMiniAppLocation()) {
    return DEFAULT_LANGUAGE;
  }
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return isSupportedLanguage(stored) ? stored : DEFAULT_LANGUAGE;
  } catch {
    return DEFAULT_LANGUAGE;
  }
}

function storeLanguage(language: string): void {
  if (isMiniAppLocation()) {
    return;
  }
  try {
    window.localStorage.setItem(STORAGE_KEY, language);
  } catch {
    // Ignore: the language simply is not remembered.
  }
}

export const resources = {
  ru: { common: ru },
  ky: { common: ky },
  uz: { common: uz },
} as const;

i18n.on('languageChanged', (language) => {
  document.documentElement.lang = language;
  document.title = i18n.t('app.name');
  storeLanguage(language);
});

void i18n.use(initReactI18next).init({
  resources,
  lng: readStoredLanguage(),
  fallbackLng: DEFAULT_LANGUAGE,
  supportedLngs: [...SUPPORTED_LANGUAGES],
  defaultNS: 'common',
  ns: ['common'],
  interpolation: { escapeValue: false },
  // Resources are bundled, so initialise synchronously (no flash of keys).
  initAsync: false,
});

export default i18n;
