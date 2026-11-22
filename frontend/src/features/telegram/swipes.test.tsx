// MA-4.3.3: vertical swipes of the Mini App are off only while the delivery
// map is mounted (DEC-152 п. 11) and restored afterwards. The real DeliveryMap
// is rendered; only react-leaflet is replaced (Leaflet needs a real browser).
// Only the mocked API is used; no order is created anywhere.
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { Provider } from 'react-redux';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AppProviders } from '../../app/providers/AppProviders';
import { miniAppRoutes } from '../../app/router/miniAppRoutes';
import { makeStore } from '../../app/store/store';
import { DeliveryMap } from '../checkout/components/DeliveryMap';
import { mockFetchRoutes } from '../../test/fetchRoutes';
import { BASE, DELIVERY_QUOTE, quote } from '../../test/orderFixtures';
import { jsonResponse } from '../../test/renderWithProviders';
import {
  installTelegram,
  openAt,
  uninstallTelegram,
  type FakeTelegram,
} from '../../test/telegramMock';
import { telegramStarted } from './telegramSlice';

vi.mock('react-leaflet', () => ({
  MapContainer: ({ children }: { children?: ReactNode }) => (
    <div data-testid="leaflet-map">{children}</div>
  ),
  TileLayer: () => null,
  CircleMarker: () => null,
  useMap: () => ({ panTo: () => undefined }),
  useMapEvents: () => null,
}));

let fake: FakeTelegram;

function Maps({ count }: { count: number }) {
  return (
    <>
      {Array.from({ length: count }, (_, index) => (
        <DeliveryMap key={index} point={null} onPick={() => undefined} />
      ))}
    </>
  );
}

/** Renders `count` real DeliveryMaps; miniApp=false is the site (no Mini App session). */
function renderMaps(count: number, { miniApp = true } = {}) {
  const store = makeStore();
  if (miniApp) {
    store.dispatch(telegramStarted());
  }
  const view = render(
    <Provider store={store}>
      <Maps count={count} />
    </Provider>,
  );
  return {
    setCount: (next: number) =>
      view.rerender(
        <Provider store={store}>
          <Maps count={next} />
        </Provider>,
      ),
    unmount: view.unmount,
  };
}

afterEach(() => {
  uninstallTelegram();
  openAt('/');
});

describe('vertical swipes around the delivery map', () => {
  beforeEach(() => {
    fake = installTelegram(); // version 8.0, swipes enabled
  });

  it('7.7+ with swipes on: off while the map is mounted, restored after unmount', () => {
    const view = renderMaps(1);
    expect(screen.getByTestId('leaflet-map')).toBeInTheDocument();
    expect(fake.app.disableVerticalSwipes).toHaveBeenCalledTimes(1);
    expect(fake.swipes.enabled).toBe(false);

    view.unmount();
    expect(fake.app.enableVerticalSwipes).toHaveBeenCalledTimes(1);
    expect(fake.swipes.enabled).toBe(true);
  });

  it('several maps: one switch-off, restored only when the last one goes', () => {
    const view = renderMaps(2);
    expect(fake.app.disableVerticalSwipes).toHaveBeenCalledTimes(1);
    expect(fake.swipes.enabled).toBe(false);

    view.setCount(1);
    expect(fake.app.enableVerticalSwipes).not.toHaveBeenCalled();
    expect(fake.swipes.enabled).toBe(false);

    view.setCount(0);
    expect(fake.app.enableVerticalSwipes).toHaveBeenCalledTimes(1);
    expect(fake.swipes.enabled).toBe(true);
  });

  it('mount → unmount → mount again: off again, restored again', () => {
    const view = renderMaps(1);
    view.setCount(0);
    expect(fake.swipes.enabled).toBe(true);
    view.setCount(1);
    expect(fake.app.disableVerticalSwipes).toHaveBeenCalledTimes(2);
    expect(fake.swipes.enabled).toBe(false);
    view.setCount(0);
    expect(fake.app.enableVerticalSwipes).toHaveBeenCalledTimes(2);
    expect(fake.swipes.enabled).toBe(true);
  });
});

describe('when the swipes are left alone', () => {
  it('initial state false: not touched, and not switched on after the map', () => {
    fake = installTelegram({ verticalSwipesEnabled: false });
    const view = renderMaps(1);
    view.unmount();
    expect(fake.app.disableVerticalSwipes).not.toHaveBeenCalled();
    expect(fake.app.enableVerticalSwipes).not.toHaveBeenCalled();
    expect(fake.swipes.enabled).toBe(false);
  });

  it.each([
    ['undefined', undefined],
    ['a string', 'yes'],
    ['a number', 1],
  ])('unknown initial state (%s): nothing is changed', (_name, value) => {
    fake = installTelegram({ verticalSwipesEnabled: value });
    const view = renderMaps(1);
    view.unmount();
    expect(fake.app.disableVerticalSwipes).not.toHaveBeenCalled();
    expect(fake.app.enableVerticalSwipes).not.toHaveBeenCalled();
    expect(fake.swipes.enabled).toBe(value);
  });

  it('a client below Bot API 7.7: the methods are not called', () => {
    fake = installTelegram({ version: '7.6' });
    const view = renderMaps(1);
    view.unmount();
    expect(fake.app.disableVerticalSwipes).not.toHaveBeenCalled();
    expect(fake.app.enableVerticalSwipes).not.toHaveBeenCalled();
    expect(fake.swipes.enabled).toBe(true);
  });

  it('a client without the methods: nothing fails, the state is unchanged', () => {
    fake = installTelegram({ swipeMethods: false });
    expect(fake.app.disableVerticalSwipes).toBeUndefined();
    const view = renderMaps(1);
    expect(screen.getByTestId('leaflet-map')).toBeInTheDocument();
    view.unmount();
    expect(fake.swipes.enabled).toBe(true);
  });

  it('the site (no Mini App session): the methods are never called', () => {
    fake = installTelegram(); // even with a Telegram object on the page
    const view = renderMaps(1, { miniApp: false });
    view.unmount();
    expect(fake.app.disableVerticalSwipes).not.toHaveBeenCalled();
    expect(fake.app.enableVerticalSwipes).not.toHaveBeenCalled();
    expect(fake.swipes.enabled).toBe(true);
  });
});

// ---------------- the map on /tg/checkout ----------------

const API = {
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
  'POST /api/v1/checkout/quote': ({ body }: { body: unknown }) =>
    jsonResponse(
      (body as { delivery_type: string }).delivery_type === 'pickup' ? quote() : DELIVERY_QUOTE,
    ),
};

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

describe('the map on /tg/checkout', () => {
  beforeEach(() => {
    fake = installTelegram();
  });

  it('follows the map: delivery → pickup → delivery → leaving the page', async () => {
    mockFetchRoutes(API);
    const router = launch('/tg/checkout');

    // Delivery with a new address (no saved addresses): the map is shown.
    expect(await screen.findByTestId('leaflet-map')).toBeInTheDocument();
    await waitFor(() => expect(fake.swipes.enabled).toBe(false));

    fireEvent.click(screen.getByRole('radio', { name: /Самовывоз/ }));
    await waitFor(() => expect(screen.queryByTestId('leaflet-map')).not.toBeInTheDocument());
    expect(fake.swipes.enabled).toBe(true);

    fireEvent.click(screen.getByRole('radio', { name: /Доставка/ }));
    expect(await screen.findByTestId('leaflet-map')).toBeInTheDocument();
    await waitFor(() => expect(fake.swipes.enabled).toBe(false));

    act(() => fake.backButton.click());
    await waitFor(() => expect(router.state.location.pathname).toBe('/tg/menu'));
    await waitFor(() => expect(fake.swipes.enabled).toBe(true));
    expect(fake.app.disableVerticalSwipes).toHaveBeenCalledTimes(2);
    expect(fake.app.enableVerticalSwipes).toHaveBeenCalledTimes(2);
  });
});
