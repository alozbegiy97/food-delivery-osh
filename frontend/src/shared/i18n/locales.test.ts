import { describe, expect, it } from 'vitest';

import { resources } from './index';
import { SUPPORTED_LANGUAGES } from './languages';

function flattenKeys(value: unknown, prefix = ''): string[] {
  if (value === null || typeof value !== 'object') {
    return [prefix];
  }
  return Object.entries(value).flatMap(([key, nested]) =>
    flattenKeys(nested, prefix ? `${prefix}.${key}` : key),
  );
}

describe('locales', () => {
  const reference = flattenKeys(resources.ru.common).sort();

  it.each(SUPPORTED_LANGUAGES)('%s has exactly the same keys as ru', (language) => {
    expect(flattenKeys(resources[language].common).sort()).toEqual(reference);
  });

  it.each(SUPPORTED_LANGUAGES)('%s has no empty strings', (language) => {
    const values = flattenKeys(resources[language].common).map((key) =>
      key
        .split('.')
        .reduce<unknown>(
          (node, part) => (node as Record<string, unknown>)[part],
          resources[language].common,
        ),
    );
    expect(values.every((v) => typeof v === 'string' && v.trim().length > 0)).toBe(true);
  });
});
