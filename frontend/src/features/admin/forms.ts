import { z } from 'zod';

import type { TranslationIn, TranslationOut } from '../../shared/types/api';
import type { Language } from '../../shared/i18n/languages';

// Form helpers of the catalog administration. They only shape data for the
// API; all business rules are checked again by the backend.

export const ADMIN_LANGUAGES: Language[] = ['ru', 'ky', 'uz'];

export interface TranslationFields {
  name: string;
  description: string;
}
export type TranslationsForm = Record<Language, TranslationFields>;

const translationFields = z.object({ name: z.string(), description: z.string() });

/** RU name required, KY/UZ optional (DEC-145). */
export function translationsSchema(maxName: number) {
  return z
    .object({ ru: translationFields, ky: translationFields, uz: translationFields })
    .superRefine((value, ctx) => {
      if (!value.ru.name.trim()) {
        ctx.addIssue({
          code: 'custom',
          path: ['ru', 'name'],
          message: 'admin.validation.ruRequired',
        });
      }
      for (const language of ADMIN_LANGUAGES) {
        if ([...value[language].name.trim()].length > maxName) {
          ctx.addIssue({
            code: 'custom',
            path: [language, 'name'],
            message: 'admin.validation.tooLong',
          });
        }
      }
    });
}

export function emptyTranslations(): TranslationsForm {
  return {
    ru: { name: '', description: '' },
    ky: { name: '', description: '' },
    uz: { name: '', description: '' },
  };
}

export function translationsToForm(items: TranslationOut[]): TranslationsForm {
  const form = emptyTranslations();
  for (const item of items) {
    if (item.language_code === 'ru' || item.language_code === 'ky' || item.language_code === 'uz') {
      form[item.language_code] = { name: item.name, description: item.description ?? '' };
    }
  }
  return form;
}

/** Only languages with a name are sent; the array replaces all translations. */
export function translationsToApi(form: TranslationsForm, withDescription = true): TranslationIn[] {
  return ADMIN_LANGUAGES.filter((language) => form[language].name.trim()).map((language) => ({
    language_code: language,
    name: form[language].name.trim(),
    ...(withDescription ? { description: form[language].description.trim() || null } : {}),
  }));
}

export function ruName(items: TranslationOut[], fallback = ''): string {
  return items.find((item) => item.language_code === 'ru')?.name ?? fallback;
}

// Money: a decimal string with up to two fraction digits (never a float).
export const moneyField = z
  .string()
  .trim()
  .regex(/^\d{1,10}([.,]\d{1,2})?$/, 'admin.validation.money')
  .transform((value) => value.replace(',', '.'));

export const sortField = z
  .string()
  .trim()
  .regex(/^-?\d{1,7}$/, 'admin.validation.integer')
  .transform(Number);

export const skuField = z
  .string()
  .trim()
  .min(1, 'validation.required')
  .max(100, 'admin.validation.tooLong')
  .regex(/^[A-Za-z0-9._-]+$/, 'admin.validation.sku');

export const slugField = z
  .string()
  .trim()
  .toLowerCase()
  .refine(
    (value) => value === '' || /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value),
    'admin.validation.slug',
  );
