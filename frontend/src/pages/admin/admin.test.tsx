import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { describe, expect, it } from 'vitest';

import { AppProviders } from '../../app/providers/AppProviders';
import { routes } from '../../app/router/routes';
import { makeStore } from '../../app/store/store';
import { callTo, mockFetchRoutes } from '../../test/fetchRoutes';
import { apiError, jsonResponse } from '../../test/renderWithProviders';

const SIGNED_IN = {
  accessToken: 'a',
  status: 'authenticated' as const,
  passwordChangeRequired: false,
};
const ME = {
  id: '00000000-0000-0000-0000-000000000009',
  email: 'admin@example.com',
  full_name: 'Админ',
  phone: null,
  preferred_language: 'ru',
  roles: ['admin'],
  must_change_password: false,
  has_password: true,
};

const ru = (name: string) => [{ language_code: 'ru', name, description: null }];

const CATEGORY = {
  id: 'cat-1',
  slug: 'pizza',
  sort_order: 1,
  is_active: true,
  image_url: null,
  translations: ru('Пицца'),
  products_count: 1,
};
const SINGLE_GROUP = {
  id: 'g-1',
  selection_type: 'single',
  is_required: true,
  min_selections: 1,
  max_selections: 1,
  is_active: true,
  sort_order: 0,
  translations: ru('Соус'),
  products_count: 0,
  modifiers: [
    {
      id: 'm-1',
      group_id: 'g-1',
      price_delta: '30.00',
      max_quantity: 1,
      is_available: true,
      sort_order: 0,
      translations: ru('Чесночный'),
    },
  ],
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

function type(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

describe('admin area', () => {
  it('is closed for users without the admin role', async () => {
    const { calls } = mockFetchRoutes({
      'GET /api/v1/auth/me': () => jsonResponse({ ...ME, roles: ['customer'] }),
    });
    renderApp('/admin/categories');
    expect(await screen.findByRole('heading', { name: 'Нет доступа' })).toBeInTheDocument();
    expect(calls.some((c) => c.path.startsWith('/api/v1/admin'))).toBe(false);
  });

  it('lists categories and creates one with the required RU name', async () => {
    const { calls } = mockFetchRoutes({
      'GET /api/v1/auth/me': () => jsonResponse(ME),
      'GET /api/v1/admin/categories': () => jsonResponse({ items: [CATEGORY] }),
      'POST /api/v1/admin/categories': [
        () =>
          apiError('VALIDATION_ERROR', 422, [
            { field: 'slug', message: 'this slug is already used' },
          ]),
        () => jsonResponse({ ...CATEGORY, id: 'cat-2' }, 201),
      ],
    });
    renderApp('/admin/categories');

    const list = await screen.findByRole('list', { name: 'Категории' });
    expect(within(list).getByText('Пицца')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Управление' })).toHaveAttribute('href', '/admin');

    fireEvent.click(screen.getByRole('button', { name: 'Добавить категорию' }));
    fireEvent.click(screen.getByRole('button', { name: 'Создать' }));
    expect(await screen.findByText('Укажите название на русском')).toBeInTheDocument();
    expect(calls.some((c) => c.method === 'POST')).toBe(false);

    type('Название (RU) *', 'Салаты');
    fireEvent.click(screen.getByRole('button', { name: 'Создать' }));
    expect(await screen.findByText('Такой адрес (slug) уже занят')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Создать' }));
    await waitFor(() => expect(screen.queryByText('Новая категория')).not.toBeInTheDocument());
    const posts = calls.filter((c) => c.method === 'POST');
    expect(posts).toHaveLength(2);
    // Only filled languages are sent; the server generates the slug.
    expect(posts[1].body).toEqual({
      translations: [{ language_code: 'ru', name: 'Салаты', description: null }],
      sort_order: 0,
      is_active: true,
    });
  });

  it('creates a product together with its first size', async () => {
    const created = {
      id: 'p-new',
      slug: 'margarita',
      category_id: 'cat-1',
      is_available: true,
      is_featured: false,
      sort_order: 0,
      deleted_at: null,
      translations: ru('Маргарита'),
      variants: [],
      modifier_groups: [],
      images: [],
    };
    const { calls } = mockFetchRoutes({
      'GET /api/v1/auth/me': () => jsonResponse(ME),
      'GET /api/v1/admin/categories': () => jsonResponse({ items: [CATEGORY] }),
      'GET /api/v1/admin/modifier-groups': () => jsonResponse({ items: [] }),
      'POST /api/v1/admin/products': () => jsonResponse(created, 201),
      'GET /api/v1/admin/products/p-new': () => jsonResponse(created),
    });
    const router = renderApp('/admin/products/new');

    await screen.findByRole('option', { name: 'Пицца' });
    fireEvent.change(screen.getByLabelText('Категория'), { target: { value: 'cat-1' } });
    type('Название (RU) *', 'Маргарита');
    type('Название размера (RU) *', '30 см');
    type('Цена, сом', '450,50');
    type('Артикул', 'PZ-MARG-30');
    fireEvent.click(screen.getByRole('button', { name: 'Создать' }));

    await waitFor(() => expect(router.state.location.pathname).toBe('/admin/products/p-new'));
    expect(callTo(calls, '/api/v1/admin/products').body).toMatchObject({
      category_id: 'cat-1',
      variants: [
        {
          sku: 'PZ-MARG-30',
          price: '450.50',
          translations: [{ language_code: 'ru', name: '30 см' }],
        },
      ],
    });
  });

  it('keeps a single-choice group to one option and sends the rules', async () => {
    const { calls } = mockFetchRoutes({
      'GET /api/v1/auth/me': () => jsonResponse(ME),
      'GET /api/v1/admin/modifier-groups': () => jsonResponse({ items: [SINGLE_GROUP] }),
      'POST /api/v1/admin/modifier-groups': () => jsonResponse(SINGLE_GROUP, 201),
    });
    renderApp('/admin/modifiers');

    expect(await screen.findByText('Чесночный')).toBeInTheDocument();
    expect(screen.getByText(/Один вариант, обязательно/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Добавить группу' }));
    type('Название группы (RU) *', 'Соусы');
    // A single-choice group has no min/max fields: only "required".
    expect(screen.queryByLabelText('Максимум выбрать')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox', { name: /Обязательный выбор/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Создать' }));

    await waitFor(() => expect(calls.some((c) => c.method === 'POST')).toBe(true));
    const post = calls.find((c) => c.method === 'POST');
    expect(post?.body).toMatchObject({
      selection_type: 'single',
      min_selections: 1,
      max_selections: 1,
    });
  });
});
