import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { describe, expect, it } from 'vitest';

import { AppProviders } from '../../app/providers/AppProviders';
import { routes } from '../../app/router/routes';
import { makeStore } from '../../app/store/store';
import type { AuthState } from '../../features/auth/authSlice';
import type { CartItemOut, CartOut } from '../../shared/types/api';
import { CATEGORIES, MARGHERITA, RESTAURANT_OPEN } from '../../test/catalogFixtures';
import { callTo, mockFetchRoutes } from '../../test/fetchRoutes';
import { ANONYMOUS, apiError, emptyResponse, jsonResponse } from '../../test/renderWithProviders';

const SIGNED_IN: AuthState = {
  accessToken: 'a',
  status: 'authenticated',
  passwordChangeRequired: false,
};
const ME = {
  id: '00000000-0000-0000-0000-000000000005',
  email: 'buyer@example.com',
  full_name: 'Айбек',
  phone: '+996700123456',
  preferred_language: 'ru',
  roles: ['customer'],
  must_change_password: false,
  has_password: true,
};

const PIZZA_LINE: CartItemOut = {
  id: 'line-1',
  product_id: 'p-margherita',
  variant_id: 'v-30',
  product_name: 'Маргарита',
  variant_name: '30 см',
  image_url: null,
  quantity: 2,
  special_instructions: 'Без лука',
  modifiers: [
    {
      id: 'm-thin',
      group_id: 'g-dough',
      group_name: 'Тесто',
      name: 'Тонкое тесто',
      quantity: 1,
      unit_price: '0.00',
    },
    {
      id: 'm-cheese',
      group_id: 'g-extras',
      group_name: 'Добавки',
      name: 'Сыр',
      quantity: 2,
      unit_price: '60.00',
    },
  ],
  unit_price: '670.00',
  line_total: '1340.00',
  is_available: true,
  issues: [],
};

function cart(items: CartItemOut[], extra: Partial<CartOut> = {}): CartOut {
  return {
    items,
    items_count: items.reduce((sum, item) => sum + item.quantity, 0),
    subtotal: '0.00',
    currency: 'KGS',
    has_issues: items.some((item) => !item.is_available),
    max_line_quantity: 99,
    max_lines: 50,
    ...extra,
  };
}

const EMPTY = cart([]);

function renderApp(path: string, auth: AuthState = SIGNED_IN) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <AppProviders store={makeStore({ auth })}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return router;
}

const CATALOG_ROUTES = {
  'GET /api/v1/catalog/categories': () => jsonResponse({ items: CATEGORIES }),
  'GET /api/v1/restaurant': () => jsonResponse(RESTAURANT_OPEN),
  'GET /api/v1/catalog/products/p-margherita': () => jsonResponse(MARGHERITA),
};

describe('add to cart', () => {
  it('sends a guest to the login page and back to the product', async () => {
    const { calls } = mockFetchRoutes(CATALOG_ROUTES);
    const router = renderApp('/menu/p-margherita', ANONYMOUS);
    fireEvent.click(await screen.findByRole('button', { name: 'В корзину' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/login'));
    expect(router.state.location.search).toBe('?returnTo=%2Fmenu%2Fp-margherita');
    expect(calls.some((c) => c.path === '/api/v1/cart/items')).toBe(false);
  });

  it('adds the selection without any price and shows success only after the server', async () => {
    let resolveAdd: (response: Response) => void = () => undefined;
    const { calls } = mockFetchRoutes({
      ...CATALOG_ROUTES,
      'GET /api/v1/auth/me': () => jsonResponse(ME),
      'GET /api/v1/cart': [
        () => jsonResponse(EMPTY),
        () => jsonResponse(cart([PIZZA_LINE], { subtotal: '1340.00' })),
      ],
      'POST /api/v1/cart/items': () =>
        new Promise<Response>((resolve) => {
          resolveAdd = resolve;
        }),
    });
    renderApp('/menu/p-margherita');
    await screen.findByRole('heading', { level: 1, name: 'Маргарита' });

    fireEvent.click(screen.getByRole('checkbox', { name: /Сыр/ }));
    fireEvent.click(screen.getAllByRole('button', { name: 'Увеличить количество' }).at(-1)!);
    fireEvent.change(screen.getByLabelText('Пожелания к блюду'), {
      target: { value: '  Без лука ' },
    });
    const add = await screen.findByRole('button', { name: 'В корзину' });
    await waitFor(() => expect(add).toBeEnabled());
    fireEvent.click(add);

    await waitFor(() => expect(calls.some((c) => c.path === '/api/v1/cart/items')).toBe(true));
    expect(screen.queryByText('Добавлено в корзину.')).not.toBeInTheDocument();
    const body = callTo(calls, '/api/v1/cart/items').body as Record<string, unknown>;
    expect(body).toEqual({
      product_id: 'p-margherita',
      variant_id: 'v-30',
      quantity: 2,
      modifiers: [
        { id: 'm-thin', quantity: 1 },
        { id: 'm-cheese', quantity: 1 },
      ],
      special_instructions: 'Без лука',
    });
    expect(JSON.stringify(body)).not.toMatch(/price|total/);

    resolveAdd(jsonResponse(cart([PIZZA_LINE], { subtotal: '1340.00' })));
    expect(await screen.findByText('Добавлено в корзину.')).toBeInTheDocument();
    const badges = await screen.findAllByTestId('cart-badge');
    await waitFor(() => expect(badges[0]).toHaveTextContent('2'));
  });

  it('explains a server refusal', async () => {
    mockFetchRoutes({
      ...CATALOG_ROUTES,
      'GET /api/v1/auth/me': () => jsonResponse(ME),
      'GET /api/v1/cart': () => jsonResponse(EMPTY),
      'POST /api/v1/cart/items': () =>
        apiError('ITEM_UNAVAILABLE', 422, [
          { code: 'MODIFIER_UNAVAILABLE', modifier_name: 'Сыр', group_name: 'Добавки' },
        ]),
    });
    renderApp('/menu/p-margherita');
    const add = await screen.findByRole('button', { name: 'В корзину' });
    await waitFor(() => expect(add).toBeEnabled());
    fireEvent.click(add);
    expect(
      await screen.findByText('Не удалось добавить: что-то из выбранного недоступно.'),
    ).toBeInTheDocument();
    expect(screen.getByText('Добавка «Сыр» недоступна.')).toBeInTheDocument();
    expect(screen.queryByText('Добавлено в корзину.')).not.toBeInTheDocument();
  });

  it('does not offer the cart to staff', async () => {
    mockFetchRoutes({
      ...CATALOG_ROUTES,
      'GET /api/v1/auth/me': () => jsonResponse({ ...ME, roles: ['admin'] }),
    });
    renderApp('/menu/p-margherita');
    expect(await screen.findAllByText('Корзина доступна только покупателям.')).not.toHaveLength(0);
    expect(screen.getByRole('button', { name: 'В корзину' })).toBeDisabled();
  });
});

describe('cart page', () => {
  it('sends a guest to the login page', async () => {
    mockFetchRoutes({});
    const router = renderApp('/cart', ANONYMOUS);
    await waitFor(() => expect(router.state.location.pathname).toBe('/login'));
    expect(router.state.location.search).toBe('?returnTo=%2Fcart');
  });

  it('shows an empty cart with a way to the menu', async () => {
    mockFetchRoutes({
      'GET /api/v1/auth/me': () => jsonResponse(ME),
      'GET /api/v1/cart': () => jsonResponse(EMPTY),
    });
    renderApp('/cart');
    expect(await screen.findByText('Корзина пуста')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Перейти в меню' })).toHaveAttribute('href', '/menu');
  });

  it('shows server totals and changes quantity, wishes and lines through the API', async () => {
    const cola: CartItemOut = {
      ...PIZZA_LINE,
      id: 'line-2',
      product_id: 'p-cola',
      variant_id: 'v-cola',
      product_name: 'Кола',
      variant_name: 'Стандарт',
      quantity: 1,
      special_instructions: null,
      modifiers: [],
      unit_price: '100.00',
      line_total: '100.00',
    };
    const { calls } = mockFetchRoutes({
      'GET /api/v1/auth/me': () => jsonResponse(ME),
      'GET /api/v1/cart': () => jsonResponse(cart([PIZZA_LINE, cola], { subtotal: '1440.00' })),
      'PATCH /api/v1/cart/items/line-1': () => jsonResponse(cart([PIZZA_LINE, cola])),
      'DELETE /api/v1/cart/items/line-2': () => emptyResponse(),
    });
    renderApp('/cart');

    const lines = await screen.findByRole('list', { name: 'Позиции корзины' });
    const pizza = within(lines).getAllByRole('listitem')[0];
    expect(within(pizza).getByText('Маргарита')).toBeInTheDocument();
    expect(within(pizza).getByText(/Сыр × 2/)).toBeInTheDocument();
    expect(within(pizza).getByText('Без лука')).toBeInTheDocument();
    expect(within(pizza).getByTestId('line-total')).toHaveTextContent('1 340 сом');
    expect(screen.getByTestId('subtotal')).toHaveTextContent('1 440 сом');
    expect(screen.getByTestId('items-count')).toHaveTextContent('3');
    // Stage 6: checkout is available when no line has issues.
    expect(screen.getByRole('link', { name: 'Оформить заказ' })).toHaveAttribute(
      'href',
      '/checkout',
    );

    fireEvent.click(within(pizza).getByRole('button', { name: 'Увеличить количество' }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ quantity: 3 }),
    );

    fireEvent.click(within(pizza).getByRole('button', { name: 'Изменить пожелания' }));
    fireEvent.change(within(pizza).getByLabelText('Пожелания к блюду'), {
      target: { value: '   ' },
    });
    fireEvent.click(within(pizza).getByRole('button', { name: 'Сохранить' }));
    await waitFor(() =>
      expect(calls.filter((c) => c.method === 'PATCH').at(-1)?.body).toEqual({
        special_instructions: null,
      }),
    );

    fireEvent.click(screen.getByRole('button', { name: 'Удалить «Кола» из корзины' }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'DELETE' && c.path.endsWith('line-2'))).toBe(true),
    );
  });

  it('warns about unavailable lines and blocks checkout', async () => {
    const broken: CartItemOut = {
      ...PIZZA_LINE,
      is_available: false,
      issues: [
        {
          code: 'MODIFIER_UNAVAILABLE',
          modifier_name: 'Сыр',
          group_name: 'Добавки',
          group_id: 'g-extras',
          modifier_id: 'm-cheese',
          limit: null,
        },
      ],
    };
    mockFetchRoutes({
      'GET /api/v1/auth/me': () => jsonResponse(ME),
      'GET /api/v1/cart': () => jsonResponse(cart([broken], { subtotal: '0.00' })),
    });
    renderApp('/cart');
    expect(await screen.findByText('Эту позицию сейчас нельзя заказать')).toBeInTheDocument();
    expect(screen.getByText('Добавка «Сыр» недоступна.')).toBeInTheDocument();
    expect(screen.getByText(/Удалите недоступные позиции/)).toBeInTheDocument();
    expect(screen.getByTestId('subtotal')).toHaveTextContent('0 сом');
    expect(screen.getByRole('button', { name: 'Оформить заказ' })).toBeDisabled();
  });
});
