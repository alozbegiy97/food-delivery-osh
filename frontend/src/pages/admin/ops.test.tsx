import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { describe, expect, it, vi } from 'vitest';

import { AppProviders } from '../../app/providers/AppProviders';
import { routes } from '../../app/router/routes';
import { makeStore } from '../../app/store/store';
import { callTo, mockFetchRoutes } from '../../test/fetchRoutes';
import { ORDER } from '../../test/orderFixtures';
import { apiError, jsonResponse } from '../../test/renderWithProviders';

// Maps need a real browser; the tests only need their callbacks.
vi.mock('../../features/checkout/components/DeliveryMap', () => ({
  DeliveryMap: () => <div>map</div>,
}));
vi.mock('../../features/admin/components/ZoneMap', () => ({
  ZoneMap: ({ onChange }: { onChange: (g: unknown) => void }) => (
    <button
      type="button"
      onClick={() =>
        onChange({
          type: 'Polygon',
          coordinates: [
            [
              [72.79, 40.52],
              [72.81, 40.52],
              [72.81, 40.54],
              [72.79, 40.52],
            ],
          ],
        })
      }
    >
      draw-zone
    </button>
  ),
}));

const SIGNED_IN = {
  accessToken: 'a',
  status: 'authenticated' as const,
  passwordChangeRequired: false,
};
const ADMIN = {
  id: 'u-admin',
  email: 'admin@example.com',
  full_name: 'Админ',
  phone: null,
  preferred_language: 'ru',
  roles: ['admin'],
  must_change_password: false,
  has_password: true,
};
const COOK = { ...ADMIN, id: 'u-cook', email: 'cook@example.com', roles: ['cook'] };
const PAGE = { page: 1, page_size: 20, total: 1, pages: 1 };
const PERIOD = { date_from: '2026-11-06', date_to: '2026-11-12' };

const KITCHEN_ORDER = {
  id: 'o-1',
  order_number: 'OSH-000009',
  delivery_type: 'pickup',
  status: 'confirmed',
  confirmed_at: '2026-11-12T06:00:00Z',
  preparing_started_at: null,
  items: [
    {
      product_name: 'Плов',
      variant_name: 'Порция',
      quantity: 2,
      special_instructions: 'Без лука',
      modifiers: [{ group_name: 'Добавки', modifier_name: 'Яйцо', quantity: 2 }],
    },
  ],
};

const ADMIN_ORDER = {
  ...ORDER,
  id: 'o-1',
  order_number: 'OSH-000009',
  customer_email: 'buyer@example.com',
  awaiting_payment: false,
  delivery_zone_name: null,
  admin_history: [
    {
      old_status: null,
      new_status: 'pending',
      comment: null,
      is_admin_override: false,
      changed_by_name: null,
      created_at: '2026-11-12T06:00:00Z',
    },
  ],
  allowed_statuses: ['confirmed', 'rejected', 'cancelled'],
  assignments: [],
  needs_courier: false,
  can_assign_courier: false,
  delivered_at: null,
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

describe('kitchen', () => {
  it('sends a cook to the kitchen and shows items without customer data', async () => {
    const { calls } = mockFetchRoutes({
      'GET /api/v1/auth/me': () => jsonResponse(COOK),
      'GET /api/v1/staff/kitchen/orders': () => jsonResponse({ items: [KITCHEN_ORDER] }),
      'POST /api/v1/staff/kitchen/orders/o-1/start': () =>
        jsonResponse({ ...KITCHEN_ORDER, status: 'preparing' }),
    });
    const router = renderApp('/admin');

    const queue = await screen.findByRole('list', { name: 'Кухня' });
    expect(router.state.location.pathname).toBe('/admin/kitchen');
    expect(within(queue).getByText('OSH-000009')).toBeInTheDocument();
    expect(within(queue).getByText(/2 × Плов · Порция/)).toBeInTheDocument();
    expect(within(queue).getByText(/Добавки: Яйцо/)).toBeInTheDocument();
    expect(within(queue).getByText(/Без лука/)).toBeInTheDocument();
    // Admin-only sections are not offered to a cook.
    expect(screen.queryByRole('link', { name: 'Сотрудники' })).not.toBeInTheDocument();

    fireEvent.click(within(queue).getByRole('button', { name: 'Начать готовить' }));
    await waitFor(() => callTo(calls, '/api/v1/staff/kitchen/orders/o-1/start'));
    expect(calls.some((c) => c.path.startsWith('/api/v1/admin'))).toBe(false);
  });

  it('closes admin sections for a cook', async () => {
    const { calls } = mockFetchRoutes({
      'GET /api/v1/auth/me': () => jsonResponse(COOK),
    });
    renderApp('/admin/orders');
    expect(await screen.findByRole('heading', { name: 'Нет доступа' })).toBeInTheDocument();
    expect(calls.some((c) => c.path.startsWith('/api/v1/admin'))).toBe(false);
  });
});

describe('admin operations', () => {
  it('shows the dashboard for the default period', async () => {
    mockFetchRoutes({
      'GET /api/v1/auth/me': () => jsonResponse(ADMIN),
      'GET /api/v1/admin/dashboard/summary': () =>
        jsonResponse({
          period: PERIOD,
          orders_count: 7,
          revenue: '3200.00',
          average_check: '800.00',
          active_orders: 2,
          currency: 'KGS',
        }),
      'GET /api/v1/admin/dashboard/orders-chart': () =>
        jsonResponse({
          period: PERIOD,
          points: [{ date: '2026-11-12', orders_created: 7, revenue: '3200.00' }],
        }),
      'GET /api/v1/admin/dashboard/top-products': () =>
        jsonResponse({
          period: PERIOD,
          items: [{ product_id: 'p-1', product_name: 'Плов', quantity: 5 }],
        }),
    });
    const router = renderApp('/admin');

    expect(await screen.findByTestId('metric-orders')).toHaveTextContent('7');
    expect(router.state.location.pathname).toBe('/admin/dashboard');
    expect(screen.getByTestId('metric-active')).toHaveTextContent('2');
    expect(await screen.findByText('1. Плов')).toBeInTheDocument();
    expect(screen.getByText('5 шт.')).toBeInTheDocument();
  });

  it('keeps unpaid card orders out of the work queue unless asked', async () => {
    const { calls } = mockFetchRoutes({
      'GET /api/v1/auth/me': () => jsonResponse(ADMIN),
      'GET /api/v1/admin/orders': () =>
        jsonResponse({
          items: [
            {
              id: 'o-1',
              order_number: 'OSH-000009',
              status: 'pending',
              delivery_type: 'pickup',
              payment_method_code: 'cash',
              payment_status: 'pending',
              awaiting_payment: false,
              total_amount: '560.00',
              currency: 'KGS',
              customer_name: 'Айбек',
              customer_phone: '+996700123456',
              items_count: 4,
              has_pending_cancellation: true,
              needs_courier: false,
              courier_name: null,
              created_at: '2026-11-12T06:00:00Z',
            },
          ],
          pagination: PAGE,
        }),
    });
    renderApp('/admin/orders');

    const list = await screen.findByRole('list', { name: 'Заказы' });
    expect(within(list).getByText('Запрос отмены')).toBeInTheDocument();
    expect(
      new URL(callTo(calls, '/api/v1/admin/orders').url).searchParams.get('awaiting_payment'),
    ).toBe('false');

    fireEvent.click(screen.getByLabelText('Ожидают оплаты картой'));
    await waitFor(() =>
      expect(
        calls.some(
          (c) =>
            c.path === '/api/v1/admin/orders' &&
            new URL(c.url).searchParams.get('awaiting_payment') === 'true',
        ),
      ).toBe(true),
    );
  });

  it('confirms an order and requires a reason to reject it', async () => {
    const { calls } = mockFetchRoutes({
      'GET /api/v1/auth/me': () => jsonResponse(ADMIN),
      'GET /api/v1/admin/orders/o-1': () => jsonResponse(ADMIN_ORDER),
      'PATCH /api/v1/admin/orders/o-1/status': () =>
        jsonResponse({ ...ADMIN_ORDER, status: 'confirmed' }),
    });
    renderApp('/admin/orders/o-1');

    fireEvent.click(await screen.findByRole('button', { name: 'Подтвердить' }));
    await waitFor(() =>
      expect(callTo(calls, '/api/v1/admin/orders/o-1/status').body).toEqual({
        status: 'confirmed',
      }),
    );

    fireEvent.click(screen.getByRole('button', { name: 'Отклонить' }));
    const dialog = screen.getByRole('alertdialog', { name: 'Отклонить' });
    const submit = within(dialog).getByRole('button', { name: 'Да: Отклонить' });
    expect(submit).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText('Причина (обязательно)'), {
      target: { value: 'Нет продуктов' },
    });
    fireEvent.click(submit);
    await waitFor(() =>
      expect(calls.filter((c) => c.method === 'PATCH').map((c) => c.body)).toContainEqual({
        status: 'rejected',
        comment: 'Нет продуктов',
      }),
    );
  });

  it('shows no actions for an order that awaits card payment', async () => {
    mockFetchRoutes({
      'GET /api/v1/auth/me': () => jsonResponse(ADMIN),
      'GET /api/v1/admin/orders/o-1': () =>
        jsonResponse({ ...ADMIN_ORDER, awaiting_payment: true, allowed_statuses: [] }),
    });
    renderApp('/admin/orders/o-1');
    expect(await screen.findByText(/Заказ ждёт демо-оплаты покупателем/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Подтвердить' })).not.toBeInTheDocument();
  });

  it('approves and rejects cancellation requests', async () => {
    const request = {
      id: 'r-1',
      order_id: 'o-1',
      order_number: 'OSH-000009',
      order_status: 'confirmed',
      customer_name: 'Айбек',
      reason: 'Передумал',
      status: 'pending',
      admin_comment: null,
      created_at: '2026-11-12T06:00:00Z',
      reviewed_at: null,
      reviewed_by_name: null,
    };
    const { calls } = mockFetchRoutes({
      'GET /api/v1/auth/me': () => jsonResponse(ADMIN),
      'GET /api/v1/admin/cancellation-requests': () =>
        jsonResponse({ items: [request], pagination: PAGE }),
      'POST /api/v1/admin/cancellation-requests/r-1/reject': () =>
        jsonResponse({ ...request, status: 'rejected' }),
      'POST /api/v1/admin/cancellation-requests/r-1/approve': () =>
        apiError('CANCELLATION_NOT_ALLOWED', 409),
    });
    renderApp('/admin/cancellations');

    const list = await screen.findByRole('list', { name: 'Запросы отмены' });
    expect(within(list).getByText('Передумал')).toBeInTheDocument();

    fireEvent.click(within(list).getByRole('button', { name: 'Одобрить' }));
    fireEvent.click(screen.getByRole('button', { name: 'Да, отменить заказ' }));
    expect(
      await screen.findByText('Отмена сейчас невозможна или запрос уже рассмотрен.'),
    ).toBeInTheDocument();

    fireEvent.click(within(list).getByRole('button', { name: 'Отклонить' }));
    fireEvent.change(screen.getByLabelText('Ответ покупателю (обязательно)'), {
      target: { value: 'Заказ уже готов' },
    });
    fireEvent.click(within(list).getByRole('button', { name: 'Отклонить' }));
    await waitFor(() =>
      expect(callTo(calls, '/api/v1/admin/cancellation-requests/r-1/reject').body).toEqual({
        admin_comment: 'Заказ уже готов',
      }),
    );
  });

  it('creates a cook and protects administrators', async () => {
    const admin = {
      id: 'u-admin',
      email: 'admin@example.com',
      full_name: 'Админ',
      phone: null,
      roles: ['admin'],
      is_active: true,
      must_change_password: false,
      created_at: '2026-11-01T06:00:00Z',
    };
    const { calls } = mockFetchRoutes({
      'GET /api/v1/auth/me': () => jsonResponse(ADMIN),
      'GET /api/v1/admin/staff': () => jsonResponse({ items: [admin], pagination: PAGE }),
      'POST /api/v1/admin/staff': () =>
        jsonResponse({ ...admin, id: 'u-cook', roles: ['cook'], must_change_password: true }, 201),
    });
    renderApp('/admin/staff');

    const list = await screen.findByRole('list', { name: 'Сотрудники' });
    expect(
      within(list).getByText('Администратор: включение и отключение здесь недоступны.'),
    ).toBeInTheDocument();
    expect(within(list).queryByRole('button', { name: 'Отключить' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Добавить сотрудника' }));
    fireEvent.change(screen.getByLabelText('Имя'), { target: { value: 'Повар Тест' } });
    fireEvent.change(screen.getByLabelText('Email (логин)'), {
      target: { value: 'cook@example.com' },
    });
    fireEvent.change(screen.getByLabelText(/Временный пароль/), { target: { value: 'short' } });
    fireEvent.click(screen.getByRole('button', { name: 'Создать' }));
    expect(await screen.findByText('Пароль должен быть от 8 до 128 символов')).toBeInTheDocument();
    expect(calls.some((c) => c.method === 'POST')).toBe(false);

    fireEvent.change(screen.getByLabelText(/Временный пароль/), {
      target: { value: 'Temp1234' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Создать' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true));
    const post = calls.find((c) => c.method === 'POST');
    expect(post?.body).toEqual({
      full_name: 'Повар Тест',
      email: 'cook@example.com',
      phone: null,
      temporary_password: 'Temp1234',
      roles: ['cook'],
    });
  });

  it('shows working-hours problems from the server', async () => {
    const days = Array.from({ length: 7 }, (_, weekday) => ({
      weekday,
      is_closed: false,
      opens_at: '10:00:00',
      closes_at: '22:00:00',
    }));
    mockFetchRoutes({
      'GET /api/v1/auth/me': () => jsonResponse(ADMIN),
      'GET /api/v1/admin/settings': () =>
        jsonResponse({
          restaurant_name: 'Демо',
          phone: null,
          address: null,
          latitude: null,
          longitude: null,
          min_order_amount: '300.00',
          delivery_enabled: true,
          pickup_enabled: true,
          timezone: 'Asia/Bishkek',
        }),
      'GET /api/v1/admin/working-hours': () => jsonResponse({ items: days }),
      'PUT /api/v1/admin/working-hours': () =>
        apiError('INVALID_WORKING_HOURS', 422, [
          { weekday: 1, problem: 'overnight_overlaps_next_day' },
        ]),
    });
    renderApp('/admin/settings');

    expect(await screen.findByText('Часовой пояс: Asia/Bishkek (не меняется)')).toBeInTheDocument();
    const saves = await screen.findAllByRole('button', { name: 'Сохранить' });
    fireEvent.click(saves[1]);
    expect(
      await screen.findByText(/Ночной интервал заходит на время следующего дня/),
    ).toBeInTheDocument();
  });

  it('reports an overlapping zone', async () => {
    const { calls } = mockFetchRoutes({
      'GET /api/v1/auth/me': () => jsonResponse(ADMIN),
      'GET /api/v1/admin/delivery-zones': () => jsonResponse({ items: [] }),
      'POST /api/v1/admin/delivery-zones': () =>
        apiError('ZONE_OVERLAP', 422, [{ message: 'Центр' }]),
    });
    renderApp('/admin/zones');

    fireEvent.click(await screen.findByRole('button', { name: 'Добавить зону' }));
    expect(screen.getByText('Нарисуйте границу зоны на карте.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'draw-zone' }));
    fireEvent.change(screen.getByLabelText('Название'), { target: { value: 'Юг' } });
    fireEvent.change(screen.getByLabelText('Стоимость доставки, сом'), {
      target: { value: '120' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Создать' }));

    expect(
      await screen.findByText('Зона пересекается с другой активной зоной.'),
    ).toBeInTheDocument();
    expect(screen.getByText(/Пересекается с: Центр/)).toBeInTheDocument();
    expect(callTo(calls, '/api/v1/admin/delivery-zones').method).toBe('GET');
    expect(calls.find((c) => c.method === 'POST')?.body).toMatchObject({
      name: 'Юг',
      delivery_fee: '120',
      min_order_amount: '0',
      is_active: true,
      boundary: { type: 'Polygon' },
    });
  });

  it('assigns a courier manually and explains an empty auto-assignment', async () => {
    const delivery = {
      ...ADMIN_ORDER,
      delivery_type: 'delivery',
      status: 'confirmed',
      allowed_statuses: ['preparing', 'cancelled'],
      can_assign_courier: true,
      needs_courier: true,
    };
    const assigned = {
      ...delivery,
      needs_courier: false,
      assignments: [
        {
          id: 'as-1',
          courier_id: 'c-1',
          courier_name: 'Бакыт',
          courier_phone: '+996700000111',
          assignment_type: 'manual',
          status: 'active',
          assigned_by_name: 'Админ',
          assigned_at: '2026-11-12T06:10:00Z',
          accepted_at: null,
          declined_at: null,
          decline_reason: null,
          completed_at: null,
        },
      ],
    };
    const { calls } = mockFetchRoutes({
      'GET /api/v1/auth/me': () => jsonResponse(ADMIN),
      // Refetched after the failed auto-assignment too (invalidated tags).
      'GET /api/v1/admin/orders/o-1': [
        () => jsonResponse(delivery),
        () => jsonResponse(delivery),
        () => jsonResponse(assigned),
      ],
      'GET /api/v1/admin/couriers': () =>
        jsonResponse({
          items: [
            {
              user_id: 'c-1',
              full_name: 'Бакыт',
              phone: null,
              email: 'c1@example.com',
              is_active: true,
              is_available: true,
              max_active_orders: 2,
              active_assignments: 0,
            },
          ],
        }),
      'POST /api/v1/admin/orders/o-1/auto-assign-courier': () =>
        apiError('NO_COURIER_AVAILABLE', 409),
      'POST /api/v1/admin/orders/o-1/assign-courier': () => jsonResponse(assigned),
    });
    renderApp('/admin/orders/o-1');

    expect(await screen.findByText('Нужен курьер: заказ без назначения.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Автоназначить' }));
    expect(
      await screen.findByText('Свободных курьеров нет — выберите курьера вручную.'),
    ).toBeInTheDocument();

    const select = screen.getByLabelText('Назначить курьера');
    await waitFor(() => expect(within(select).getByText('Бакыт (0/2)')).toBeInTheDocument());
    fireEvent.change(select, { target: { value: 'c-1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Назначить' }));
    await waitFor(() =>
      expect(callTo(calls, '/api/v1/admin/orders/o-1/assign-courier').body).toEqual({
        courier_id: 'c-1',
      }),
    );
    expect(await screen.findByText('Не принял')).toBeInTheDocument();
  });

  it('requires a comment for the override of a courier transition', async () => {
    const ready = {
      ...ADMIN_ORDER,
      delivery_type: 'delivery',
      status: 'ready_for_pickup',
      allowed_statuses: ['out_for_delivery', 'cancelled'],
      can_assign_courier: true,
    };
    const { calls } = mockFetchRoutes({
      'GET /api/v1/auth/me': () => jsonResponse(ADMIN),
      'GET /api/v1/admin/orders/o-1': () => jsonResponse(ready),
      'GET /api/v1/admin/couriers': () => jsonResponse({ items: [] }),
      'PATCH /api/v1/admin/orders/o-1/status': () =>
        jsonResponse({ ...ready, status: 'out_for_delivery' }),
    });
    renderApp('/admin/orders/o-1');

    fireEvent.click(await screen.findByRole('button', { name: 'Отметить как переданный курьеру' }));
    const dialog = screen.getByRole('alertdialog', { name: 'Отметить как переданный курьеру' });
    expect(within(dialog).getByText(/вмешательство администратора/)).toBeInTheDocument();
    const submit = within(dialog).getByRole('button', {
      name: 'Да: Отметить как переданный курьеру',
    });
    expect(submit).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText('Комментарий (обязательно)'), {
      target: { value: 'Курьер без телефона' },
    });
    fireEvent.click(submit);
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({
        status: 'out_for_delivery',
        comment: 'Курьер без телефона',
      }),
    );
  });

  it('edits the courier limit within 1–10', async () => {
    const courier = {
      user_id: 'c-1',
      full_name: 'Бакыт',
      phone: '+996700000111',
      email: 'c1@example.com',
      is_active: true,
      is_available: true,
      max_active_orders: 2,
      active_assignments: 2,
    };
    const { calls } = mockFetchRoutes({
      'GET /api/v1/auth/me': () => jsonResponse(ADMIN),
      'GET /api/v1/admin/couriers': () => jsonResponse({ items: [courier] }),
      'PATCH /api/v1/admin/couriers/c-1/availability': () =>
        jsonResponse({ ...courier, max_active_orders: 1 }),
    });
    renderApp('/admin/couriers');

    const list = await screen.findByRole('list', { name: 'Курьеры' });
    expect(within(list).getByText('Заказов: 2 из 2')).toBeInTheDocument();
    const limit = within(list).getByLabelText('Лимит заказов');
    fireEvent.change(limit, { target: { value: '11' } });
    expect(within(list).getByText('Введите число от 1 до 10.')).toBeInTheDocument();
    expect(within(list).getByRole('button', { name: 'Сохранить' })).toBeDisabled();
    fireEvent.change(limit, { target: { value: '1' } });
    expect(within(list).getByText(/Лимит меньше текущих заказов/)).toBeInTheDocument();
    fireEvent.click(within(list).getByRole('button', { name: 'Сохранить' }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ max_active_orders: 1 }),
    );
  });
});
