import { act, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import i18n from '../../../shared/i18n';
import { RESTAURANT_CLOSED, RESTAURANT_OPEN } from '../../../test/catalogFixtures';
import { renderWithProviders } from '../../../test/renderWithProviders';
import { OpenStatusBadge } from './RestaurantInfo';

// MA-4.6-FINAL-QUALITY: the weekday of "opens …" comes from our translations
// (browsers lack Uzbek and partly Kyrgyz weekday names: "Mon 10:00").
// RESTAURANT_CLOSED opens on Thursday 2026-11-12 10:00 in Asia/Bishkek.

afterEach(async () => {
  await act(() => i18n.changeLanguage('ru'));
});

async function badgeText(language: string, restaurant = RESTAURANT_CLOSED): Promise<string> {
  await act(() => i18n.changeLanguage(language));
  const { container } = renderWithProviders(<OpenStatusBadge restaurant={restaurant} />);
  return (container.textContent ?? '').replace(/\s+/g, ' ').trim();
}

describe('OpenStatusBadge: the opening day in every language', () => {
  it.each([
    ['ru', 'Закрыто', 'откроемся четверг 10:00'],
    ['ky', 'Жабык', 'ачылабыз: бейшемби 10:00'],
    ['uz', 'Yopiq', 'ochilamiz: payshanba 10:00'],
  ])('%s: "%s · %s"', async (language, status, opens) => {
    const text = await badgeText(language);
    expect(text).toContain(status);
    expect(text).toContain(opens);
    // No English or Russian fallback from the browser.
    expect(text).not.toMatch(/\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b/);
    if (language !== 'ru') {
      expect(text).not.toMatch(/четверг|воскресенье/);
    }
  });

  it('takes the weekday in the restaurant time zone, not in UTC', async () => {
    // Sunday 19:30 UTC is already Monday 01:30 in Bishkek (UTC+6).
    const late = { ...RESTAURANT_CLOSED, next_opening_at: '2026-11-15T19:30:00Z' };
    expect(await badgeText('ru', late)).toContain('откроемся понедельник 01:30');
    expect(await badgeText('uz', late)).toContain('ochilamiz: dushanba 01:30');
  });

  it('an open restaurant shows no opening time', async () => {
    const text = await badgeText('uz', RESTAURANT_OPEN);
    expect(text).toBe('Ochiq');
    expect(screen.queryByText(/ochilamiz/)).toBeNull();
  });
});
