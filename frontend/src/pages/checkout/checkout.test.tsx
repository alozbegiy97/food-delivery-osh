import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { mockFetchRoutes } from '../../test/fetchRoutes';
import {
  BASE,
  CART,
  DELIVERY_QUOTE,
  ME,
  ORDER,
  posts,
  quote,
  renderApp,
} from '../../test/orderFixtures';
import { apiError, jsonResponse } from '../../test/renderWithProviders';

// Leaflet needs a real browser; the map is replaced by a button that puts a point.
vi.mock('../../features/checkout/components/DeliveryMap', () => ({
  DeliveryMap: ({ onPick }: { onPick: (p: { latitude: string; longitude: string }) => void }) => (
    <button
      type="button"
      onClick={() => onPick({ latitude: '40.5300000', longitude: '72.8000000' })}
    >
      map-point
    </button>
  ),
}));

describe('checkout', () => {
  it('places a pickup order with the server total and opens the order', async () => {
    const { calls } = mockFetchRoutes({
      ...BASE,
      'POST /api/v1/checkout/quote': ({ body }) =>
        jsonResponse(
          (body as { delivery_type: string }).delivery_type === 'pickup' ? quote() : DELIVERY_QUOTE,
        ),
      'POST /api/v1/orders': () =>
        jsonResponse({ id: 'o-1', order_number: 'OSH-000001', status: 'pending' }, 201),
      'GET /api/v1/orders/o-1': () => jsonResponse(ORDER),
    });
    const router = renderApp('/checkout');

    fireEvent.click(await screen.findByRole('radio', { name: /Самовывоз/ }));
    await waitFor(() => expect(screen.getByTestId('quote-total')).toHaveTextContent('560 сом'));
    expect(screen.getByLabelText('Имя')).toHaveValue('Айбек');
    expect(screen.getByLabelText('Телефон')).toHaveValue('+996 700 12 34 56');
    expect(screen.getByRole('radio', { name: /Наличными/ })).toBeChecked();

    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить заказ' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/orders/o-1'));

    const [order] = posts(calls, '/api/v1/orders');
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
    expect(await screen.findByRole('heading', { name: 'Заказ OSH-000001' })).toBeInTheDocument();
  });

  it('needs a point for delivery and explains an address outside the zone', async () => {
    const { calls } = mockFetchRoutes({
      ...BASE,
      'POST /api/v1/checkout/quote': () =>
        jsonResponse(
          quote({
            delivery_type: 'delivery',
            problems: [{ code: 'OUT_OF_DELIVERY_ZONE', details: null }],
            can_place_order: false,
          }),
        ),
    });
    renderApp('/checkout');
    expect(await screen.findByText(/Отметьте точку на карте/)).toBeInTheDocument();
    expect(posts(calls, '/api/v1/checkout/quote')).toHaveLength(0);

    fireEvent.click(screen.getByRole('button', { name: 'map-point' }));
    expect(await screen.findByText(/вне зоны доставки/)).toBeInTheDocument();
    expect(posts(calls, '/api/v1/checkout/quote')[0].body).toEqual({
      delivery_type: 'delivery',
      address: { latitude: '40.5300000', longitude: '72.8000000' },
    });
    expect(screen.getByRole('button', { name: 'Подтвердить заказ' })).toBeDisabled();
  });

  it('shows a changed price, asks to confirm and retries with the same key', async () => {
    const { calls } = mockFetchRoutes({
      ...BASE,
      'POST /api/v1/checkout/quote': () => jsonResponse(DELIVERY_QUOTE),
      'POST /api/v1/orders': [
        () =>
          apiError('PRICE_CHANGED', 409, {
            ...DELIVERY_QUOTE,
            total: '700.00',
            subtotal: '600.00',
          }),
        () => jsonResponse({ id: 'o-1', order_number: 'OSH-000001', status: 'pending' }, 201),
      ],
      'GET /api/v1/orders/o-1': () => jsonResponse(ORDER),
    });
    const router = renderApp('/checkout');
    fireEvent.click(await screen.findByRole('button', { name: 'map-point' }));
    fireEvent.change(screen.getByLabelText('Адрес (улица, дом)'), {
      target: { value: 'ул. Ленина, 1' },
    });
    await waitFor(() => expect(screen.getByTestId('quote-total')).toHaveTextContent('660 сом'));

    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить заказ' }));
    expect(await screen.findByText(/Цены изменились/)).toBeInTheDocument();
    expect(screen.getByTestId('quote-total')).toHaveTextContent('700 сом');
    expect(router.state.location.pathname).toBe('/checkout');

    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить новую сумму' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/orders/o-1'));
    const [first, second] = posts(calls, '/api/v1/orders');
    expect(first.body).toMatchObject({
      expected_total: '660.00',
      address: { address_text: 'ул. Ленина, 1' },
    });
    expect(second.body).toMatchObject({ expected_total: '700.00' });
    expect(second.headers.get('Idempotency-Key')).toBe(first.headers.get('Idempotency-Key'));
  });

  it('checks the limits in the form before sending', async () => {
    const { calls } = mockFetchRoutes({
      ...BASE,
      'POST /api/v1/checkout/quote': () => jsonResponse(quote()),
    });
    renderApp('/checkout');
    fireEvent.click(await screen.findByRole('radio', { name: /Самовывоз/ }));
    await screen.findByTestId('quote-total');
    fireEvent.change(screen.getByLabelText('Имя'), { target: { value: '' } });
    fireEvent.change(screen.getByLabelText('Телефон'), { target: { value: '12' } });
    fireEvent.click(screen.getByRole('button', { name: 'Подтвердить заказ' }));
    expect(await screen.findByText('Заполните поле')).toBeInTheDocument();
    expect(screen.getByText('Введите номер полностью: +996 и 9 цифр')).toBeInTheDocument();
    expect(posts(calls, '/api/v1/orders')).toHaveLength(0);
  });
});

describe('orders', () => {
  it('lists the orders and sends a cancellation request', async () => {
    const { calls } = mockFetchRoutes({
      'GET /api/v1/auth/me': () => jsonResponse(ME),
      'GET /api/v1/cart': () => jsonResponse(CART),
      'GET /api/v1/orders': () =>
        jsonResponse({
          items: [
            {
              id: 'o-1',
              order_number: 'OSH-000001',
              status: 'pending',
              delivery_type: 'pickup',
              payment_method_code: 'cash',
              total_amount: '560.00',
              currency: 'KGS',
              items_count: 4,
              created_at: '2026-11-12T06:00:00Z',
            },
          ],
          pagination: { page: 1, page_size: 20, total: 1, pages: 1 },
        }),
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
    const router = renderApp('/orders');
    const list = await screen.findByRole('list', { name: 'Список заказов' });
    expect(within(list).getByText('OSH-000001')).toBeInTheDocument();
    expect(within(list).getByText('Ожидает подтверждения')).toBeInTheDocument();

    fireEvent.click(within(list).getByRole('link'));
    await waitFor(() => expect(router.state.location.pathname).toBe('/orders/o-1'));
    expect(await screen.findByTestId('order-total')).toHaveTextContent('560 сом');
    expect(screen.getByText(/Оплата: наличными/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Попросить отменить заказ' }));
    fireEvent.change(screen.getByLabelText('Причина'), { target: { value: '  Передумал ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Отправить запрос' }));
    expect(await screen.findByText('Запрос ожидает рассмотрения')).toBeInTheDocument();
    const [request] = posts(calls, '/api/v1/orders/o-1/cancellation-requests');
    expect(request.body).toEqual({ reason: 'Передумал' });
    expect(
      screen.queryByRole('button', { name: 'Попросить отменить заказ' }),
    ).not.toBeInTheDocument();
  });
});
