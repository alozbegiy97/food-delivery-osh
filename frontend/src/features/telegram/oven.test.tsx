// MA-4.6-C: the "Печь" look of the Mini App — the compact oven on /tg/menu,
// the bottom tabs and the Telegram theme (cream-100, plate tokens).
import { act, render, screen, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { AppProviders } from '../../app/providers/AppProviders';
import { miniAppRoutes } from '../../app/router/miniAppRoutes';
import { routes } from '../../app/router/routes';
import { makeStore } from '../../app/store/store';
import i18n from '../../shared/i18n';
import {
  CATEGORIES,
  MARGHERITA_SUMMARY,
  productList,
  RESTAURANT_CLOSED,
} from '../../test/catalogFixtures';
import { mockFetchRoutes } from '../../test/fetchRoutes';
import { BASE } from '../../test/orderFixtures';
import { ANONYMOUS, apiError, jsonResponse } from '../../test/renderWithProviders';
import {
  installTelegram,
  openAt,
  uninstallTelegram,
  type FakeTelegram,
} from '../../test/telegramMock';
import { contrastRatio, DARK_OVERRIDES, MIN_CONTRAST, themeVariables } from './theme';

const PROFILE =
  (language = 'ru') =>
  () =>
    jsonResponse({
      id: 'u1',
      email: null,
      full_name: 'Айбек',
      phone: null,
      preferred_language: language,
      roles: ['customer'],
      must_change_password: false,
      has_password: false,
    });

const API = {
  ...BASE,
  'POST /api/v1/auth/telegram/webapp': () =>
    jsonResponse({ access_token: 'mini', token_type: 'bearer', expires_in: 900 }),
  'GET /api/v1/users/me': PROFILE(),
  'GET /api/v1/catalog/categories': () => jsonResponse({ items: CATEGORIES }),
  'GET /api/v1/catalog/products': () => jsonResponse(productList([MARGHERITA_SUMMARY])),
};

let fake: FakeTelegram;

beforeEach(() => {
  fake = installTelegram();
});

afterEach(() => {
  uninstallTelegram();
  document.documentElement.removeAttribute('style');
  openAt('/');
});

function launch(path: string) {
  openAt(path);
  const router = createMemoryRouter(miniAppRoutes, { initialEntries: [path], basename: '/tg' });
  render(
    <AppProviders store={makeStore()}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return router;
}

describe('compact oven on /tg/menu', () => {
  it('shows the graphite oven with the pizza and the status from the API', async () => {
    mockFetchRoutes(API);
    launch('/tg/menu');
    const oven = await screen.findByTestId('mini-oven');
    expect(oven).toHaveClass('mini-oven', 'min-h-[7.5rem]');
    const art = oven.querySelector('svg[data-dish-art]');
    expect(art).toHaveAttribute('data-dish-art', 'pizza');
    expect(art).toHaveAttribute('aria-hidden', 'true');
    // The light drawing: no filters on a phone.
    expect(oven.querySelector('filter')).toBeNull();
    expect(await within(oven).findByText('Открыто')).toBeInTheDocument();
    expect(within(oven).getByText('Горячая пицца и любимые блюда Оша')).toBeInTheDocument();
    // Not a second h1: the page title stays "Меню", compact in the Mini App.
    expect(within(oven).queryByRole('heading')).toBeNull();
    const title = screen.getByRole('heading', { level: 1, name: 'Меню' });
    expect(title).toHaveClass('text-2xl');
    // Search and categories follow right after it.
    expect(screen.getByRole('searchbox', { name: 'Поиск по меню' })).toBeInTheDocument();
    expect(await screen.findByRole('navigation', { name: 'Категории меню' })).toBeInTheDocument();
    expect(oven.compareDocumentPosition(title) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('a closed restaurant: the status says so with the opening time', async () => {
    mockFetchRoutes({ ...API, 'GET /api/v1/restaurant': () => jsonResponse(RESTAURANT_CLOSED) });
    launch('/tg/menu');
    const oven = await screen.findByTestId('mini-oven');
    expect(await within(oven).findByText('Закрыто')).toBeInTheDocument();
    expect(within(oven).getByText(/откроемся/)).toBeInTheDocument();
  });

  it('without restaurant data there is no invented status', async () => {
    mockFetchRoutes({
      ...API,
      'GET /api/v1/restaurant': () => apiError('INTERNAL_ERROR', 500),
    });
    launch('/tg/menu');
    const oven = await screen.findByTestId('mini-oven');
    await screen.findByRole('heading', { name: MARGHERITA_SUMMARY.name });
    expect(within(oven).queryByText('Открыто')).toBeNull();
    expect(within(oven).queryByText('Закрыто')).toBeNull();
    expect(within(oven).getByText('Горячая пицца и любимые блюда Оша')).toBeInTheDocument();
  });

  it.each([
    ['ky', 'Ысык пицца жана Оштун сүйүктүү тамактары'],
    ['uz', 'Issiq pitsa va Oʻshning sevimli taomlari'],
  ])('is translated in %s (the language of the profile)', async (language, title) => {
    mockFetchRoutes({ ...API, 'GET /api/v1/users/me': PROFILE(language) });
    launch('/tg/menu');
    const oven = await screen.findByTestId('mini-oven');
    expect(await within(oven).findByText(title)).toBeInTheDocument();
    await act(() => i18n.changeLanguage('ru'));
  });

  it('is only on the menu: not in the cart, not on the site', async () => {
    mockFetchRoutes(API);
    launch('/tg/cart');
    await screen.findByRole('navigation', { name: 'Разделы Mini App' });
    expect(screen.queryByTestId('mini-oven')).toBeNull();
  });

  it('the site menu has no oven and keeps the large title', async () => {
    uninstallTelegram();
    mockFetchRoutes(API);
    openAt('/menu');
    const router = createMemoryRouter(routes, { initialEntries: ['/menu'] });
    render(
      <AppProviders store={makeStore({ auth: ANONYMOUS })}>
        <RouterProvider router={router} />
      </AppProviders>,
    );
    const title = await screen.findByRole('heading', { level: 1, name: 'Меню' });
    expect(title).not.toHaveClass('text-2xl');
    expect(screen.queryByTestId('mini-oven')).toBeNull();
    fake = installTelegram();
  });
});

describe('bottom tabs', () => {
  it('mark the current tab clearly and keep names, sizes and icons hidden', async () => {
    mockFetchRoutes(API);
    launch('/tg/menu');
    const nav = await screen.findByRole('navigation', { name: 'Разделы Mini App' });
    const tabs = within(nav).getAllByRole('link');
    expect(tabs).toHaveLength(4);
    const menu = within(nav).getByRole('link', { name: 'Меню' });
    expect(menu).toHaveAttribute('aria-current', 'page');
    expect(menu).toHaveClass('text-accent-800', 'font-bold');
    for (const link of tabs) {
      expect(link).toHaveClass('min-h-12');
      const icon = link.querySelector('svg');
      expect(icon).toHaveAttribute('aria-hidden', 'true');
      // The pill behind the icon is tinted only on the current tab.
      expect(icon?.parentElement).toHaveClass('group-aria-[current=page]:bg-accent-50');
    }
    const orders = within(nav).getByRole('link', { name: 'Заказы' });
    expect(orders).not.toHaveAttribute('aria-current');
    expect(orders).toHaveClass('text-ink-600', 'font-semibold');
    expect(await within(nav).findByRole('link', { name: /^Корзина, товаров: \d+$/ })).toBeVisible();
  });
});

describe('Telegram theme (MA-4.6-C)', () => {
  const LIGHT = {
    bg_color: '#ffffff',
    text_color: '#000000',
    hint_color: '#707579',
    secondary_bg_color: '#f4f4f5',
    section_bg_color: '#ffffff',
  };
  const DARK = {
    bg_color: '#17212b',
    text_color: '#f5f5f5',
    hint_color: '#aab6c3',
    secondary_bg_color: '#232e3c',
    section_bg_color: '#17212b',
  };

  it.each([
    ['missing', { bg_color: '#17212b', text_color: '#f5f5f5', section_bg_color: '#232e3c' }],
    ['unreadable', { ...DARK, secondary_bg_color: '#f5f5f5' }],
  ])('cream-100 falls back to the surface when the secondary colour is %s', (_, params) => {
    const vars = themeVariables(params);
    expect(vars['--color-cream-100']).toBe(vars['--color-surface']);
    expect(contrastRatio(params.text_color, vars['--color-cream-100'])).toBeGreaterThanOrEqual(
      MIN_CONTRAST,
    );
  });

  it('a readable secondary colour is still used for cream-100', () => {
    expect(themeVariables(LIGHT)['--color-cream-100']).toBe('#f4f4f5');
    expect(themeVariables(DARK)['--color-cream-100']).toBe('#232e3c');
  });

  it('dark themes darken the dish plate; light themes keep the brand plate', () => {
    const dark = themeVariables(DARK);
    expect(dark['--color-plate']).toBe(DARK_OVERRIDES['--color-plate']);
    expect(dark['--color-plate-hi']).toBe(DARK_OVERRIDES['--color-plate-hi']);
    const light = themeVariables(LIGHT);
    expect(light['--color-plate']).toBeUndefined();
    expect(light['--color-plate-hi']).toBeUndefined();
  });

  it('applies the dark theme to the open Mini App, with the oven still in place', async () => {
    mockFetchRoutes(API);
    launch('/tg/menu');
    await screen.findByTestId('mini-oven');
    act(() => {
      fake.setTheme('dark', DARK);
      fake.emit('themeChanged');
    });
    const root = getComputedStyle(document.documentElement);
    expect(root.getPropertyValue('--color-cream-50')).toBe('#17212b');
    expect(root.getPropertyValue('--color-plate')).toBe(DARK_OVERRIDES['--color-plate']);
    expect(root.getPropertyValue('--color-cream-100')).toBe('#232e3c');
  });
});
