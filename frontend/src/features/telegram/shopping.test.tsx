// MA-4.2: the shopping path of the Mini App — /tg/menu → product → cart
// (stage 1) and the dish summary above the tab bar (stage 2). Only the mocked API (mockFetchRoutes answers an
// unknown route with 404, so nothing reaches the network) and the shared
// fixtures are used; the site's own tests stay as they are.
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { AppProviders } from '../../app/providers/AppProviders';
import { miniAppRoutes } from '../../app/router/miniAppRoutes';
import { routes } from '../../app/router/routes';
import { makeStore } from '../../app/store/store';
import type { CartItemOut, CartOut, ProductSummary } from '../../shared/types/api';
import {
  CATEGORIES,
  MARGHERITA,
  MARGHERITA_SUMMARY,
  PEPPERONI_SUMMARY,
  productList,
} from '../../test/catalogFixtures';
import { callTo, mockFetchRoutes, type RecordedRequest } from '../../test/fetchRoutes';
import { BASE, CART } from '../../test/orderFixtures';
import { apiError, emptyResponse, jsonResponse } from '../../test/renderWithProviders';
import {
  installTelegram,
  openAt,
  uninstallTelegram,
  type FakeTelegram,
} from '../../test/telegramMock';
import { MINI_APP_NAV_HEIGHT, NAV_SPACE_VAR } from './miniAppLayout';

const TOKEN = () => jsonResponse({ access_token: 'mini', token_type: 'bearer', expires_in: 900 });
const PROFILE = () =>
  jsonResponse({
    id: 'u-1',
    email: null,
    full_name: 'Айбек',
    phone: null,
    preferred_language: 'ru',
    roles: ['customer'],
    must_change_password: false,
    has_password: false,
  });

// Sign-in by initData, the profile and the catalog; the cart comes from BASE
// (CART: 4 items) unless a test answers it itself.
const API = {
  ...BASE,
  'POST /api/v1/auth/telegram/webapp': TOKEN,
  'GET /api/v1/users/me': PROFILE,
  'GET /api/v1/catalog/categories': () => jsonResponse({ items: CATEGORIES }),
  'GET /api/v1/catalog/products': ({ url }: RecordedRequest) =>
    new URL(url).searchParams.get('category_id') === 'cat-pizza'
      ? jsonResponse(productList([MARGHERITA_SUMMARY, PEPPERONI_SUMMARY]))
      : jsonResponse(productList([MARGHERITA_SUMMARY])),
  [`GET /api/v1/catalog/products/${MARGHERITA.id}`]: () => jsonResponse(MARGHERITA),
};

let fake: FakeTelegram;

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

function productQueries(calls: RecordedRequest[]): URLSearchParams[] {
  return calls
    .filter((c) => c.path === '/api/v1/catalog/products')
    .map((c) => new URL(c.url).searchParams);
}

/** The "Корзина" tab of the bottom bar, found by its accessible name. */
async function findCartTab(count: number): Promise<HTMLElement> {
  const nav = await screen.findByRole('navigation', { name: 'Разделы Mini App' });
  return within(nav).findByRole('link', { name: `Корзина, товаров: ${count}` });
}

function cartTabName(): string | null {
  const nav = screen.getByRole('navigation', { name: 'Разделы Mini App' });
  return within(nav)
    .getByRole('link', { name: /^Корзина, товаров/ })
    .getAttribute('aria-label');
}

/** No rendered link leaves /tg (external http(s) links aside). */
function expectOnlyMiniAppLinks(): void {
  for (const anchor of document.querySelectorAll('a[href]')) {
    const href = anchor.getAttribute('href') ?? '';
    if (/^https?:\/\//.test(href) || href.startsWith('#')) {
      continue;
    }
    expect(href, `link ${href}`).toMatch(/^\/tg(\/|$|\?)/);
  }
}

beforeEach(() => {
  fake = installTelegram();
});

afterEach(() => {
  uninstallTelegram();
  openAt('/');
});

describe('menu in the Mini App', () => {
  it('shows categories and dishes; category and search stay in /tg/menu', async () => {
    const { calls } = mockFetchRoutes(API);
    const router = launch('/tg/menu');

    const grid = await screen.findByRole('list', { name: 'Блюда' });
    expect(within(grid).getByRole('link', { name: /Маргарита/ })).toHaveAttribute(
      'href',
      '/tg/menu/p-margherita',
    );
    expect(fake.backButton.visible).toBe(false); // the start page has no BackButton

    fireEvent.click(screen.getByRole('button', { name: 'Пицца' }));
    expect(await screen.findByRole('heading', { name: 'Пепперони (говяжья)' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'Пицца' })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/tg/menu');
    expect(router.state.location.search).toBe('?category=cat-pizza');

    fireEvent.change(screen.getByRole('searchbox', { name: 'Поиск по меню' }), {
      target: { value: 'марг' },
    });
    fireEvent.submit(screen.getByRole('search'));
    await waitFor(() =>
      expect(router.state.location.search).toContain('q=%D0%BC%D0%B0%D1%80%D0%B3'),
    );
    expect(router.state.location.pathname).toBe('/tg/menu');
    const last = productQueries(calls).at(-1)!;
    expect(last.get('search')).toBe('марг');
    expect(last.get('category_id')).toBe('cat-pizza');
    expect(fake.backButton.visible).toBe(false);
    expectOnlyMiniAppLinks();
  });

  // 24 cards with the dish drawings (MA-4.6-B) are slow to build in jsdom on a
  // loaded machine; the default 15 s is not enough there. Browsers are fast.
  it('the 21st dish is on page 2 of 2 (page_size=12)', async () => {
    const dishes: ProductSummary[] = Array.from({ length: 21 }, (_, index) => ({
      ...MARGHERITA_SUMMARY,
      id: `p-dish-${index + 1}`,
      slug: `dish-${index + 1}`,
      name: `Блюдо ${index + 1}`,
    }));
    const { calls } = mockFetchRoutes({
      ...API,
      'GET /api/v1/catalog/products': ({ url }) => {
        const params = new URL(url).searchParams;
        const page = Number(params.get('page'));
        const size = Number(params.get('page_size'));
        const items = dishes.slice((page - 1) * size, page * size);
        return jsonResponse(productList(items, page, Math.ceil(dishes.length / size), 21));
      },
    });
    const router = launch('/tg/menu');

    expect(await screen.findByText('Страница 1 из 2')).toBeInTheDocument();
    expect(screen.getByText('Найдено блюд: 21')).toBeInTheDocument();
    const first = productQueries(calls)[0];
    expect(first.get('page')).toBe('1');
    expect(first.get('page_size')).toBe('12');
    let grid = screen.getByRole('list', { name: 'Блюда' });
    expect(within(grid).getAllByRole('listitem')).toHaveLength(12);
    expect(within(grid).queryByRole('heading', { name: 'Блюдо 21' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Дальше' }));
    expect(await screen.findByRole('heading', { name: 'Блюдо 21' })).toBeInTheDocument();
    expect(screen.getByText('Страница 2 из 2')).toBeInTheDocument();
    grid = screen.getByRole('list', { name: 'Блюда' });
    expect(within(grid).getAllByRole('listitem')).toHaveLength(9);
    expect(within(grid).getByRole('link', { name: /Блюдо 21/ })).toHaveAttribute(
      'href',
      '/tg/menu/p-dish-21',
    );
    expect(screen.getByRole('button', { name: 'Дальше' })).toBeDisabled();
    expect(router.state.location.pathname).toBe('/tg/menu');
    expect(router.state.location.search).toBe('?page=2');
    const second = productQueries(calls).at(-1)!;
    expect(second.get('page')).toBe('2');
    expect(second.get('page_size')).toBe('12');
  }, 30_000);
});

describe('product page and BackButton', () => {
  it('menu with a category → dish → BackButton returns to the same category', async () => {
    mockFetchRoutes(API);
    const router = launch('/tg/menu');
    await screen.findByRole('list', { name: 'Блюда' });

    fireEvent.click(screen.getByRole('button', { name: 'Пицца' }));
    await screen.findByRole('heading', { name: 'Пепперони (говяжья)' });
    const grid = screen.getByRole('list', { name: 'Блюда' });
    fireEvent.click(within(grid).getByRole('link', { name: /Маргарита/ }));

    expect(await screen.findByRole('heading', { level: 1, name: 'Маргарита' })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/tg/menu/p-margherita');
    await waitFor(() => expect(fake.backButton.visible).toBe(true));
    expectOnlyMiniAppLinks();

    act(() => fake.backButton.click());
    await waitFor(() => expect(router.state.location.pathname).toBe('/tg/menu'));
    expect(router.state.location.search).toBe('?category=cat-pizza');
    expect(await screen.findByRole('heading', { level: 1, name: 'Пицца' })).toBeInTheDocument();
    await waitFor(() => expect(fake.backButton.visible).toBe(false));
  });

  it('a dish opened directly: BackButton goes to /tg/menu, not out of the app', async () => {
    mockFetchRoutes(API);
    const router = launch('/tg/menu/p-margherita');
    await screen.findByRole('heading', { level: 1, name: 'Маргарита' });
    await waitFor(() => expect(fake.backButton.visible).toBe(true));

    act(() => fake.backButton.click());
    await waitFor(() => expect(router.state.location.pathname).toBe('/tg/menu'));
    expect(router.state.location.search).toBe('');
    expect(await screen.findByRole('list', { name: 'Блюда' })).toBeInTheDocument();
  });
});

const ADDED_LINE: CartItemOut = {
  id: 'line-pizza',
  product_id: 'p-margherita',
  variant_id: 'v-40',
  product_name: 'Маргарита',
  variant_name: '40 см',
  image_url: null,
  quantity: 1,
  special_instructions: null,
  modifiers: [
    {
      id: 'm-classic',
      group_id: 'g-dough',
      group_name: 'Тесто',
      name: 'Традиционное тесто',
      quantity: 1,
      unit_price: '0.00',
    },
    {
      id: 'm-cheese',
      group_id: 'g-extras',
      group_name: 'Добавки',
      name: 'Сыр',
      quantity: 2,
      unit_price: '80.00',
    },
  ],
  unit_price: '910.00',
  line_total: '910.00',
  is_available: true,
  issues: [],
};
const CART_AFTER_ADD: CartOut = {
  ...CART,
  items: [...CART.items, ADDED_LINE],
  items_count: CART.items_count + 1,
  subtotal: '1470.00',
};

async function configurePizza(): Promise<HTMLElement> {
  await screen.findByRole('heading', { level: 1, name: 'Маргарита' });
  fireEvent.click(screen.getByRole('radio', { name: /40 см/ }));
  const dough = screen.getByRole('group', { name: /Тесто/ });
  fireEvent.click(within(dough).getByRole('radio', { name: /Традиционное тесто/ }));
  fireEvent.click(screen.getByRole('checkbox', { name: /Сыр/ }));
  const cheese = screen.getByRole('group', { name: 'Количество: Сыр' });
  fireEvent.click(within(cheese).getByRole('button', { name: 'Увеличить количество' }));
  const add = screen.getByRole('button', { name: 'В корзину' });
  await waitFor(() => expect(add).toBeEnabled());
  return add;
}

describe('add to cart in the Mini App', () => {
  it('sends the choice without prices; success and the tab count only after the server', async () => {
    let added = false;
    let resolveAdd: (response: Response) => void = () => undefined;
    const { calls } = mockFetchRoutes({
      ...API,
      'GET /api/v1/cart': () => jsonResponse(added ? CART_AFTER_ADD : CART),
      'POST /api/v1/cart/items': () =>
        new Promise<Response>((resolve) => {
          resolveAdd = resolve;
        }),
    });
    launch('/tg/menu/p-margherita');
    await findCartTab(CART.items_count);

    fireEvent.click(await configurePizza());
    await waitFor(() => expect(calls.some((c) => c.path === '/api/v1/cart/items')).toBe(true));

    const body = callTo(calls, '/api/v1/cart/items').body as {
      modifiers: { id: string; quantity: number }[];
    } & Record<string, unknown>;
    expect(JSON.stringify(body)).not.toMatch(/price|total|subtotal|amount/i);
    expect({ ...body, modifiers: undefined }).toEqual({
      product_id: 'p-margherita',
      variant_id: 'v-40',
      quantity: 1,
      modifiers: undefined,
      special_instructions: null,
    });
    expect([...body.modifiers].sort((a, b) => a.id.localeCompare(b.id))).toEqual([
      { id: 'm-cheese', quantity: 2 },
      { id: 'm-classic', quantity: 1 },
    ]);

    // Still waiting for the server: no success text, the tab keeps the old count.
    expect(screen.getByRole('button', { name: 'Добавляем…' })).toBeDisabled();
    expect(screen.queryByText('Добавлено в корзину.')).not.toBeInTheDocument();
    expect(cartTabName()).toBe(`Корзина, товаров: ${CART.items_count}`);

    added = true;
    resolveAdd(jsonResponse(CART_AFTER_ADD));
    expect(await screen.findByText('Добавлено в корзину.')).toBeInTheDocument();
    expect(await findCartTab(CART_AFTER_ADD.items_count)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Перейти в корзину' })).toHaveAttribute(
      'href',
      '/tg/cart',
    );
    expectOnlyMiniAppLinks();
  });

  it.each([
    [
      'a refused selection',
      () =>
        apiError('ITEM_UNAVAILABLE', 422, [
          { code: 'MODIFIER_UNAVAILABLE', modifier_name: 'Сыр', group_name: 'Добавки' },
        ]),
      ['Не удалось добавить: что-то из выбранного недоступно.', 'Добавка «Сыр» недоступна.'],
    ],
    [
      'a server error',
      () => apiError('INTERNAL_ERROR', 500),
      ['Ошибка сервера. Попробуйте позже.'],
    ],
  ])('explains %s; no success and the tab count stays', async (_name, answer, texts) => {
    mockFetchRoutes({
      ...API,
      'GET /api/v1/cart': () => jsonResponse(CART),
      'POST /api/v1/cart/items': answer,
    });
    launch('/tg/menu/p-margherita');
    await findCartTab(CART.items_count);

    fireEvent.click(await configurePizza());
    for (const text of texts) {
      expect(await screen.findByText(text)).toBeInTheDocument();
    }
    expect(screen.queryByText('Добавлено в корзину.')).not.toBeInTheDocument();
    expect(cartTabName()).toBe(`Корзина, товаров: ${CART.items_count}`);
  });
});

const PIZZA_LINE: CartItemOut = { ...ADDED_LINE, id: 'line-1', quantity: 2, line_total: '1820.00' };
const COLA_LINE: CartItemOut = {
  ...ADDED_LINE,
  id: 'line-2',
  product_id: 'p-cola',
  variant_id: 'v-cola',
  product_name: 'Кола',
  variant_name: 'Стандарт',
  quantity: 1,
  modifiers: [],
  unit_price: '100.00',
  line_total: '100.00',
};

/** The cart lines themselves (each line also holds a list of its modifiers). */
function cartLines(list: HTMLElement): HTMLElement[] {
  return within(list)
    .getAllByRole('listitem')
    .filter((item) => item.parentElement === list);
}

function cartOf(items: CartItemOut[], subtotal: string): CartOut {
  return {
    ...CART,
    items,
    items_count: items.reduce((sum, item) => sum + item.quantity, 0),
    subtotal,
    has_issues: false,
  };
}

describe('cart in the Mini App', () => {
  it('quantity and removal go through the API; totals and the tab follow the server', async () => {
    let state = cartOf([PIZZA_LINE, COLA_LINE], '1920.00');
    let resolvePatch: (response: Response) => void = () => undefined;
    const { calls } = mockFetchRoutes({
      ...API,
      'GET /api/v1/cart': () => jsonResponse(state),
      'PATCH /api/v1/cart/items/line-1': () =>
        new Promise<Response>((resolve) => {
          resolvePatch = resolve;
        }),
      'DELETE /api/v1/cart/items/line-2': () => {
        state = cartOf([{ ...PIZZA_LINE, quantity: 3, line_total: '2730.00' }], '2730.00');
        return emptyResponse();
      },
    });
    launch('/tg/cart');

    const lines = await screen.findByRole('list', { name: 'Позиции корзины' });
    expect(screen.getByTestId('subtotal')).toHaveTextContent('1 920 сом');
    await findCartTab(3);
    expect(screen.getByRole('link', { name: 'Оформить заказ' })).toHaveAttribute(
      'href',
      '/tg/checkout',
    );
    expectOnlyMiniAppLinks();

    const [pizza] = cartLines(lines);
    expect(within(pizza).getByText(/Сыр × 2/)).toBeInTheDocument();
    fireEvent.click(within(pizza).getByRole('button', { name: 'Увеличить количество' }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ quantity: 3 }),
    );
    // Until the server answers, totals and the tab stay as they were.
    expect(screen.getByTestId('subtotal')).toHaveTextContent('1 920 сом');
    expect(cartTabName()).toBe('Корзина, товаров: 3');

    state = cartOf([{ ...PIZZA_LINE, quantity: 3, line_total: '2730.00' }, COLA_LINE], '2830.00');
    resolvePatch(jsonResponse(state));
    await waitFor(() => expect(screen.getByTestId('subtotal')).toHaveTextContent('2 830 сом'));
    expect(await findCartTab(4)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Удалить «Кола» из корзины' }));
    await waitFor(() => expect(screen.getByTestId('subtotal')).toHaveTextContent('2 730 сом'));
    expect(await findCartTab(3)).toBeInTheDocument();
    expect(calls.some((c) => c.method === 'DELETE' && c.path.endsWith('/line-2'))).toBe(true);
    expect(screen.queryByText('Кола')).not.toBeInTheDocument();
  });

  it('a failed quantity change or removal is explained; totals and the tab stay', async () => {
    const state = cartOf([PIZZA_LINE, COLA_LINE], '1920.00');
    mockFetchRoutes({
      ...API,
      'GET /api/v1/cart': () => jsonResponse(state),
      'PATCH /api/v1/cart/items/line-1': () => apiError('INTERNAL_ERROR', 500),
      'DELETE /api/v1/cart/items/line-2': () => apiError('NOT_FOUND', 404),
    });
    launch('/tg/cart');

    const lines = await screen.findByRole('list', { name: 'Позиции корзины' });
    await findCartTab(3);
    const [pizza, cola] = cartLines(lines);

    fireEvent.click(within(pizza).getByRole('button', { name: 'Увеличить количество' }));
    expect(await within(pizza).findByText('Ошибка сервера. Попробуйте позже.')).toBeInTheDocument();

    fireEvent.click(within(cola).getByRole('button', { name: 'Удалить «Кола» из корзины' }));
    expect(
      await within(cola).findByText('Эта позиция уже удалена. Обновите корзину.'),
    ).toBeInTheDocument();

    expect(screen.getByTestId('subtotal')).toHaveTextContent('1 920 сом');
    expect(cartTabName()).toBe('Корзина, товаров: 3');
  });
});

// MA-4.2 (stage 2): the pinned summary of a dish ("Итог выбора": total and
// "В корзину") must not slide under the bottom tab bar. jsdom does no layout,
// so the test checks the contract instead: the layout publishes the space the
// bar takes (its height plus the bottom safe area), the bar has exactly that
// height, and the summary is pinned that far from the bottom — in the Mini
// App only.
describe('the dish summary stays above the tab bar', () => {
  it('in the Mini App: summary bottom = the space of the bar, which includes the safe area', async () => {
    mockFetchRoutes(API);
    launch('/tg/menu/p-margherita');
    await screen.findByRole('heading', { level: 1, name: 'Маргарита' });
    const nav = await screen.findByRole('navigation', { name: 'Разделы Mini App' });

    const summary = screen.getByRole('region', { name: 'Итог выбора' });
    expect(within(summary).getByRole('button', { name: 'В корзину' })).toBeInTheDocument();
    expect(within(summary).getByTestId('preview-total')).toBeInTheDocument();
    expect(summary.style.bottom).toBe(`var(${NAV_SPACE_VAR}, 0px)`);

    expect(nav.style.height).toBe(`var(${NAV_SPACE_VAR})`);
    const root = nav.closest<HTMLElement>('[data-mini-app]')!;
    const space = root.style.getPropertyValue(NAV_SPACE_VAR);
    expect(space).toContain(MINI_APP_NAV_HEIGHT);
    expect(space).toContain('--tg-safe-area-inset-bottom');
    expect(space).toContain('safe-area-inset-bottom');
  });

  it('on the site the summary keeps its plain bottom-0 (no Mini App offset)', async () => {
    uninstallTelegram();
    openAt('/menu/p-margherita');
    mockFetchRoutes(API);
    const router = createMemoryRouter(routes, { initialEntries: ['/menu/p-margherita'] });
    render(
      <AppProviders store={makeStore()}>
        <RouterProvider router={router} />
      </AppProviders>,
    );
    await screen.findByRole('heading', { level: 1, name: 'Маргарита' });

    const summary = screen.getByRole('region', { name: 'Итог выбора' });
    expect(summary.style.bottom).toBe('');
    expect(summary.getAttribute('style')).toBeNull();
    expect(screen.queryByRole('navigation', { name: 'Разделы Mini App' })).not.toBeInTheDocument();
  });
});
