import { render } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';

import { AppProviders } from '../app/providers/AppProviders';
import { routes } from '../app/router/routes';
import { makeStore } from '../app/store/store';
import type { AuthState } from '../features/auth/authSlice';
import type { CartOut, OrderDetail, QuoteOut } from '../shared/types/api';
import { RESTAURANT_OPEN } from './catalogFixtures';
import type { RecordedRequest } from './fetchRoutes';
import { jsonResponse } from './renderWithProviders';

// Fixtures of the checkout, order and payment tests (stages 6–7).

export const SIGNED_IN: AuthState = {
  accessToken: 'a',
  status: 'authenticated',
  passwordChangeRequired: false,
};
export const ME = {
  id: 'u-1',
  email: 'buyer@example.com',
  full_name: 'Айбек',
  phone: '+996700123456',
  preferred_language: 'ru',
  roles: ['customer'],
  must_change_password: false,
  has_password: true,
};
export const CART: CartOut = {
  items: [
    {
      id: 'line-1',
      product_id: 'p-kompot',
      variant_id: 'v-1l',
      product_name: 'Компот',
      variant_name: '1 л',
      image_url: null,
      quantity: 4,
      special_instructions: null,
      modifiers: [],
      unit_price: '140.00',
      line_total: '560.00',
      is_available: true,
      issues: [],
    },
  ],
  items_count: 4,
  subtotal: '560.00',
  currency: 'KGS',
  has_issues: false,
  max_line_quantity: 99,
  max_lines: 50,
};

export function quote(extra: Partial<QuoteOut> = {}): QuoteOut {
  return {
    delivery_type: 'pickup',
    items_count: 4,
    subtotal: '560.00',
    zone: null,
    delivery_fee: '0.00',
    min_order_amount: '300.00',
    min_order_reached: true,
    total: '560.00',
    currency: 'KGS',
    is_open_now: true,
    next_opening_at: null,
    delivery_enabled: true,
    pickup_enabled: true,
    problems: [],
    can_place_order: true,
    ...extra,
  };
}

export const DELIVERY_QUOTE = quote({
  delivery_type: 'delivery',
  zone: { id: 'z-1', name: 'Демо-зона доставки — Ош' },
  delivery_fee: '100.00',
  min_order_amount: '500.00',
  total: '660.00',
});

export const ORDER: OrderDetail = {
  id: 'o-1',
  order_number: 'OSH-000001',
  status: 'pending',
  language_code: 'ru',
  delivery_type: 'pickup',
  payment_method_code: 'cash',
  payment_status: 'pending',
  subtotal: '560.00',
  delivery_fee: '0.00',
  total_amount: '560.00',
  currency: 'KGS',
  customer_name: 'Айбек',
  customer_phone: '+996700123456',
  customer_comment: null,
  address: null,
  payment_due_at: null,
  cancellation_reason_code: null,
  cancelled_at: null,
  completed_at: null,
  created_at: '2026-11-12T06:00:00Z',
  items: [
    {
      id: 'i-1',
      product_id: 'p-kompot',
      product_name: 'Компот',
      variant_name: '1 л',
      unit_price: '140.00',
      quantity: 4,
      total_price: '560.00',
      special_instructions: null,
      modifiers: [],
    },
  ],
  payments: [],
  status_history: [
    { old_status: null, new_status: 'pending', comment: null, created_at: '2026-11-12T06:00:00Z' },
  ],
  cancellation_requests: [],
  can_request_cancellation: true,
};

export const BASE = {
  'GET /api/v1/auth/me': () => jsonResponse(ME),
  'GET /api/v1/cart': () => jsonResponse(CART),
  'GET /api/v1/restaurant': () => jsonResponse(RESTAURANT_OPEN),
  'GET /api/v1/payment-methods': () =>
    jsonResponse({
      items: [
        { code: 'cash', sort_order: 0 },
        { code: 'mock_card', sort_order: 1 },
      ],
    }),
  'GET /api/v1/users/me/addresses': () =>
    jsonResponse({ items: [], pagination: { page: 1, page_size: 100, total: 0, pages: 0 } }),
};

export function renderApp(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <AppProviders store={makeStore({ auth: SIGNED_IN })}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return router;
}

export function posts(calls: RecordedRequest[], path: string) {
  return calls.filter((c) => c.method === 'POST' && c.path === path);
}
