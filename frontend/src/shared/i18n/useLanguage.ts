import { useTranslation } from 'react-i18next';

import { DEFAULT_LANGUAGE, isSupportedLanguage, type Language } from './languages';

/** Current UI language as a supported code (ru/ky/uz). */
export function useLanguage(): Language {
  const { i18n } = useTranslation();
  const current = i18n.resolvedLanguage ?? i18n.language;
  return isSupportedLanguage(current) ? current : DEFAULT_LANGUAGE;
}

// BCP 47 tags for number and date formatting.
export const LOCALE_TAGS: Record<Language, string> = {
  ru: 'ru-RU',
  ky: 'ky-KG',
  uz: 'uz-Latn-UZ',
};
