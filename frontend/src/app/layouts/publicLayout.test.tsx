import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { describe, expect, it } from 'vitest';

import i18n from '../../shared/i18n';
import {
  CATEGORIES,
  MARGHERITA_SUMMARY,
  productList,
  RESTAURANT_CLOSED,
  RESTAURANT_OPEN,
} from '../../test/catalogFixtures';
import { mockFetchRoutes } from '../../test/fetchRoutes';
import { ME } from '../../test/orderFixtures';
import { ANONYMOUS, apiError, jsonResponse } from '../../test/renderWithProviders';
import type { AuthState } from '../../features/auth/authSlice';
import { AppProviders } from '../providers/AppProviders';
import { routes } from '../router/routes';
import { makeStore } from '../store/store';
import { isStaffPath } from './staffPath';

// MA-4.6-A2: the "Печь" header, home hero and footer of the public site.

const SIGNED_IN: AuthState = {
  accessToken: 'a',
  status: 'authenticated',
  passwordChangeRequired: false,
};

const ROUTES = {
  'GET /api/v1/catalog/categories': () => jsonResponse({ items: CATEGORIES }),
  'GET /api/v1/restaurant': () => jsonResponse(RESTAURANT_OPEN),
  'GET /api/v1/catalog/products': () => jsonResponse(productList([MARGHERITA_SUMMARY])),
};

function renderAt(path: string, auth: AuthState = ANONYMOUS) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <AppProviders store={makeStore({ auth })}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return router;
}

function publicHeader(): HTMLElement {
  const header = document.querySelector<HTMLElement>('header[data-header="public"]');
  if (!header) {
    throw new Error('no public header');
  }
  return header;
}

describe('isStaffPath', () => {
  it.each([
    '/admin',
    '/admin/',
    '/admin/kitchen',
    '/admin/orders/1',
    '/courier',
    '/courier/history',
  ])('%s is a staff area', (path) => expect(isStaffPath(path)).toBe(true));

  it.each(['/', '/menu', '/menu/p-1', '/cart', '/administrator', '/couriers', '/x/admin', ''])(
    '%s is public',
    (path) => expect(isStaffPath(path)).toBe(false),
  );
});

describe('public header', () => {
  it('shows the oven mark and the full restaurant name, never cut with an ellipsis', async () => {
    mockFetchRoutes(ROUTES);
    renderAt('/');
    await screen.findByRole('heading', { level: 1 });
    const header = publicHeader();
    const home = within(header).getAllByRole('link', { name: 'Доставка еды — Ош' })[0];
    expect(home).toHaveAttribute('href', '/');
    expect(home.querySelector('svg[viewBox="0 0 30 34"]')).toHaveAttribute('aria-hidden', 'true');
    const name = within(header).getByTestId('site-name');
    expect(name).toHaveTextContent('Доставка еды — Ош');
    expect(name).toHaveClass('line-clamp-2');
    expect(name.className).not.toMatch(/\btruncate\b|text-ellipsis|whitespace-nowrap/);
  });

  it('keeps the navigation, the language switch and a 44 px menu button', async () => {
    mockFetchRoutes(ROUTES);
    const router = renderAt('/');
    await screen.findByRole('heading', { level: 1 });
    const header = publicHeader();

    const nav = within(header).getByRole('navigation', { name: 'Основная навигация' });
    expect(within(nav).getByRole('link', { name: 'Главная' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    for (const link of within(nav).getAllByRole('link')) {
      expect(link).toHaveClass('min-h-11');
    }

    const toggle = within(header).getByRole('button', { name: 'Открыть меню' });
    expect(toggle).toHaveClass('h-11', 'w-11');
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(toggle).toHaveAccessibleName('Закрыть меню');
    const menu = header.querySelector('#mobile-menu') as HTMLElement;
    expect(menu).toBeInTheDocument();

    // The language switch still works from the mobile menu.
    const ky = within(menu).getByRole('button', { name: 'Кыргызча' });
    expect(ky).toHaveClass('min-h-11', 'min-w-11');
    fireEvent.click(ky);
    expect(
      await screen.findByRole('heading', {
        level: 1,
        name: 'Ысык пицца жана Оштун сүйүктүү тамактары',
      }),
    ).toBeInTheDocument();
    await act(() => i18n.changeLanguage('ru'));

    // The menu closes by itself after navigation.
    fireEvent.click(within(menu).getByRole('link', { name: 'Меню' }));
    expect(router.state.location.pathname).toBe('/menu');
    expect(header.querySelector('#mobile-menu')).toBeNull();
  });

  it('gives a customer a compact 44 px cart button on phones with the same name', async () => {
    mockFetchRoutes({
      ...ROUTES,
      'GET /api/v1/auth/me': () => jsonResponse(ME),
      'GET /api/v1/cart': () =>
        jsonResponse({
          items: [],
          items_count: 3,
          subtotal: '0.00',
          currency: 'KGS',
          has_issues: false,
          max_line_quantity: 99,
          max_lines: 50,
        }),
    });
    renderAt('/', SIGNED_IN);
    const carts = await within(publicHeader()).findAllByRole('link', {
      name: 'Корзина, товаров: 3',
    });
    expect(carts).toHaveLength(2);
    const compact = carts.find((link) => link.className.includes('w-11'));
    expect(compact).toHaveClass('h-11', 'w-11');
    expect(compact).not.toHaveTextContent('Корзина');
    expect(compact).toHaveAttribute('href', '/cart');
  });
});

describe('home hero ("Печь")', () => {
  it('shows the oven with the neutral pizza, the open status and the menu button', async () => {
    mockFetchRoutes(ROUTES);
    renderAt('/');
    const hero = (
      await screen.findByRole('heading', { level: 1, name: 'Горячая пицца и любимые блюда Оша' })
    ).closest('section') as HTMLElement;
    expect(hero).toHaveAttribute('aria-labelledby', 'hero-title');

    const art = within(hero).getByTestId('oven').querySelector('svg[data-dish-art]');
    expect(art).toHaveAttribute('data-dish-art', 'pizza');
    expect(art).toHaveAttribute('aria-hidden', 'true');

    expect(await within(hero).findByText('Открыто')).toBeInTheDocument();
    expect(within(hero).getByRole('link', { name: 'Посмотреть меню' })).toHaveAttribute(
      'href',
      '/menu',
    );
    // Services from the restaurant flags, next to the button on wide screens.
    expect(within(hero).getByText('Доставка по Ошу')).toBeInTheDocument();
    expect(within(hero).getByText('Самовывоз')).toBeInTheDocument();
  });

  it('keeps the closed notice and hides services the restaurant does not offer', async () => {
    mockFetchRoutes({
      ...ROUTES,
      'GET /api/v1/restaurant': () =>
        jsonResponse({ ...RESTAURANT_CLOSED, delivery_enabled: false }),
    });
    renderAt('/');
    expect(
      await screen.findByRole('heading', { name: 'Сейчас ресторан закрыт' }),
    ).toBeInTheDocument();
    const hero = screen.getByRole('heading', { level: 1 }).closest('section') as HTMLElement;
    expect(within(hero).getByText('Закрыто')).toBeInTheDocument();
    expect(within(hero).queryByText('Доставка по Ошу')).toBeNull();
    expect(screen.queryByText('Доставка по Ошу')).toBeNull();
  });

  it('shows categories on plates: the drawing without a photo', async () => {
    mockFetchRoutes(ROUTES);
    renderAt('/');
    const categories = await screen.findByRole('region', { name: 'Категории' });
    const pizza = await within(categories).findByRole('link', { name: 'Пицца' });
    expect(pizza.querySelector('[data-dish-plate]')).toHaveAttribute('data-dish-plate', 'pizza');
    const burgers = within(categories).getByRole('link', { name: 'Бургеры' });
    expect(burgers.querySelector('[data-dish-plate]')).toHaveAttribute('data-dish-plate', 'burger');
  });

  it('prefers a real category photo over the drawing', async () => {
    mockFetchRoutes({
      ...ROUTES,
      'GET /api/v1/catalog/categories': () =>
        jsonResponse({
          items: CATEGORIES.map((category) =>
            category.slug === 'pizza'
              ? { ...category, image_url: '/media/categories/pizza.webp' }
              : category,
          ),
        }),
    });
    renderAt('/');
    const categories = await screen.findByRole('region', { name: 'Категории' });
    const plate = (await within(categories).findByRole('link', { name: 'Пицца' })).querySelector(
      '[data-dish-plate]',
    ) as HTMLElement;
    expect(plate).toHaveAttribute('data-dish-plate', 'photo');
    expect(plate.querySelector('img')).toHaveAttribute('src', '/media/categories/pizza.webp');
    expect(plate.querySelector('svg[data-dish-art]')).toBeNull();
  });
});

describe('public footer', () => {
  it('is graphite and shows the restaurant data from the API', async () => {
    mockFetchRoutes(ROUTES);
    renderAt('/menu');
    const footer = await screen.findByRole('contentinfo');
    expect(footer).toHaveAttribute('data-footer', 'public');
    expect(footer).toHaveClass('on-scrim');
    expect(await within(footer).findByText('Demo Restaurant — Osh')).toBeInTheDocument();
    expect(within(footer).getByText('+996000000000')).toBeInTheDocument();
    const nav = within(footer).getByRole('navigation', { name: 'Навигация в подвале' });
    expect(within(nav).getByRole('link', { name: 'Меню' })).toHaveAttribute('href', '/menu');
  });

  it('says when the restaurant data is unavailable', async () => {
    mockFetchRoutes({
      ...ROUTES,
      'GET /api/v1/restaurant': () => apiError('INTERNAL_ERROR', 500),
    });
    renderAt('/menu');
    const footer = await screen.findByRole('contentinfo');
    expect(
      await within(footer).findByText('Информация о ресторане временно недоступна.'),
    ).toBeInTheDocument();
    expect(within(footer).getByText('Доставка еды — Ош')).toBeInTheDocument();
  });
});

describe('staff areas keep the previous header and footer', () => {
  it.each(['/admin', '/admin/kitchen', '/courier'])('%s', async (path) => {
    mockFetchRoutes(ROUTES);
    renderAt(path, SIGNED_IN);
    const header = await screen.findByRole('banner');
    expect(header).not.toHaveAttribute('data-header');
    expect(header).toHaveClass('border-b', 'bg-surface/95');
    expect(header.querySelector('svg[viewBox="0 0 32 32"]')).toBeInTheDocument();
    expect(header.querySelector('svg[viewBox="0 0 30 34"]')).toBeNull();
    const footer = screen.getByRole('contentinfo');
    expect(footer).not.toHaveAttribute('data-footer');
    expect(footer).not.toHaveClass('on-scrim');
    expect(footer).toHaveClass('bg-surface');
  });
});
