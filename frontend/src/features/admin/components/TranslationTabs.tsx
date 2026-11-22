import { useId, useState } from 'react';
import type { FieldErrors, UseFormRegisterReturn } from 'react-hook-form';
import { useTranslation } from 'react-i18next';

import type { Language } from '../../../shared/i18n/languages';
import { ADMIN_LANGUAGES, type TranslationsForm } from '../forms';
import { Field } from './AdminUi';

interface TranslationTabsProps {
  // `register` of a form that has a `translations` object (ru/ky/uz).
  register: (name: `translations.${Language}.${'name' | 'description'}`) => UseFormRegisterReturn;
  errors?: FieldErrors<TranslationsForm>;
  withDescription?: boolean;
  nameLabel?: string;
}

/** Name (and description) per language; RU is required (DEC-145). */
export function TranslationTabs({
  register,
  errors,
  withDescription = true,
  nameLabel,
}: TranslationTabsProps) {
  const { t } = useTranslation();
  const uid = useId();
  const [active, setActive] = useState<(typeof ADMIN_LANGUAGES)[number]>('ru');
  const failing = ADMIN_LANGUAGES.filter((language) => errors?.[language]);

  return (
    <div className="flex flex-col gap-3">
      <div role="tablist" aria-label={t('admin.translations.label')} className="flex gap-1">
        {ADMIN_LANGUAGES.map((language) => (
          <button
            key={language}
            type="button"
            role="tab"
            id={`${uid}-tab-${language}`}
            aria-selected={active === language}
            aria-controls={`${uid}-panel-${language}`}
            onClick={() => setActive(language)}
            className={[
              'min-h-10 rounded-full px-4 text-sm font-semibold uppercase',
              active === language ? 'bg-accent-700 text-white' : 'bg-cream-100 text-ink-900',
              failing.includes(language) ? 'ring-2 ring-danger-700' : '',
            ].join(' ')}
          >
            {language}
            {language === 'ru' && <span aria-hidden="true"> *</span>}
          </button>
        ))}
      </div>
      <p className="text-xs text-ink-600">{t('admin.translations.hint')}</p>
      {ADMIN_LANGUAGES.map((language) => (
        <div
          key={language}
          role="tabpanel"
          id={`${uid}-panel-${language}`}
          aria-labelledby={`${uid}-tab-${language}`}
          hidden={active !== language}
          className="flex flex-col gap-3"
        >
          <Field
            label={`${nameLabel ?? t('admin.fields.name')} (${language.toUpperCase()})${language === 'ru' ? ' *' : ''}`}
            error={errors?.[language]?.name?.message ? t(errors[language].name.message) : undefined}
            {...register(`translations.${language}.name`)}
          />
          {withDescription && (
            <div className="flex flex-col gap-1">
              <label htmlFor={`${uid}-desc-${language}`} className="text-sm font-medium">
                {`${t('admin.fields.description')} (${language.toUpperCase()})`}
              </label>
              <textarea
                id={`${uid}-desc-${language}`}
                rows={3}
                className="rounded-lg border border-border bg-surface px-3 py-2"
                {...register(`translations.${language}.description`)}
              />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
