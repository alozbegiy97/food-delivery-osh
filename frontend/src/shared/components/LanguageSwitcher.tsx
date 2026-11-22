import { useTranslation } from 'react-i18next';

import { SUPPORTED_LANGUAGES, type Language } from '../i18n/languages';

interface LanguageSwitcherProps {
  // Default (site): switch i18next directly. The Mini App passes a handler
  // that first saves the language in the profile (DEC-152 п. 10).
  onSelect?: (language: Language) => void | Promise<void>;
  disabled?: boolean;
}

export function LanguageSwitcher({ onSelect, disabled = false }: LanguageSwitcherProps = {}) {
  const { t, i18n } = useTranslation();
  const current = i18n.resolvedLanguage ?? i18n.language;
  const select = onSelect ?? ((language: Language) => i18n.changeLanguage(language));

  return (
    <div role="group" aria-label={t('language.label')} className="flex gap-1">
      {SUPPORTED_LANGUAGES.map((language) => {
        const active = language === current;
        return (
          <button
            key={language}
            type="button"
            lang={language}
            aria-pressed={active}
            aria-label={t(`language.names.${language}`)}
            disabled={disabled}
            onClick={() => void select(language)}
            className={[
              'min-h-11 min-w-11 rounded-full px-3 text-sm font-semibold uppercase transition-colors',
              active
                ? 'bg-accent-700 text-white'
                : 'bg-surface text-ink-900 ring-1 ring-border hover:bg-cream-100',
            ].join(' ')}
          >
            {language}
          </button>
        );
      })}
    </div>
  );
}
