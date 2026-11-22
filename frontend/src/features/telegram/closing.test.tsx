// MA-4.3.2: closing confirmation of the Mini App (DEC-152 п. 11, DEC-157 п. 4).
// On while a customer's non-empty cart is checked out and while a mock_card
// order awaits payment; off otherwise, after leaving those screens, after
// success, cancellation or expiry; never touched on the site or on old clients.
// Only the mocked API is used; no order is created anywhere.
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AppProviders } from '../../app/providers/AppProviders';
import { miniAppRoutes } from '../../app/router/miniAppRoutes';
import { routes } from '../../app/router/routes';
import { makeStore } from '../../app/store/store';
import type { OrderDetail, PaymentOut } from '../../shared/types/api';
import { mockFetchRoutes } from '../../test/fetchRoutes';
import { BASE, CART, ORDER, quote, SIGNED_IN } from '../../test/orderFixtures';
import { apiError, jsonResponse } from '../../test/renderWithProviders';
import {
  installTelegram,
  openAt,
  uninstallTelegram,
  type FakeTelegram,
} from '../../test/telegramMock';

vi.mock('../checkout/components/DeliveryMap', () => ({
  DeliveryMap: () => <div>map</div>,
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
const API = {
  ...BASE,
  'POST /api/v1/auth/telegram/webapp': TOKEN,
  'GET /api/v1/users/me': PROFILE,
  'POST /api/v1/checkout/quote': () => jsonResponse(quote()),
};

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
    payment_due_at: new Date(Date.now() + 25 * 60 * 1000).toISOString(),
    payments: [attempt('a-1', 'pending')],
    ...extra,
  };
}

function confirmOut(attemptId: string, status: string, paymentStatus: string) {
  return {
    order_id: 'o-1',
    order_status: 'pending',
    payment_status: paymentStatus,
    payment_due_at: paymentStatus === 'succeeded' ? null : cardOrder().payment_due_at,
    attempt: attempt(attemptId, status),
  };
}

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

async function choosePickup() {
  fireEvent.click(await screen.findByRole('radio', { name: /Самовывоз/ }));
  await waitFor(() => expect(screen.getByTestId('quote-total')).toHaveTextContent('560 сом'));
}

beforeEach(() => {
  fake = installTelegram();
});

afterEach(() => {
  uninstallTelegram();
  openAt('/');
});

describe('closing confirmation on checkout', () => {
  it('is on for a non-empty cart and off after leaving with BackButton (unmount)', async () => {
    mockFetchRoutes(API);
    const router = launch('/tg/checkout');
    await screen.findByRole('heading', { level: 1, name: 'Оформление заказа' });
    await waitFor(() => expect(fake.closing.enabled).toBe(true));
    expect(fake.app.enableClosingConfirmation).toHaveBeenCalled();

    act(() => fake.backButton.click());
    await waitFor(() => expect(router.state.location.pathname).toBe('/tg/menu'));
    await waitFor(() => expect(fake.closing.enabled).toBe(false));
    expect(fake.app.disableClosingConfirmation).toHaveBeenCalled();
  });

  it('is off after leaving through the "Корзина" tab', async () => {
    mockFetchRoutes(API);
    const router = launch('/tg/checkout');
    await waitFor(() => expect(fake.closing.enabled).toBe(true));
    const nav = await screen.findByRole('navigation', { name: 'Разделы Mini App' });
    fireEvent.click(nav.querySelector('a[href="/tg/cart"]')!);
    await waitFor(() => expect(router.state.location.pathname).toBe('/tg/cart'));
    await waitFor(() => expect(fake.closing.enabled).toBe(false));
  });

  it('is never turned on for an empty cart', async () => {
    mockFetchRoutes({
      ...API,
      'GET /api/v1/cart': () =>
        jsonResponse({ ...CART, items: [], items_count: 0, subtotal: '0.00' }),
    });
    launch('/tg/checkout');
    expect(await screen.findByRole('link', { name: 'Перейти в меню' })).toBeInTheDocument();
    expect(fake.app.enableClosingConfirmation).not.toHaveBeenCalled();
    expect(fake.closing.enabled).toBe(false);
  });

  it('a cash order: off after the move to /tg/orders/:id', async () => {
    mockFetchRoutes({
      ...API,
      'POST /api/v1/orders': () =>
        jsonResponse({ id: 'o-1', order_number: 'OSH-000001', status: 'pending' }, 201),
      'GET /api/v1/orders/o-1': () => jsonResponse(ORDER),
    });
    const router = launch('/tg/checkout');
    await choosePickup();
    expect(fake.closing.enabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить заказ' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/tg/orders/o-1'));
    expect(await screen.findByRole('heading', { name: 'Заказ OSH-000001' })).toBeInTheDocument();
    await waitFor(() => expect(fake.closing.enabled).toBe(false));
  });
});

describe('closing confirmation on the demo payment', () => {
  it('checkout → payment keeps it on (no late switch-off); a failure keeps it; success turns it off', async () => {
    let paid = false;
    let failed = false;
    mockFetchRoutes({
      ...API,
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
      'GET /api/v1/orders/o-1': () =>
        jsonResponse(
          paid
            ? cardOrder({
                payment_status: 'succeeded',
                payment_due_at: null,
                payments: [attempt('a-1', 'failed'), attempt('a-2', 'succeeded')],
              })
            : failed
              ? cardOrder({ payments: [attempt('a-1', 'failed'), attempt('a-2', 'pending')] })
              : cardOrder(),
        ),
      'POST /api/v1/payments/mock/confirm': [
        () => {
          failed = true;
          return jsonResponse(confirmOut('a-1', 'failed', 'pending'));
        },
        () => {
          paid = true;
          return jsonResponse(confirmOut('a-2', 'succeeded', 'succeeded'));
        },
      ],
    });
    const router = launch('/tg/checkout');
    await choosePickup();
    fireEvent.click(screen.getByRole('radio', { name: /Картой \(демо\)/ }));
    const place = screen.getByRole('button', { name: 'Подтвердить заказ' });
    await waitFor(() => expect(place).toBeEnabled());
    expect(fake.closing.enabled).toBe(true);

    fireEvent.click(place);
    await waitFor(() => expect(router.state.location.pathname).toBe('/tg/orders/o-1/pay'));
    await screen.findByRole('button', { name: 'Оплатить успешно' });
    // After the route change the final state is ON: the checkout's cleanup did not win.
    await waitFor(() => expect(fake.closing.enabled).toBe(true));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(fake.closing.enabled).toBe(true);

    fireEvent.click(screen.getByRole('button', { name: 'Сымитировать ошибку' }));
    expect(await screen.findByText(/Оплата не прошла/)).toBeInTheDocument();
    expect(fake.closing.enabled).toBe(true);

    const pay = screen.getByRole('button', { name: 'Оплатить успешно' });
    await waitFor(() => expect(pay).toBeEnabled());
    fireEvent.click(pay);
    expect(await screen.findByText('Оплата прошла.')).toBeInTheDocument();
    await waitFor(() => expect(fake.closing.enabled).toBe(false));
  });

  it('a payment page left with BackButton turns it off (unmount)', async () => {
    mockFetchRoutes({ ...API, 'GET /api/v1/orders/o-1': () => jsonResponse(cardOrder()) });
    const router = launch('/tg/orders/o-1/pay');
    await screen.findByRole('button', { name: 'Оплатить успешно' });
    await waitFor(() => expect(fake.closing.enabled).toBe(true));
    act(() => fake.backButton.click());
    await waitFor(() => expect(router.state.location.pathname).toBe('/tg/menu'));
    await waitFor(() => expect(fake.closing.enabled).toBe(false));
  });

  it.each([
    [
      'an expired deadline',
      () => cardOrder({ payment_due_at: new Date(Date.now() - 60_000).toISOString() }),
      /Срок оплаты истёк/,
    ],
    [
      'a timeout cancellation',
      () =>
        cardOrder({
          status: 'cancelled',
          cancellation_reason_code: 'payment_timeout',
          cancelled_at: '2026-11-12T06:31:00Z',
          payment_status: 'cancelled',
          payments: [attempt('a-1', 'cancelled')],
        }),
      /Заказ отменён: оплата не поступила вовремя/,
    ],
    [
      'an already paid order',
      () =>
        cardOrder({
          payment_status: 'succeeded',
          payment_due_at: null,
          payments: [attempt('a-1', 'succeeded')],
        }),
      /Оплата прошла/,
    ],
    ['a cash order', () => ({ ...ORDER }), /оплачивается наличными/],
  ])('is never turned on for %s', async (_name, order, text) => {
    mockFetchRoutes({ ...API, 'GET /api/v1/orders/o-1': () => jsonResponse(order()) });
    launch('/tg/orders/o-1/pay');
    expect(await screen.findByRole('heading', { name: 'Оплата заказа' })).toBeInTheDocument();
    expect(await screen.findAllByText(text)).not.toHaveLength(0);
    expect(fake.app.enableClosingConfirmation).not.toHaveBeenCalled();
    expect(fake.closing.enabled).toBe(false);
  });

  it('is off for a missing order (404)', async () => {
    mockFetchRoutes({ ...API, 'GET /api/v1/orders/o-1': () => apiError('NOT_FOUND', 404) });
    launch('/tg/orders/o-1/pay');
    expect(await screen.findByText(/не найден/i)).toBeInTheDocument();
    expect(fake.app.enableClosingConfirmation).not.toHaveBeenCalled();
  });

  it('turns off by itself when the deadline passes while the page is open', async () => {
    mockFetchRoutes({
      ...API,
      'GET /api/v1/orders/o-1': () =>
        jsonResponse(cardOrder({ payment_due_at: new Date(Date.now() + 2500).toISOString() })),
    });
    launch('/tg/orders/o-1/pay');
    await waitFor(() => expect(fake.closing.enabled).toBe(true));
    await waitFor(() => expect(fake.closing.enabled).toBe(false), { timeout: 8000 });
    expect(await screen.findByText(/Срок оплаты истёк/)).toBeInTheDocument();
  });
});

describe('where it is never used', () => {
  it('old clients (Bot API 6.1): the methods are not called and nothing fails', async () => {
    uninstallTelegram();
    fake = installTelegram({ version: '6.1' });
    mockFetchRoutes(API);
    launch('/tg/checkout');
    await choosePickup();
    expect(fake.app.enableClosingConfirmation).not.toHaveBeenCalled();
    expect(fake.app.disableClosingConfirmation).not.toHaveBeenCalled();
  });

  it('the site (/checkout, /orders/:id/pay) never calls the Telegram methods', async () => {
    // Even with a Telegram object on the page, the site has no Mini App session.
    mockFetchRoutes({
      ...BASE,
      'POST /api/v1/checkout/quote': () => jsonResponse(quote()),
      'GET /api/v1/orders/o-1': () => jsonResponse(cardOrder()),
    });
    const router = createMemoryRouter(routes, { initialEntries: ['/checkout'] });
    render(
      <AppProviders store={makeStore({ auth: SIGNED_IN })}>
        <RouterProvider router={router} />
      </AppProviders>,
    );
    await choosePickup();
    await act(async () => {
      await router.navigate('/orders/o-1/pay');
    });
    expect(await screen.findByRole('button', { name: 'Оплатить успешно' })).toBeInTheDocument();
    expect(fake.app.enableClosingConfirmation).not.toHaveBeenCalled();
    expect(fake.app.disableClosingConfirmation).not.toHaveBeenCalled();
  });
});
