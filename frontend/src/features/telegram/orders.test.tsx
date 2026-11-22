// MA-4.4.1: the customer's orders in the Mini App (DEC-160 п. 7). The pages
// are the site's own; these tests cover what the existing tests do not:
// the list with real orders, empty / error / retry, pages, transitions and
// BackButton, order details, the cancellation request and the payment link,
// all under /tg. Only the mocked API is used; no order is created anywhere.
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { AppProviders } from '../../app/providers/AppProviders';
import { miniAppRoutes } from '../../app/router/miniAppRoutes';
import { makeStore } from '../../app/store/store';
import type { OrderDetail, OrderSummary } from '../../shared/types/api';
import { mockFetchRoutes, type RecordedRequest } from '../../test/fetchRoutes';
import { BASE, ORDER, posts } from '../../test/orderFixtures';
import { apiError, jsonResponse } from '../../test/renderWithProviders';
import {
  installTelegram,
  openAt,
  uninstallTelegram,
  type FakeTelegram,
} from '../../test/telegramMock';

const SIGNED_IN = {
  ...BASE,
  'POST /api/v1/auth/telegram/webapp': () =>
    jsonResponse({ access_token: 'mini', token_type: 'bearer', expires_in: 900 }),
  'GET /api/v1/users/me': () =>
    jsonResponse({
      id: 'u-1',
      email: null,
      full_name: 'Айбек',
      phone: '+996700123456',
      preferred_language: 'ru',
      roles: ['customer'],
      must_change_password: false,
      has_password: false,
    }),
};

function summary(extra: Partial<OrderSummary> = {}): OrderSummary {
  return {
    id: 'o-1',
    order_number: 'OSH-000001',
    status: 'pending',
    delivery_type: 'pickup',
    payment_method_code: 'cash',
    total_amount: '560.00',
    currency: 'KGS',
    items_count: 4,
    created_at: '2026-11-12T06:00:00Z',
    ...extra,
  };
}

function orderList(items: OrderSummary[], page = 1, pages = items.length ? 1 : 0) {
  return jsonResponse({
    items,
    pagination: { page, page_size: 20, total: items.length, pages },
  });
}

const DELIVERY_ORDER: OrderDetail = {
  ...ORDER,
  id: 'o-3',
  order_number: 'OSH-000003',
  status: 'confirmed',
  delivery_type: 'delivery',
  subtotal: '1100.00',
  delivery_fee: '100.00',
  total_amount: '1200.00',
  address: {
    address_text: 'ул. Ленина, 1',
    latitude: '40.5283',
    longitude: '72.7985',
    entrance: '2',
    floor: '3',
    apartment: '15',
    comment: 'Домофон не работает',
  },
  items: [
    {
      id: 'i-3',
      product_id: 'p-pizza',
      product_name: 'Маргарита',
      variant_name: '30 см',
      unit_price: '550.00',
      quantity: 2,
      total_price: '1100.00',
      special_instructions: 'Без лука',
      modifiers: [
        {
          group_name: 'Добавки',
          modifier_name: 'Сыр',
          quantity: 2,
          unit_price: '60.00',
          total_price: '120.00',
        },
      ],
    },
  ],
  status_history: [
    { old_status: null, new_status: 'pending', comment: null, created_at: '2026-11-12T06:00:00Z' },
    {
      old_status: 'pending',
      new_status: 'confirmed',
      comment: null,
      created_at: '2026-11-12T06:05:00Z',
    },
  ],
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

/** No rendered link leaves /tg (external http(s) links aside). */
function expectOnlyMiniAppLinks(): void {
  for (const a of document.querySelectorAll('a[href]')) {
    const href = a.getAttribute('href') ?? '';
    if (/^https?:\/\//.test(href) || href.startsWith('#')) {
      continue;
    }
    expect(href, `link ${href}`).toMatch(/^\/tg(\/|$|\?)/);
  }
}

function orderListCalls(calls: RecordedRequest[]) {
  return calls.filter((c) => c.method === 'GET' && c.path === '/api/v1/orders');
}

beforeEach(() => {
  fake = installTelegram();
});

afterEach(() => {
  uninstallTelegram();
  openAt('/');
});

describe('the orders list in the Mini App', () => {
  it('lists the orders with links inside /tg; a card opens it, BackButton returns', async () => {
    mockFetchRoutes({
      ...SIGNED_IN,
      'GET /api/v1/orders': () =>
        orderList([
          summary(),
          summary({
            id: 'o-2',
            order_number: 'OSH-000002',
            status: 'completed',
            delivery_type: 'delivery',
            total_amount: '660.00',
            items_count: 1,
          }),
        ]),
      'GET /api/v1/orders/o-1': () => jsonResponse(ORDER),
    });
    const router = launch('/tg/orders');

    const list = await screen.findByRole('list', { name: 'Список заказов' });
    const links = within(list).getAllByRole('link');
    expect(links.map((l) => l.getAttribute('href'))).toEqual(['/tg/orders/o-1', '/tg/orders/o-2']);
    expect(within(links[0]).getByText('OSH-000001')).toBeInTheDocument();
    expect(within(links[0]).getByText('Ожидает подтверждения')).toBeInTheDocument();
    expect(within(links[1]).getByText('Завершён')).toBeInTheDocument();
    expect(within(links[1]).getByText(/Доставка/)).toBeInTheDocument();
    const nav = screen.getByRole('navigation', { name: 'Разделы Mini App' });
    expect(within(nav).getByRole('link', { name: 'Заказы' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expectOnlyMiniAppLinks();

    fireEvent.click(links[0]);
    await waitFor(() => expect(router.state.location.pathname).toBe('/tg/orders/o-1'));
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Заказ OSH-000001' }),
    ).toBeInTheDocument();
    expect(fake.backButton.visible).toBe(true);

    act(() => fake.backButton.click());
    await waitFor(() => expect(router.state.location.pathname).toBe('/tg/orders'));
    expect(await screen.findByRole('list', { name: 'Список заказов' })).toBeInTheDocument();
  });

  it('an empty list leads to the Mini App menu', async () => {
    mockFetchRoutes({ ...SIGNED_IN, 'GET /api/v1/orders': () => orderList([]) });
    const router = launch('/tg/orders');
    expect(await screen.findByText('Заказов пока нет')).toBeInTheDocument();
    const toMenu = screen.getByRole('link', { name: 'Перейти в меню' });
    expect(toMenu).toHaveAttribute('href', '/tg/menu');
    fireEvent.click(toMenu);
    await waitFor(() => expect(router.state.location.pathname).toBe('/tg/menu'));
  });

  it('a loading error offers "Повторить"; the retry shows the orders', async () => {
    const { calls } = mockFetchRoutes({
      ...SIGNED_IN,
      'GET /api/v1/orders': [() => apiError('INTERNAL_ERROR', 500), () => orderList([summary()])],
    });
    launch('/tg/orders');
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Не удалось загрузить заказы');
    fireEvent.click(within(alert).getByRole('button', { name: 'Повторить' }));
    const list = await screen.findByRole('list', { name: 'Список заказов' });
    expect(within(list).getByText('OSH-000001')).toBeInTheDocument();
    expect(orderListCalls(calls)).toHaveLength(2);
  });

  it('pages through the orders', async () => {
    const { calls } = mockFetchRoutes({
      ...SIGNED_IN,
      'GET /api/v1/orders': ({ url }) =>
        new URL(url).searchParams.get('page') === '2'
          ? orderList([summary({ id: 'o-21', order_number: 'OSH-000021' })], 2, 2)
          : orderList([summary()], 1, 2),
    });
    launch('/tg/orders');
    const pages = await screen.findByRole('navigation', { name: 'Страницы заказов' });
    expect(within(pages).getByText('Страница 1 из 2')).toBeInTheDocument();
    expect(within(pages).getByRole('button', { name: 'Назад' })).toBeDisabled();

    fireEvent.click(within(pages).getByRole('button', { name: 'Далее' }));
    expect(await within(pages).findByText('Страница 2 из 2')).toBeInTheDocument();
    expect(await screen.findByText('OSH-000021')).toBeInTheDocument();
    expect(within(pages).getByRole('button', { name: 'Далее' })).toBeDisabled();
    const urls = orderListCalls(calls).map((c) => new URL(c.url).searchParams);
    expect(urls.at(-1)?.get('page')).toBe('2');
    expect(urls.at(-1)?.get('page_size')).toBe('20');
  });
});

describe('order details in the Mini App', () => {
  it('shows a delivery order from the server snapshot; the back link stays in /tg', async () => {
    mockFetchRoutes({
      ...SIGNED_IN,
      'GET /api/v1/orders/o-3': () => jsonResponse(DELIVERY_ORDER),
      'GET /api/v1/orders': () => orderList([summary()]),
    });
    const router = launch('/tg/orders/o-3');

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Заказ OSH-000003' }),
    ).toBeInTheDocument();
    expect(screen.getByText('Маргарита · 30 см × 2')).toBeInTheDocument();
    expect(screen.getByText(/Добавки: Сыр × 2/)).toBeInTheDocument();
    expect(screen.getByText(/Без лука/)).toBeInTheDocument();
    expect(screen.getByText('ул. Ленина, 1')).toBeInTheDocument();
    expect(screen.getByText('подъезд 2, этаж 3, кв. 15')).toBeInTheDocument();
    expect(screen.getByText('Домофон не работает')).toBeInTheDocument();
    expect(screen.getByTestId('order-total')).toHaveTextContent('1 200 сом');
    expect(
      screen.getByText('Оплата: наличными — ожидает оплаты при получении'),
    ).toBeInTheDocument();
    const history = screen.getByRole('heading', { name: 'История статусов' }).parentElement!;
    expect(within(history).getAllByRole('listitem')).toHaveLength(2);
    expect(within(history).getByText('Подтверждён')).toBeInTheDocument();
    expectOnlyMiniAppLinks();

    const back = screen.getByRole('link', { name: /Все заказы/ });
    expect(back).toHaveAttribute('href', '/tg/orders');
    fireEvent.click(back);
    await waitFor(() => expect(router.state.location.pathname).toBe('/tg/orders'));
  });

  it('a cancelled order shows the reason and the restaurant answer, no new request', async () => {
    mockFetchRoutes({
      ...SIGNED_IN,
      'GET /api/v1/orders/o-1': () =>
        jsonResponse({
          ...ORDER,
          status: 'cancelled',
          cancellation_reason_code: 'customer_request',
          cancelled_at: '2026-11-12T06:10:00Z',
          payment_status: 'cancelled',
          can_request_cancellation: false,
          cancellation_requests: [
            {
              id: 'c-1',
              reason: 'Передумал',
              status: 'approved',
              admin_comment: 'Отменили',
              created_at: '2026-11-12T06:05:00Z',
              reviewed_at: '2026-11-12T06:10:00Z',
            },
          ],
        }),
    });
    launch('/tg/orders/o-1');
    expect(await screen.findByText('Заказ отменён по вашему запросу.')).toBeInTheDocument();
    expect(screen.getByText('Запрос одобрен')).toBeInTheDocument();
    expect(screen.getByText('Причина: Передумал')).toBeInTheDocument();
    expect(screen.getByText('Ответ ресторана: Отменили')).toBeInTheDocument();
    expect(screen.getByText('В этом статусе запросить отмену уже нельзя.')).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Попросить отменить заказ' }),
    ).not.toBeInTheDocument();
  });

  it('an unknown or foreign order: "not found" inside the Mini App', async () => {
    mockFetchRoutes({
      ...SIGNED_IN,
      'GET /api/v1/orders/o-x': () => apiError('NOT_FOUND', 404),
    });
    const router = launch('/tg/orders/o-x');
    expect(await screen.findByText('Заказ не найден')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Все заказы/ })).toHaveAttribute('href', '/tg/orders');
    expect(router.state.location.pathname).toBe('/tg/orders/o-x');
  });
});

describe('cancellation request in the Mini App', () => {
  it('is sent with the Mini App token; the reloaded order shows the pending request', async () => {
    const { calls } = mockFetchRoutes({
      ...SIGNED_IN,
      'GET /api/v1/orders/o-1': [
        () => jsonResponse(ORDER),
        () =>
          jsonResponse({
            ...ORDER,
            can_request_cancellation: false,
            cancellation_requests: [
              {
                id: 'c-1',
                reason: 'Передумал',
                status: 'pending',
                admin_comment: null,
                created_at: '2026-11-12T06:05:00Z',
                reviewed_at: null,
              },
            ],
          }),
      ],
      'POST /api/v1/orders/o-1/cancellation-requests': () =>
        jsonResponse({ id: 'c-1', reason: 'Передумал', status: 'pending' }, 201),
    });
    const router = launch('/tg/orders/o-1');
    fireEvent.click(await screen.findByRole('button', { name: 'Попросить отменить заказ' }));
    fireEvent.change(screen.getByLabelText('Причина'), { target: { value: ' Передумал ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Отправить запрос' }));

    expect(await screen.findByText('Запрос ожидает рассмотрения')).toBeInTheDocument();
    const [request] = posts(calls, '/api/v1/orders/o-1/cancellation-requests');
    expect(request.body).toEqual({ reason: 'Передумал' });
    expect(request.headers.get('Authorization')).toBe('Bearer mini');
    expect(router.state.location.pathname).toBe('/tg/orders/o-1');
    // The customer never cancels directly: no status change was requested.
    expect(calls.some((c) => c.method !== 'GET' && /\/status$/.test(c.path))).toBe(false);
  });

  it('a refused request shows the server reason and keeps the form', async () => {
    mockFetchRoutes({
      ...SIGNED_IN,
      'GET /api/v1/orders/o-1': () => jsonResponse(ORDER),
      'POST /api/v1/orders/o-1/cancellation-requests': () =>
        apiError('CANCELLATION_NOT_ALLOWED', 409),
    });
    launch('/tg/orders/o-1');
    fireEvent.click(await screen.findByRole('button', { name: 'Попросить отменить заказ' }));
    fireEvent.change(screen.getByLabelText('Причина'), { target: { value: 'Передумал' } });
    fireEvent.click(screen.getByRole('button', { name: 'Отправить запрос' }));

    expect(await screen.findByText('В этом статусе отмену запросить нельзя.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Отправить запрос' })).toBeEnabled();
    expect(screen.getByLabelText('Причина')).toHaveValue('Передумал');
  });
});

describe('payment from the order page in the Mini App', () => {
  it('an order awaiting the demo payment opens /tg/orders/:id/pay', async () => {
    const due = new Date(Date.now() + 25 * 60 * 1000).toISOString();
    const cardOrder: OrderDetail = {
      ...ORDER,
      payment_method_code: 'mock_card',
      payment_status: 'pending',
      payment_due_at: due,
      payments: [
        {
          id: 'a-1',
          method_code: 'mock_card',
          amount: '560.00',
          currency: 'KGS',
          status: 'pending',
          is_simulated: true,
          transaction_reference: 'MOCK-a-1',
          created_at: '2026-11-12T06:00:00Z',
          paid_at: null,
          refunded_at: null,
        },
      ],
    };
    mockFetchRoutes({ ...SIGNED_IN, 'GET /api/v1/orders/o-1': () => jsonResponse(cardOrder) });
    const router = launch('/tg/orders/o-1');
    const pay = await screen.findByRole('link', { name: 'Оплатить' });
    expect(pay).toHaveAttribute('href', '/tg/orders/o-1/pay');
    fireEvent.click(pay);
    await waitFor(() => expect(router.state.location.pathname).toBe('/tg/orders/o-1/pay'));
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Оплата заказа' }),
    ).toBeInTheDocument();
  });
});
