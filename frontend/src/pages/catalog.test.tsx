import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { describe, expect, it } from 'vitest';

import { AppProviders } from '../app/providers/AppProviders';
import { routes } from '../app/router/routes';
import { makeStore } from '../app/store/store';
import i18n from '../shared/i18n';
import {
  BURGER,
  BURGER_SUMMARY,
  CATEGORIES,
  MARGHERITA,
  MARGHERITA_SUMMARY,
  PEPPERONI_SUMMARY,
  productList,
  RESTAURANT_CLOSED,
  RESTAURANT_OPEN,
  SHAWARMA,
  SOLD_OUT_SUMMARY,
} from '../test/catalogFixtures';
import { mockFetchRoutes, type RecordedRequest } from '../test/fetchRoutes';
import { ANONYMOUS, apiError, jsonResponse } from '../test/renderWithProviders';

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <AppProviders store={makeStore({ auth: ANONYMOUS })}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return router;
}

function productQueries(calls: RecordedRequest[]) {
  return calls.filter((c) => c.path === '/api/v1/catalog/products').map((c) => c.url);
}

const BASE_ROUTES = {
  'GET /api/v1/catalog/categories': () => jsonResponse({ items: CATEGORIES }),
  'GET /api/v1/restaurant': () => jsonResponse(RESTAURANT_OPEN),
};

describe('menu page', () => {
  it('shows real categories and products from the API', async () => {
    const { calls } = mockFetchRoutes({
      ...BASE_ROUTES,
      'GET /api/v1/catalog/products': () =>
        jsonResponse(productList([MARGHERITA_SUMMARY, BURGER_SUMMARY, SOLD_OUT_SUMMARY])),
    });
    renderAt('/menu');

    const grid = await screen.findByRole('list', { name: 'Блюда' });
    expect(within(grid).getByRole('heading', { name: 'Маргарита' })).toBeInTheDocument();
    expect(within(grid).getByText('от 550 сом')).toBeInTheDocument();
    expect(within(grid).getAllByText('Нет в наличии').length).toBeGreaterThan(0);
    expect(within(grid).getByRole('link', { name: /Маргарита/ })).toHaveAttribute(
      'href',
      '/menu/p-margherita',
    );
    // MA-4.6.2b: the menu uses the catalog cards (rows on phones, tiles from 640 px).
    const menuCard = within(grid).getByRole('link', { name: /Маргарита/ });
    expect(menuCard).toHaveAccessibleName('Маргарита от 550 сом');
    expect(menuCard).toHaveClass('sm:flex-col');
    expect(grid).toHaveClass('sm:gap-x-6');
    expect(screen.getByText('Найдено блюд: 3')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Бургеры' })).toBeInTheDocument();

    const url = new URL(productQueries(calls)[0]);
    expect(url.searchParams.get('language')).toBe('ru');
    expect(url.searchParams.get('page')).toBe('1');
  });

  it('filters by category and searches, keeping both in the URL', async () => {
    const { calls } = mockFetchRoutes({
      ...BASE_ROUTES,
      'GET /api/v1/catalog/products': ({ url }) => {
        const params = new URL(url).searchParams;
        if (params.get('category_id') === 'cat-pizza') {
          return jsonResponse(productList([MARGHERITA_SUMMARY, PEPPERONI_SUMMARY]));
        }
        return jsonResponse(productList([MARGHERITA_SUMMARY, BURGER_SUMMARY]));
      },
    });
    const router = renderAt('/menu');
    await screen.findByRole('heading', { name: 'Классический бургер' });

    fireEvent.click(screen.getByRole('button', { name: 'Пицца' }));
    expect(await screen.findByRole('heading', { name: 'Пепперони (говяжья)' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'Пицца' })).toBeInTheDocument();
    expect(router.state.location.search).toBe('?category=cat-pizza');

    // The search box: a 52 px pill with a visible label for assistive tech.
    expect(screen.getByRole('searchbox', { name: 'Поиск по меню' })).toHaveClass(
      'min-h-13',
      'rounded-full',
    );
    fireEvent.change(screen.getByRole('searchbox', { name: 'Поиск по меню' }), {
      target: { value: 'марг' },
    });
    fireEvent.submit(screen.getByRole('search'));
    await waitFor(() =>
      expect(router.state.location.search).toContain('q=%D0%BC%D0%B0%D1%80%D0%B3'),
    );
    const last = new URL(productQueries(calls).at(-1) ?? '');
    expect(last.searchParams.get('search')).toBe('марг');
    expect(last.searchParams.get('category_id')).toBe('cat-pizza');
  });

  it('pages through results', async () => {
    const { calls } = mockFetchRoutes({
      ...BASE_ROUTES,
      'GET /api/v1/catalog/products': ({ url }) => {
        const page = Number(new URL(url).searchParams.get('page'));
        return jsonResponse(
          productList(page === 2 ? [BURGER_SUMMARY] : [MARGHERITA_SUMMARY], page, 2, 13),
        );
      },
    });
    const router = renderAt('/menu');
    expect(await screen.findByText('Страница 1 из 2')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Назад' })).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: 'Дальше' }));
    expect(await screen.findByRole('heading', { name: 'Классический бургер' })).toBeInTheDocument();
    expect(router.state.location.search).toBe('?page=2');
    expect(new URL(productQueries(calls).at(-1) ?? '').searchParams.get('page')).toBe('2');
  });

  it('keeps the semantics of category chips and pagination (MA-4.6.2a)', async () => {
    mockFetchRoutes({
      ...BASE_ROUTES,
      'GET /api/v1/catalog/products': () =>
        jsonResponse(productList([MARGHERITA_SUMMARY], 1, 2, 13)),
    });
    renderAt('/menu');
    await screen.findByRole('heading', { name: 'Маргарита' });

    const categories = screen.getByRole('navigation', { name: 'Категории меню' });
    const items = within(within(categories).getByRole('list')).getAllByRole('listitem');
    expect(items).toHaveLength(1 + CATEGORIES.length);
    for (const item of items) {
      const chip = within(item).getByRole('button');
      expect(chip).toHaveAttribute('type', 'button');
      expect(chip).not.toHaveAttribute('aria-current');
      expect(chip.className).not.toMatch(/cream-100/);
    }
    const all = within(categories).getByRole('button', { name: 'Все' });
    const pizza = within(categories).getByRole('button', { name: 'Пицца' });
    expect(all).toHaveAttribute('aria-pressed', 'true');
    expect(pizza).toHaveAttribute('aria-pressed', 'false');
    // MA-4.6-B: the selected chip is graphite (ink-900 on cream-50, a pair the
    // Telegram theme always keeps readable); the others are light.
    expect(all).toHaveClass('bg-ink-900', 'text-cream-50', 'min-h-11');
    expect(pizza).toHaveClass('bg-surface', 'ring-1');
    expect(pizza).not.toHaveClass('bg-ink-900');
    fireEvent.click(pizza);
    await waitFor(() => expect(pizza).toHaveAttribute('aria-pressed', 'true'));
    expect(all).toHaveAttribute('aria-pressed', 'false');
    expect(pizza).toHaveClass('bg-ink-900');
    expect(all).not.toHaveClass('bg-ink-900');

    const pages = screen.getByRole('navigation', { name: 'Страницы меню' });
    const previous = within(pages).getByRole('button', { name: 'Назад' });
    const next = within(pages).getByRole('button', { name: 'Дальше' });
    for (const button of [previous, next]) {
      expect(button).toHaveAttribute('type', 'button');
      expect(button).toHaveClass('min-h-11');
      expect(button.className).not.toMatch(/cream-100/);
    }
    expect(previous).toBeDisabled();
    expect(next).toBeEnabled();
  });

  it('explains an empty result and resets filters', async () => {
    mockFetchRoutes({
      ...BASE_ROUTES,
      'GET /api/v1/catalog/products': ({ url }) =>
        jsonResponse(
          productList(new URL(url).searchParams.get('search') ? [] : [MARGHERITA_SUMMARY]),
        ),
    });
    const router = renderAt('/menu?q=xyz');
    expect(await screen.findByText('Ничего не нашлось')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Показать всё меню' })).toHaveAttribute(
      'type',
      'button',
    );
    fireEvent.click(screen.getByRole('button', { name: 'Показать всё меню' }));
    expect(await screen.findByRole('heading', { name: 'Маргарита' })).toBeInTheDocument();
    expect(router.state.location.search).toBe('');
  });

  it('shows an empty catalog without filters', async () => {
    mockFetchRoutes({
      ...BASE_ROUTES,
      'GET /api/v1/catalog/products': () => jsonResponse(productList([])),
    });
    renderAt('/menu');
    expect(await screen.findByText('Меню пока пустое')).toBeInTheDocument();
  });

  it('shows an API error with a working retry', async () => {
    mockFetchRoutes({
      ...BASE_ROUTES,
      'GET /api/v1/catalog/products': [
        () => apiError('INTERNAL_ERROR', 500),
        () => jsonResponse(productList([MARGHERITA_SUMMARY])),
      ],
    });
    renderAt('/menu');
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Не удалось загрузить меню');
    fireEvent.click(within(alert).getByRole('button', { name: 'Повторить' }));
    expect(await screen.findByRole('heading', { name: 'Маргарита' })).toBeInTheDocument();
  });

  it('requests the catalog again in the chosen language', async () => {
    const { calls } = mockFetchRoutes({
      ...BASE_ROUTES,
      'GET /api/v1/catalog/categories': ({ url }) =>
        jsonResponse({
          items:
            new URL(url).searchParams.get('language') === 'uz'
              ? [{ ...CATEGORIES[0], name: 'Pitsa' }]
              : CATEGORIES,
        }),
      'GET /api/v1/catalog/products': () => jsonResponse(productList([MARGHERITA_SUMMARY])),
    });
    renderAt('/menu');
    await screen.findByRole('button', { name: 'Пицца' });

    fireEvent.click(screen.getAllByRole('button', { name: 'Oʻzbekcha' })[0]);
    expect(await screen.findByRole('button', { name: 'Pitsa' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'Menyu' })).toBeInTheDocument();
    expect(new URL(productQueries(calls).at(-1) ?? '').searchParams.get('language')).toBe('uz');
    await i18n.changeLanguage('ru');
  });
});

describe('product page', () => {
  const routesFor = (product = MARGHERITA) => ({
    ...BASE_ROUTES,
    [`GET /api/v1/catalog/products/${product.id}`]: () => jsonResponse(product),
  });

  const total = () => screen.getByTestId('preview-total').textContent;

  it('configures a pizza: size, required dough, extras with per-size prices', async () => {
    mockFetchRoutes(routesFor());
    renderAt('/menu/p-margherita');

    expect(await screen.findByRole('heading', { level: 1, name: 'Маргарита' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /30 см/ })).toBeChecked();
    // Dough is a required single group, chosen by default (DEC-128).
    const dough = screen.getByRole('group', { name: /Тесто/ });
    expect(within(dough).getByText('Обязательно')).toBeInTheDocument();
    expect(within(dough).getByRole('radio', { name: /Тонкое тесто/ })).toBeChecked();
    expect(total()).toBe('550 сом');

    fireEvent.click(within(dough).getByRole('radio', { name: /Традиционное тесто/ }));
    expect(within(dough).getByRole('radio', { name: /Тонкое тесто/ })).not.toBeChecked();

    fireEvent.click(screen.getByRole('checkbox', { name: /Сыр/ }));
    expect(total()).toBe('610 сом');
    const cheeseStepper = screen.getByRole('group', { name: 'Количество: Сыр' });
    fireEvent.click(within(cheeseStepper).getByRole('button', { name: 'Увеличить количество' }));
    expect(total()).toBe('670 сом');
    expect(
      within(cheeseStepper).getByRole('button', { name: 'Увеличить количество' }),
    ).toBeDisabled(); // max 2

    fireEvent.click(screen.getByRole('radio', { name: /40 см/ }));
    expect(total()).toBe('910 сом'); // 750 + 2 × 80 (price for 40 cm)
    expect(screen.getByText('выбрано 1 из 3', { exact: false })).toBeInTheDocument();
  });

  it('respects the extras limit and unavailable options', async () => {
    mockFetchRoutes(routesFor());
    renderAt('/menu/p-margherita');
    await screen.findByRole('heading', { level: 1, name: 'Маргарита' });

    expect(screen.getByRole('checkbox', { name: /Оливки/ })).toBeDisabled();
    for (const name of [/Сыр/, /Грибы/, /Халапеньо/]) {
      fireEvent.click(screen.getByRole('checkbox', { name }));
    }
    expect(screen.getByText(/Выбрано максимальное количество/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: /Грибы/ }));
    expect(screen.queryByText(/Выбрано максимальное количество/)).not.toBeInTheDocument();
  });

  it('hides the size choice for a single variant; a guest is asked to sign in', async () => {
    mockFetchRoutes(routesFor(BURGER));
    renderAt('/menu/p-burger');
    await screen.findByRole('heading', { level: 1, name: 'Классический бургер' });
    expect(screen.queryByRole('group', { name: 'Размер' })).not.toBeInTheDocument();
    expect(total()).toBe('280 сом');
    // Stage 5: the cart is real; a guest goes to the login page (DEC-13).
    expect(screen.getByRole('button', { name: 'В корзину' })).toBeEnabled();
    expect(screen.getByText(/Чтобы добавить блюдо в корзину, войдите/)).toBeInTheDocument();
  });

  it('lets an optional sauce be skipped', async () => {
    mockFetchRoutes(routesFor(SHAWARMA));
    renderAt('/menu/p-shawarma');
    await screen.findByRole('heading', { level: 1, name: 'Шаурма с курицей' });
    const sauce = screen.getByRole('group', { name: /Соус/ });
    expect(within(sauce).getByText('По желанию')).toBeInTheDocument();
    expect(within(sauce).getByRole('radio', { name: 'Не нужно' })).toBeChecked();
    fireEvent.click(within(sauce).getByRole('radio', { name: /Острый соус/ }));
    expect(within(sauce).getByRole('radio', { name: 'Не нужно' })).not.toBeChecked();
    expect(screen.queryByText('Заполните обязательные пункты выбора.')).not.toBeInTheDocument();
  });

  it('shows not found for an unknown dish', async () => {
    mockFetchRoutes({
      ...BASE_ROUTES,
      'GET /api/v1/catalog/products/nope': () => apiError('NOT_FOUND', 404),
    });
    renderAt('/menu/nope');
    expect(await screen.findByText('Блюдо не найдено')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Назад в меню/ })).toHaveAttribute('href', '/menu');
  });
});

describe('home page and footer', () => {
  it('shows categories, dishes from the menu and restaurant contacts', async () => {
    const { calls } = mockFetchRoutes({
      ...BASE_ROUTES,
      'GET /api/v1/catalog/products': ({ url }) =>
        jsonResponse(
          productList(
            new URL(url).searchParams.get('featured') === 'true' ? [] : [MARGHERITA_SUMMARY],
          ),
        ),
    });
    renderAt('/');

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Горячая пицца и любимые блюда Оша' }),
    ).toBeInTheDocument();
    const categories = await screen.findByRole('region', { name: 'Категории' });
    expect(within(categories).getByRole('link', { name: /Пицца/ })).toHaveAttribute(
      'href',
      '/menu?category=cat-pizza',
    );
    // Nothing is marked featured: the block honestly says "from our menu".
    expect(await screen.findByRole('heading', { name: 'Из нашего меню' })).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Маргарита' })).toBeInTheDocument();
    // MA-4.6-A2: the home page uses the menu's cards (one link, decorative image).
    const homeCard = screen.getByRole('link', { name: /Маргарита/ });
    expect(homeCard).toHaveAccessibleName('Маргарита от 550 сом');
    expect(homeCard).toHaveClass('sm:flex-col');
    expect(homeCard).toHaveAttribute('href', '/menu/p-margherita');
    expect(screen.getAllByText('+996000000000').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Открыто').length).toBeGreaterThan(0);
    expect(calls.some((c) => c.url.includes('featured=true'))).toBe(true);
  });

  it('makes closed hours visible', async () => {
    mockFetchRoutes({
      ...BASE_ROUTES,
      'GET /api/v1/restaurant': () => jsonResponse(RESTAURANT_CLOSED),
      'GET /api/v1/catalog/products': () => jsonResponse(productList([])),
    });
    renderAt('/');
    expect(
      await screen.findByRole('heading', { name: 'Сейчас ресторан закрыт' }),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/откроемся четверг/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText('Понедельник').length).toBeGreaterThan(0);
    expect(screen.getAllByText('10:00–23:00').length).toBeGreaterThan(0);
  });
});
