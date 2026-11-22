// MA-4.3.1: checkout and the demo payment in the Mini App (/tg) as they work
// today — before the Telegram-specific additions of MA-4.3 (closing
// confirmation, vertical swipes). Only the mocked API is used
// (mockFetchRoutes answers an unknown route with 404, nothing reaches the
// network); no order is created anywhere. The site's own tests stay as they are.
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AppProviders } from '../../app/providers/AppProviders';
import { miniAppRoutes } from '../../app/router/miniAppRoutes';
import { makeStore } from '../../app/store/store';
import type { AddressOut, OrderDetail, PaymentOut } from '../../shared/types/api';
import { mockFetchRoutes, type RecordedRequest } from '../../test/fetchRoutes';
import { BASE, CART, DELIVERY_QUOTE, ORDER, posts, quote } from '../../test/orderFixtures';
import { apiError, jsonResponse } from '../../test/renderWithProviders';
import {
  installTelegram,
  openAt,
  uninstallTelegram,
  type FakeTelegram,
} from '../../test/telegramMock';

// Leaflet needs a real browser; the map is replaced by a button that puts a point
// (the same stand-in as the site's checkout tests).
vi.mock('../checkout/components/DeliveryMap', () => ({
  DeliveryMap: ({ onPick }: { onPick: (p: { latitude: string; longitude: string }) => void }) => (
    <button
      type="button"
      onClick={() => onPick({ latitude: '40.5300000', longitude: '72.8000000' })}
    >
      map-point
    </button>
  ),
}));

const TOKEN = () => jsonResponse({ access_token: 'mini', token_type: 'bearer', expires_in: 900 });
const PROFILE = () =>
  jsonResponse({
    id: 'u-1',
    email: null,
    full_name: 'Айбек',
    phone: '+996700123456',
    preferred_language: 'ru',
    roles: ['customer'],
    must_change_password: false,
    has_password: false,
  });

// Mini App sign-in by initData plus the shared order fixtures (cart, profile,
// restaurant, payment methods, no saved addresses).
const API = {
  ...BASE,
  'POST /api/v1/auth/telegram/webapp': TOKEN,
  'GET /api/v1/users/me': PROFILE,
};

const CREATED_CASH = () =>
  jsonResponse({ id: 'o-1', order_number: 'OSH-000001', status: 'pending' }, 201);

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
  for (const anchor of document.querySelectorAll('a[href]')) {
    const href = anchor.getAttribute('href') ?? '';
    if (/^https?:\/\//.test(href) || href.startsWith('#')) {
      continue;
    }
    expect(href, `link ${href}`).toMatch(/^\/tg(\/|$|\?)/);
  }
}

function orderPosts(calls: RecordedRequest[]) {
  return posts(calls, '/api/v1/orders');
}

async function choosePickup(total = '560 сом') {
  fireEvent.click(await screen.findByRole('radio', { name: /Самовывоз/ }));
  await waitFor(() => expect(screen.getByTestId('quote-total')).toHaveTextContent(total));
}

beforeEach(() => {
  fake = installTelegram();
});

afterEach(() => {
  uninstallTelegram();
  openAt('/');
});

describe('checkout in the Mini App', () => {
  it('pickup + cash: server total, Idempotency-Key, success only after 201, then /tg/orders/:id', async () => {
    let release: (response: Response) => void = () => undefined;
    const { calls } = mockFetchRoutes({
      ...API,
      'POST /api/v1/checkout/quote': () => jsonResponse(quote()),
      'POST /api/v1/orders': () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }),
      'GET /api/v1/orders/o-1': () => jsonResponse(ORDER),
    });
    const router = launch('/tg/checkout');

    expect(
      await screen.findByRole('heading', { level: 1, name: 'Оформление заказа' }),
    ).toBeInTheDocument();
    await waitFor(() => expect(fake.backButton.visible).toBe(true));
    await choosePickup();
    expect(screen.getByLabelText('Имя')).toHaveValue('Айбек');
    expect(screen.getByLabelText('Телефон')).toHaveValue('+996 700 12 34 56');
    expect(screen.getByRole('radio', { name: /Наличными/ })).toBeChecked();
    expectOnlyMiniAppLinks();

    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить заказ' }));
    // Pending: the button is locked and nothing is shown as placed yet.
    expect(await screen.findByRole('button', { name: 'Оформляем…' })).toBeDisabled();
    expect(router.state.location.pathname).toBe('/tg/checkout');

    const [order] = orderPosts(calls);
    expect(order.headers.get('Idempotency-Key')).toMatch(/^[A-Za-z0-9_-]{1,128}$/);
    expect(order.body).toMatchObject({
      delivery_type: 'pickup',
      payment_method_code: 'cash',
      expected_total: '560.00',
      customer_name: 'Айбек',
      customer_phone: '+996 700 12 34 56',
      language: 'ru',
    });
    expect(order.body).not.toHaveProperty('address');
    expect(order.body).not.toHaveProperty('address_id');
    expect(JSON.stringify(order.body)).not.toMatch(/subtotal|delivery_fee|unit_price/);

    release(CREATED_CASH());
    await waitFor(() => expect(router.state.location.pathname).toBe('/tg/orders/o-1'));
    expect(await screen.findByRole('heading', { name: 'Заказ OSH-000001' })).toBeInTheDocument();
    expect(orderPosts(calls)).toHaveLength(1);
    expectOnlyMiniAppLinks();
  });

  it('delivery to the saved default address sends only address_id', async () => {
    const saved: AddressOut = {
      id: 'addr-1',
      label: 'Дом',
      address_text: 'ул. Ленина, 1',
      latitude: '40.5300000',
      longitude: '72.8000000',
      entrance: null,
      floor: null,
      apartment: null,
      comment: null,
      is_default: true,
      created_at: '2026-11-12T06:00:00Z',
      updated_at: '2026-11-12T06:00:00Z',
    };
    const { calls } = mockFetchRoutes({
      ...API,
      'GET /api/v1/users/me/addresses': () =>
        jsonResponse({
          items: [saved],
          pagination: { page: 1, page_size: 100, total: 1, pages: 1 },
        }),
      'POST /api/v1/checkout/quote': () => jsonResponse(DELIVERY_QUOTE),
      'POST /api/v1/orders': CREATED_CASH,
      'GET /api/v1/orders/o-1': () => jsonResponse(ORDER),
    });
    const router = launch('/tg/checkout');

    expect(await screen.findByRole('radio', { name: /Дом/ })).toBeChecked();
    await waitFor(() => expect(screen.getByTestId('quote-total')).toHaveTextContent('660 сом'));
    expect(posts(calls, '/api/v1/checkout/quote').at(-1)?.body).toEqual({
      delivery_type: 'delivery',
      address_id: 'addr-1',
    });
    expect(screen.queryByRole('button', { name: 'map-point' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить заказ' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/tg/orders/o-1'));
    const [order] = orderPosts(calls);
    expect(order.body).toMatchObject({
      delivery_type: 'delivery',
      address_id: 'addr-1',
      expected_total: '660.00',
    });
    expect(order.body).not.toHaveProperty('address');
  });

  it('a new address needs a point on the map; the order carries the point and the text', async () => {
    const { calls } = mockFetchRoutes({
      ...API,
      'POST /api/v1/checkout/quote': () => jsonResponse(DELIVERY_QUOTE),
      'POST /api/v1/orders': CREATED_CASH,
      'GET /api/v1/orders/o-1': () => jsonResponse(ORDER),
    });
    const router = launch('/tg/checkout');

    expect(await screen.findByText(/Отметьте точку на карте/)).toBeInTheDocument();
    expect(posts(calls, '/api/v1/checkout/quote')).toHaveLength(0);
    fireEvent.click(screen.getByRole('button', { name: 'map-point' }));
    await waitFor(() => expect(screen.getByTestId('quote-total')).toHaveTextContent('660 сом'));
    expect(posts(calls, '/api/v1/checkout/quote')[0].body).toEqual({
      delivery_type: 'delivery',
      address: { latitude: '40.5300000', longitude: '72.8000000' },
    });

    fireEvent.change(screen.getByLabelText('Адрес (улица, дом)'), {
      target: { value: 'ул. Курманжан Датка, 10' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить заказ' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/tg/orders/o-1'));
    const [order] = orderPosts(calls);
    expect(order.body).toMatchObject({
      delivery_type: 'delivery',
      expected_total: '660.00',
      save_address: false,
      address: {
        address_text: 'ул. Курманжан Датка, 10',
        latitude: '40.5300000',
        longitude: '72.8000000',
      },
    });
  });

  it('an address outside the zone blocks the order (server quote decides)', async () => {
    const { calls } = mockFetchRoutes({
      ...API,
      'POST /api/v1/checkout/quote': () =>
        jsonResponse(
          quote({
            delivery_type: 'delivery',
            problems: [{ code: 'OUT_OF_DELIVERY_ZONE', details: null }],
            can_place_order: false,
          }),
        ),
    });
    launch('/tg/checkout');
    fireEvent.click(await screen.findByRole('button', { name: 'map-point' }));
    expect(await screen.findByText(/вне зоны доставки/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Подтвердить заказ' })).toBeDisabled();
    expect(orderPosts(calls)).toHaveLength(0);
  });

  it('PRICE_CHANGED: shows the new total, waits for a confirmation, retries with the same key', async () => {
    const { calls } = mockFetchRoutes({
      ...API,
      'POST /api/v1/checkout/quote': () => jsonResponse(quote()),
      'POST /api/v1/orders': [
        () => apiError('PRICE_CHANGED', 409, { ...quote(), subtotal: '600.00', total: '600.00' }),
        CREATED_CASH,
      ],
      'GET /api/v1/orders/o-1': () => jsonResponse(ORDER),
    });
    const router = launch('/tg/checkout');
    await choosePickup();

    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить заказ' }));
    expect(await screen.findByText(/Цены изменились/)).toBeInTheDocument();
    expect(screen.getByTestId('quote-total')).toHaveTextContent('600 сом');
    expect(router.state.location.pathname).toBe('/tg/checkout');
    expect(orderPosts(calls)).toHaveLength(1); // no automatic second attempt

    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить новую сумму' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/tg/orders/o-1'));
    const [first, second] = orderPosts(calls);
    expect(first.body).toMatchObject({ expected_total: '560.00' });
    expect(second.body).toMatchObject({ expected_total: '600.00' });
    expect(second.headers.get('Idempotency-Key')).toBe(first.headers.get('Idempotency-Key'));
  });

  it.each([
    [
      'the restaurant is closed',
      () => apiError('RESTAURANT_CLOSED', 409),
      /Ресторан сейчас закрыт/,
    ],
    [
      'the key was used with other data',
      () => apiError('IDEMPOTENCY_KEY_CONFLICT', 409),
      /Заказ уже был отправлен с другими данными/,
    ],
    [
      'the same order is still being processed',
      () => apiError('IDEMPOTENCY_IN_PROGRESS', 409),
      /Заказ ещё обрабатывается/,
    ],
  ])('explains that %s and stays on /tg/checkout', async (_name, answer, text) => {
    const { calls } = mockFetchRoutes({
      ...API,
      'POST /api/v1/checkout/quote': () => jsonResponse(quote()),
      'POST /api/v1/orders': answer,
    });
    const router = launch('/tg/checkout');
    await choosePickup();
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить заказ' }));
    expect(await screen.findByText(text)).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/tg/checkout');
    expect(orderPosts(calls)).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Подтвердить заказ' })).toBeEnabled();
  });

  it('a retry after a failed send reuses the same Idempotency-Key', async () => {
    const { calls } = mockFetchRoutes({
      ...API,
      'POST /api/v1/checkout/quote': () => jsonResponse(quote()),
      'POST /api/v1/orders': [() => apiError('INTERNAL_ERROR', 500), CREATED_CASH],
      'GET /api/v1/orders/o-1': () => jsonResponse(ORDER),
    });
    const router = launch('/tg/checkout');
    await choosePickup();

    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить заказ' }));
    expect(await screen.findByText('Ошибка сервера. Попробуйте позже.')).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/tg/checkout');

    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить заказ' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/tg/orders/o-1'));
    const [first, second] = orderPosts(calls);
    expect(second.headers.get('Idempotency-Key')).toBe(first.headers.get('Idempotency-Key'));
    expect(second.body).toEqual(first.body);
  });

  it('an empty cart offers the way back to the Mini App menu', async () => {
    const { calls } = mockFetchRoutes({
      ...API,
      'GET /api/v1/cart': () =>
        jsonResponse({ ...CART, items: [], items_count: 0, subtotal: '0.00' }),
    });
    launch('/tg/checkout');
    expect(await screen.findByRole('link', { name: 'Перейти в меню' })).toHaveAttribute(
      'href',
      '/tg/menu',
    );
    expect(posts(calls, '/api/v1/checkout/quote')).toHaveLength(0);
    expectOnlyMiniAppLinks();
  });
});

// ---------------- demo payment (mock_card) ----------------

const DUE_SOON = new Date(Date.now() + 25 * 60 * 1000).toISOString();

function attempt(id: string, status: string): PaymentOut {
  return {
    id,
    method_code: 'mock_card',
    amount: '560.00',
    currency: 'KGS',
    status,
    is_simulated: true,
    transaction_reference: `MOCK-${id}`,
    created_at: '2026-11-12T06:00:00Z',
    paid_at: status === 'succeeded' ? '2026-11-12T06:01:00Z' : null,
    refunded_at: null,
  };
}

function cardOrder(extra: Partial<OrderDetail> = {}): OrderDetail {
  return {
    ...ORDER,
    payment_method_code: 'mock_card',
    payment_status: 'pending',
    payment_due_at: DUE_SOON,
    payments: [attempt('a-1', 'pending')],
    ...extra,
  };
}

describe('demo payment in the Mini App', () => {
  it('mock_card at checkout leads to /tg/orders/:id/pay', async () => {
    const { calls } = mockFetchRoutes({
      ...API,
      'POST /api/v1/checkout/quote': () => jsonResponse(quote()),
      'POST /api/v1/orders': () =>
        jsonResponse(
          {
            id: 'o-1',
            order_number: 'OSH-000001',
            status: 'pending',
            payment_method_code: 'mock_card',
          },
          201,
        ),
      'GET /api/v1/orders/o-1': () => jsonResponse(cardOrder()),
    });
    const router = launch('/tg/checkout');
    await choosePickup();
    fireEvent.click(screen.getByRole('radio', { name: /Картой \(демо\)/ }));
    expect(screen.getByText(/реальные деньги не списываются/)).toBeInTheDocument();

    const place = screen.getByRole('button', { name: 'Подтвердить заказ' });
    await waitFor(() => expect(place).toBeEnabled());
    fireEvent.click(place);
    await waitFor(() => expect(router.state.location.pathname).toBe('/tg/orders/o-1/pay'));
    expect(orderPosts(calls)[0].body).toMatchObject({ payment_method_code: 'mock_card' });
    expect(await screen.findByRole('heading', { name: 'Оплата заказа' })).toBeInTheDocument();
    expectOnlyMiniAppLinks();
  });

  it('pays on /tg/orders/:id/pay: no card fields, success only after the server', async () => {
    let paid = false;
    let release: (response: Response) => void = () => undefined;
    const { calls } = mockFetchRoutes({
      ...API,
      'GET /api/v1/orders/o-1': () =>
        jsonResponse(
          paid
            ? cardOrder({
                payment_status: 'succeeded',
                payment_due_at: null,
                payments: [attempt('a-1', 'succeeded')],
              })
            : cardOrder(),
        ),
      'POST /api/v1/payments/mock/confirm': () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }),
    });
    launch('/tg/orders/o-1/pay');

    expect(await screen.findByText(/Это демонстрационная оплата/)).toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(screen.getByTestId('pay-amount')).toHaveTextContent('560 сом');
    await waitFor(() => expect(fake.backButton.visible).toBe(true));

    const pay = screen.getByRole('button', { name: 'Оплатить успешно' });
    await waitFor(() => expect(pay).toBeEnabled());
    fireEvent.click(pay);
    expect(await screen.findByRole('button', { name: 'Обрабатываем…' })).toBeDisabled();
    expect(screen.queryByText('Оплата прошла.')).not.toBeInTheDocument();

    paid = true;
    await act(async () => {
      release(
        jsonResponse({
          order_id: 'o-1',
          order_status: 'pending',
          payment_status: 'succeeded',
          payment_due_at: null,
          attempt: attempt('a-1', 'succeeded'),
        }),
      );
    });
    expect(await screen.findByText('Оплата прошла.')).toBeInTheDocument();
    const [confirm] = posts(calls, '/api/v1/payments/mock/confirm');
    expect(confirm.body).toEqual({ order_id: 'o-1', attempt_id: 'a-1', outcome: 'success' });
    expect(JSON.stringify(confirm.body)).not.toMatch(/card|cvv|expiry|number/i);
    expectOnlyMiniAppLinks();
  });

  it('an expired deadline and a timeout cancellation offer no payment', async () => {
    mockFetchRoutes({
      ...API,
      'GET /api/v1/orders/o-1': () =>
        jsonResponse(cardOrder({ payment_due_at: new Date(Date.now() - 60_000).toISOString() })),
      'GET /api/v1/orders/o-2': () =>
        jsonResponse(
          cardOrder({
            id: 'o-2',
            status: 'cancelled',
            cancellation_reason_code: 'payment_timeout',
            cancelled_at: '2026-11-12T06:31:00Z',
            payment_status: 'cancelled',
            payments: [attempt('a-1', 'cancelled')],
          }),
        ),
    });
    const router = launch('/tg/orders/o-1/pay');
    expect(await screen.findByText(/Срок оплаты истёк/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Оплатить успешно' })).not.toBeInTheDocument();

    await act(async () => {
      await router.navigate('/orders/o-2/pay');
    });
    expect(
      await screen.findByText('Заказ отменён: оплата не поступила вовремя.'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Оплатить успешно' })).not.toBeInTheDocument();
  });
});
