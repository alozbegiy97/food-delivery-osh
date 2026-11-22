import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { describe, expect, it, vi } from 'vitest';

import { AppProviders } from '../../app/providers/AppProviders';
import { routes } from '../../app/router/routes';
import { makeStore } from '../../app/store/store';
import { mockFetchRoutes } from '../../test/fetchRoutes';
import { apiError, jsonResponse } from '../../test/renderWithProviders';
import type { CourierOrderOut } from '../../shared/types/api';

vi.mock('../../features/checkout/components/DeliveryMap', () => ({
  DeliveryMap: () => <div>map</div>,
}));
vi.mock('../../features/admin/components/ZoneMap', () => ({ ZoneMap: () => <div>zones</div> }));

const SIGNED_IN = {
  accessToken: 'a',
  status: 'authenticated' as const,
  passwordChangeRequired: false,
};
const COURIER_ME = {
  id: 'u-courier',
  email: 'courier@example.com',
  full_name: 'Бакыт',
  phone: null,
  preferred_language: 'ru',
  roles: ['courier'],
  must_change_password: false,
  has_password: true,
};
const PROFILE = {
  user_id: 'u-courier',
  full_name: 'Бакыт',
  is_available: true,
  max_active_orders: 2,
  active_assignments: 1,
};

function order(extra: Partial<CourierOrderOut> = {}): CourierOrderOut {
  return {
    assignment_id: 'a-1',
    order_id: 'o-1',
    order_number: 'OSH-000009',
    status: 'preparing',
    created_at: '2026-11-13T06:00:00Z',
    assigned_at: '2026-11-13T06:05:00Z',
    accepted_at: null,
    address: {
      address_text: 'ул. Ленина, 1',
      latitude: '40.5300000',
      longitude: '72.8000000',
      entrance: '2',
      floor: '3',
      apartment: '15',
      comment: 'Домофон не работает',
    },
    customer_name: 'Айбек',
    customer_phone: '+996700123456',
    customer_comment: 'Позвоните у ворот',
    items: [
      {
        product_name: 'Плов',
        variant_name: 'Порция',
        quantity: 2,
        special_instructions: 'Без лука',
        modifiers: [],
      },
    ],
    payment_method_code: 'cash',
    total_amount: '660.00',
    currency: 'KGS',
    amount_to_collect: '660.00',
    can_accept: true,
    can_decline: true,
    can_pick_up: false,
    can_deliver: false,
    ...extra,
  };
}

const BASE = {
  'GET /api/v1/auth/me': () => jsonResponse(COURIER_ME),
  'GET /api/v1/courier/me': () => jsonResponse(PROFILE),
};

function renderApp(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <AppProviders store={makeStore({ auth: SIGNED_IN })}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return router;
}

describe('courier cabinet', () => {
  it('lists active assignments and switches availability', async () => {
    const { calls } = mockFetchRoutes({
      ...BASE,
      'GET /api/v1/courier/orders': () => jsonResponse({ kind: 'active', items: [order()] }),
      'PATCH /api/v1/courier/me/availability': () =>
        jsonResponse({ ...PROFILE, is_available: false }),
    });
    renderApp('/courier');

    const list = await screen.findByRole('list', { name: 'Мои заказы' });
    const card = within(list).getByRole('link', { name: /OSH-000009/ });
    expect(card).toHaveAttribute('href', '/courier/orders/o-1');
    expect(within(card).getByText('ул. Ленина, 1')).toBeInTheDocument();
    expect(within(card).getByText(/К получению/)).toBeInTheDocument();
    expect(screen.getByText('Активных заказов: 1 из 2')).toBeInTheDocument();

    const toggle = screen.getByRole('checkbox', { name: /Принимаю новые заказы/ });
    expect(toggle).toBeChecked();
    fireEvent.click(toggle);
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ is_available: false }),
    );
    // The courier never sends a courier id (API §10).
    expect(calls.every((c) => !JSON.stringify(c.body ?? {}).includes('courier_id'))).toBe(true);
  });

  it('shows the delivery data and accepts; pick-up waits for readiness', async () => {
    const { calls } = mockFetchRoutes({
      ...BASE,
      'GET /api/v1/courier/orders/o-1': [
        () => jsonResponse(order()),
        () =>
          jsonResponse(
            order({ accepted_at: '2026-11-13T06:06:00Z', can_accept: false, can_decline: false }),
          ),
      ],
      'POST /api/v1/courier/orders/o-1/accept': () =>
        jsonResponse(
          order({ accepted_at: '2026-11-13T06:06:00Z', can_accept: false, can_decline: false }),
        ),
    });
    renderApp('/courier/orders/o-1');

    expect(await screen.findByRole('heading', { name: 'OSH-000009' })).toBeInTheDocument();
    expect(screen.getByText('подъезд 2, этаж 3, кв. 15')).toBeInTheDocument();
    expect(screen.getByText(/Домофон не работает/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '+996700123456' })).toHaveAttribute(
      'href',
      'tel:+996700123456',
    );
    expect(screen.getByText(/Без лука/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Открыть на карте' })).toHaveAttribute(
      'href',
      expect.stringContaining('openstreetmap.org'),
    );
    const pickUp = screen.getByRole('button', { name: 'Забрал заказ' });
    expect(pickUp).toBeDisabled();
    expect(screen.getByText('Сначала примите заказ.')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Принять заказ' }));
    await waitFor(() =>
      expect(calls.some((c) => c.path === '/api/v1/courier/orders/o-1/accept')).toBe(true),
    );
    expect(await screen.findByText(/Заказ ещё готовится/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Отказаться' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Забрал заказ' })).toBeDisabled();
  });

  it('confirms delivery with the cash amount and returns to the list', async () => {
    const onTheWay = order({
      status: 'out_for_delivery',
      accepted_at: '2026-11-13T06:06:00Z',
      can_accept: false,
      can_decline: false,
      can_deliver: true,
    });
    const { calls } = mockFetchRoutes({
      ...BASE,
      'GET /api/v1/courier/orders/o-1': () => jsonResponse(onTheWay),
      'GET /api/v1/courier/orders': () => jsonResponse({ kind: 'active', items: [] }),
      'POST /api/v1/courier/orders/o-1/delivered': () =>
        jsonResponse({
          assignment_id: 'a-1',
          order_id: 'o-1',
          order_number: 'OSH-000009',
          assignment_status: 'completed',
          finished_at: '2026-11-13T07:00:00Z',
          total_amount: '660.00',
          currency: 'KGS',
          payment_method_code: 'cash',
        }),
    });
    const router = renderApp('/courier/orders/o-1');

    fireEvent.click(await screen.findByRole('button', { name: 'Доставлен' }));
    const dialog = screen.getByRole('alertdialog');
    expect(within(dialog).getByText(/получено/)).toBeInTheDocument();
    expect(calls.some((c) => c.method === 'POST')).toBe(false);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Да, доставлен' }));
    expect(await screen.findByText('Заказ отмечен как доставленный.')).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/courier');
    expect(await screen.findByText('Назначенных заказов нет')).toBeInTheDocument();
  });

  it('declines with an optional reason after confirmation', async () => {
    const { calls } = mockFetchRoutes({
      ...BASE,
      'GET /api/v1/courier/orders/o-1': () => jsonResponse(order({ status: 'confirmed' })),
      'GET /api/v1/courier/orders': () => jsonResponse({ kind: 'active', items: [] }),
      'POST /api/v1/courier/orders/o-1/decline': () =>
        jsonResponse({
          assignment_id: 'a-1',
          order_id: 'o-1',
          order_number: 'OSH-000009',
          assignment_status: 'declined',
          finished_at: '2026-11-13T06:10:00Z',
          total_amount: '660.00',
          currency: 'KGS',
          payment_method_code: 'cash',
        }),
    });
    renderApp('/courier/orders/o-1');

    fireEvent.click(await screen.findByRole('button', { name: 'Отказаться' }));
    fireEvent.change(screen.getByLabelText('Причина (необязательно)'), {
      target: { value: '  Сломался мопед ' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Да, отказаться' }));
    expect(await screen.findByText('Вы отказались от заказа.')).toBeInTheDocument();
    expect(calls.find((c) => c.path.endsWith('/decline'))?.body).toEqual({
      reason: 'Сломался мопед',
    });
  });

  it('explains an order that is no longer assigned (DEC-106)', async () => {
    mockFetchRoutes({
      ...BASE,
      'GET /api/v1/courier/orders/o-1': () => apiError('NOT_FOUND', 404),
    });
    renderApp('/courier/orders/o-1');
    expect(await screen.findByText('Заказ больше не назначен вам')).toBeInTheDocument();
  });

  it('shows the server error of an action', async () => {
    mockFetchRoutes({
      ...BASE,
      'GET /api/v1/courier/orders/o-1': () => jsonResponse(order({ status: 'confirmed' })),
      'POST /api/v1/courier/orders/o-1/accept': () => apiError('INVALID_STATUS_TRANSITION', 409),
    });
    renderApp('/courier/orders/o-1');
    fireEvent.click(await screen.findByRole('button', { name: 'Принять заказ' }));
    expect(
      await screen.findByText('Такой переход статуса сейчас невозможен. Обновите страницу.'),
    ).toBeInTheDocument();
  });

  it('shows history without address or contacts', async () => {
    mockFetchRoutes({
      ...BASE,
      'GET /api/v1/courier/orders': () =>
        jsonResponse({
          kind: 'history',
          items: [
            {
              assignment_id: 'a-1',
              order_id: 'o-1',
              order_number: 'OSH-000009',
              assignment_status: 'completed',
              finished_at: '2026-11-13T07:00:00Z',
              total_amount: '660.00',
              currency: 'KGS',
              payment_method_code: 'cash',
            },
          ],
          pagination: { page: 1, page_size: 20, total: 1, pages: 1 },
        }),
    });
    renderApp('/courier/history');
    const list = await screen.findByRole('list', { name: 'История' });
    expect(within(list).getByText('OSH-000009')).toBeInTheDocument();
    expect(within(list).getByText('Доставлен')).toBeInTheDocument();
    expect(within(list).getByText(/наличные/)).toBeInTheDocument();
  });

  it('is closed for users without the courier role', async () => {
    const { calls } = mockFetchRoutes({
      'GET /api/v1/auth/me': () => jsonResponse({ ...COURIER_ME, roles: ['customer'] }),
    });
    renderApp('/courier');
    expect(await screen.findByRole('heading', { name: 'Нет доступа' })).toBeInTheDocument();
    expect(calls.some((c) => c.path.startsWith('/api/v1/courier'))).toBe(false);
  });

  it('keeps a courier out of the admin area', async () => {
    const { calls } = mockFetchRoutes(BASE);
    renderApp('/admin/orders');
    expect(await screen.findByRole('heading', { name: 'Нет доступа' })).toBeInTheDocument();
    expect(calls.some((c) => c.path.startsWith('/api/v1/admin'))).toBe(false);
  });
});
