import { fireEvent, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import i18n from '../../shared/i18n';
import type { OrderDetail, PaymentOut } from '../../shared/types/api';
import { mockFetchRoutes } from '../../test/fetchRoutes';
import { BASE, CART, ME, ORDER, posts, quote, renderApp } from '../../test/orderFixtures';
import { jsonResponse } from '../../test/renderWithProviders';

// Leaflet needs a real browser (checkout renders the map for delivery).
vi.mock('../../features/checkout/components/DeliveryMap', () => ({
  DeliveryMap: () => <div>map</div>,
}));

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

function confirmed(attemptId: string, status: string, paymentStatus: string) {
  return {
    order_id: 'o-1',
    order_status: 'pending',
    payment_status: paymentStatus,
    payment_due_at: paymentStatus === 'succeeded' ? null : DUE_SOON,
    attempt: attempt(attemptId, status),
  };
}

const SIGNED = {
  'GET /api/v1/auth/me': () => jsonResponse(ME),
  'GET /api/v1/cart': () => jsonResponse(CART),
};

describe('mock card payment', () => {
  it('chooses the card at checkout and opens the payment screen', async () => {
    const { calls } = mockFetchRoutes({
      ...BASE,
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
    const router = renderApp('/checkout');
    fireEvent.click(await screen.findByRole('radio', { name: /Самовывоз/ }));
    expect(await screen.findByRole('radio', { name: /Наличными/ })).toBeChecked(); // first method
    fireEvent.click(screen.getByRole('radio', { name: /Картой \(демо\)/ }));
    expect(screen.getByText(/реальные деньги не списываются/)).toBeInTheDocument();
    const place = screen.getByRole('button', { name: 'Подтвердить заказ' });
    await waitFor(() => expect(place).toBeEnabled());
    fireEvent.click(place);
    await waitFor(() => expect(router.state.location.pathname).toBe('/orders/o-1/pay'));
    expect(posts(calls, '/api/v1/orders')[0].body).toMatchObject({
      payment_method_code: 'mock_card',
    });
    expect(await screen.findByRole('heading', { name: 'Оплата заказа' })).toBeInTheDocument();
  });

  it('pays after a failure with a new attempt; success only after the server', async () => {
    let releaseSuccess: (response: Response) => void = () => undefined;
    const { calls } = mockFetchRoutes({
      ...SIGNED,
      'GET /api/v1/orders/o-1': [
        () => jsonResponse(cardOrder()),
        () =>
          jsonResponse(
            cardOrder({ payments: [attempt('a-1', 'failed'), attempt('a-2', 'pending')] }),
          ),
        () =>
          jsonResponse(
            cardOrder({
              payment_status: 'succeeded',
              payment_due_at: null,
              payments: [attempt('a-1', 'failed'), attempt('a-2', 'succeeded')],
            }),
          ),
      ],
      'POST /api/v1/payments/mock/confirm': [
        () => jsonResponse(confirmed('a-1', 'failed', 'pending')),
        () =>
          new Promise<Response>((resolve) => {
            releaseSuccess = resolve;
          }),
      ],
    });
    renderApp('/orders/o-1/pay');

    expect(await screen.findByText(/Это демонстрационная оплата/)).toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument(); // no card fields at all
    expect(screen.getByTestId('pay-amount')).toHaveTextContent('560 сом');
    expect(screen.getByTestId('pay-left')).toHaveTextContent(/осталось \d+:\d\d/);

    fireEvent.click(screen.getByRole('button', { name: 'Сымитировать ошибку' }));
    expect(await screen.findByText(/Оплата не прошла/)).toBeInTheDocument();
    expect(await screen.findByText(/Попытка 2/)).toBeInTheDocument();

    const pay = screen.getByRole('button', { name: 'Оплатить успешно' });
    await waitFor(() => expect(pay).toBeEnabled());
    fireEvent.click(pay);
    // Locked while the request runs; no success before the answer.
    expect(await screen.findByRole('button', { name: 'Обрабатываем…' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Сымитировать ошибку' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Обрабатываем…' })); // ignored
    expect(screen.queryByText('Оплата прошла.')).not.toBeInTheDocument();
    releaseSuccess(jsonResponse(confirmed('a-2', 'succeeded', 'succeeded')));
    expect(await screen.findByText('Оплата прошла.')).toBeInTheDocument();

    const bodies = posts(calls, '/api/v1/payments/mock/confirm').map((c) => c.body);
    expect(bodies).toEqual([
      { order_id: 'o-1', attempt_id: 'a-1', outcome: 'failure' },
      { order_id: 'o-1', attempt_id: 'a-2', outcome: 'success' },
    ]);
    for (const body of bodies) {
      expect(JSON.stringify(body)).not.toMatch(/card|cvv|expiry|number/i);
    }
  });

  it('explains an expired deadline and a timeout cancellation', async () => {
    mockFetchRoutes({
      ...SIGNED,
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
    const router = renderApp('/orders/o-1/pay');
    expect(await screen.findByText(/Срок оплаты истёк/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Оплатить успешно' })).not.toBeInTheDocument();

    await router.navigate('/orders/o-2/pay');
    expect(
      await screen.findByText('Заказ отменён: оплата не поступила вовремя.'),
    ).toBeInTheDocument();
    await router.navigate('/orders/o-2');
    expect(
      await screen.findByText('Заказ отменён: оплата не поступила вовремя.'),
    ).toBeInTheDocument();
    expect(screen.getByText(/Попытка 1/)).toBeInTheDocument();
  });

  it('offers the payment from the order page while it is due', async () => {
    mockFetchRoutes({ ...SIGNED, 'GET /api/v1/orders/o-1': () => jsonResponse(cardOrder()) });
    renderApp('/orders/o-1');
    expect(await screen.findByRole('link', { name: 'Оплатить' })).toHaveAttribute(
      'href',
      '/orders/o-1/pay',
    );
    expect(screen.getByText(/Заказ ожидает демонстрационной оплаты/)).toBeInTheDocument();
  });

  it('is translated to Kyrgyz and Uzbek', async () => {
    mockFetchRoutes({ ...SIGNED, 'GET /api/v1/orders/o-1': () => jsonResponse(cardOrder()) });
    await i18n.changeLanguage('ky');
    try {
      renderApp('/orders/o-1/pay');
      expect(await screen.findByRole('button', { name: 'Ийгиликтүү төлөө' })).toBeInTheDocument();
      await i18n.changeLanguage('uz');
      expect(
        await screen.findByRole('button', { name: 'Muvaffaqiyatli toʻlash' }),
      ).toBeInTheDocument();
    } finally {
      await i18n.changeLanguage('ru');
    }
  });
});
