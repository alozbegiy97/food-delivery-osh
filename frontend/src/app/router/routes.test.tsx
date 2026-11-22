import { render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { describe, expect, it } from 'vitest';

import { AppProviders } from '../providers/AppProviders';
import { makeStore } from '../store/store';
import { ANONYMOUS } from '../../test/renderWithProviders';
import { routes } from './routes';

describe('routes', () => {
  it('renders the not-found page for unknown paths', () => {
    const router = createMemoryRouter(routes, { initialEntries: ['/no-such-page'] });

    render(
      <AppProviders store={makeStore({ auth: ANONYMOUS })}>
        <RouterProvider router={router} />
      </AppProviders>,
    );

    expect(screen.getByRole('heading', { name: 'Страница не найдена' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'На главную' })).toHaveAttribute('href', '/');
  });
});
