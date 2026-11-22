// MA-4.0: the Mini App router (basename /tg), its tabs, link safety and
// the unchanged site router (R1).
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

import { createAppRouter } from '../../app/router/createAppRouter';
import { miniAppRoutes } from '../../app/router/miniAppRoutes';
import { routes } from '../../app/router/routes';
import { AppProviders } from '../../app/providers/AppProviders';
import { makeStore } from '../../app/store/store';
import { ProductConfigurator } from '../catalog/components/ProductConfigurator';
import {
  CATEGORIES,
  MARGHERITA,
  MARGHERITA_SUMMARY,
  productList,
} from '../../test/catalogFixtures';
import { mockFetchRoutes } from '../../test/fetchRoutes';
import { BASE, CART, ORDER } from '../../test/orderFixtures';
import { jsonResponse } from '../../test/renderWithProviders';
import {
  installTelegram,
  openAt,
  uninstallTelegram,
  type FakeTelegram,
} from '../../test/telegramMock';
import { decideLink } from './linkGuard';

const TOKEN = () => jsonResponse({ access_token: 'mini', token_type: 'bearer', expires_in: 900 });
const PROFILE = () =>
  jsonResponse({
    id: 'u-1',
    email: null,
    full_name: 'Айбек',
    phone: null,
    preferred_language: 'ru',
    roles: ['customer'],
    must_change_password: false,
    has_password: false,
  });

// Every API the shopping pages call, answered with the shared fixtures.
const API = {
  ...BASE,
  'POST /api/v1/auth/telegram/webapp': TOKEN,
  'GET /api/v1/users/me': PROFILE,
  'GET /api/v1/catalog/categories': () => jsonResponse({ items: CATEGORIES }),
  'GET /api/v1/catalog/products': () => jsonResponse(productList([MARGHERITA_SUMMARY])),
  [`GET /api/v1/catalog/products/${MARGHERITA.id}`]: () => jsonResponse(MARGHERITA),
  'GET /api/v1/orders': () =>
    jsonResponse({ items: [], pagination: { page: 1, page_size: 20, total: 0, pages: 0 } }),
  [`GET /api/v1/orders/${ORDER.id}`]: () => jsonResponse(ORDER),
};

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

/** Waits for a level-1 heading that stays in the document (pages re-render
 * their heading per loading state). */
async function expectHeading(name: string | RegExp): Promise<void> {
  await waitFor(() => expect(screen.getByRole('heading', { level: 1, name })).toBeInTheDocument());
}

function childPaths(list: { path?: string; index?: boolean; children?: unknown[] }[]): string[] {
  return (list[0].children as { path?: string; index?: boolean }[]).map((r) =>
    r.index ? '<index>' : (r.path ?? ''),
  );
}

function hrefs(): string[] {
  return Array.from(document.querySelectorAll('a[href]'), (a) => a.getAttribute('href') ?? '');
}

/** No rendered link leaves /tg (external http(s) links aside). */
function expectOnlyMiniAppLinks(): void {
  for (const href of hrefs()) {
    if (/^https?:\/\//.test(href) || href.startsWith('#')) {
      continue; // external (opened with openLink) or an in-page anchor
    }
    expect(href, `link ${href}`).toMatch(/^\/tg(\/|$|\?)/);
    expect(href).not.toMatch(/^\/tg\/tg/);
  }
}

beforeEach(() => {
  fake = installTelegram();
});

afterEach(() => {
  uninstallTelegram();
  openAt('/');
});

describe('one router per mode', () => {
  it('a Mini App path gets the Mini App router under /tg', () => {
    openAt('/tg/menu');
    const router = createAppRouter();
    expect(router.basename).toBe('/tg');
    expect(childPaths(router.routes)).toEqual(childPaths(miniAppRoutes));
    router.dispose();
  });

  it.each(['/', '/menu', '/tgx', '/admin'])('%s gets the unchanged site router', (path) => {
    openAt(path);
    const router = createAppRouter();
    expect(router.basename).toBe('/');
    expect(router.routes.map((r) => r.path ?? null)).toEqual(routes.map((r) => r.path ?? null));
    expect(childPaths(router.routes)).toEqual(childPaths(routes));
    router.dispose();
  });

  it('the site router has no /tg branch any more', () => {
    const router = createMemoryRouter(routes, { initialEntries: ['/tg/menu'] });
    render(
      <AppProviders store={makeStore()}>
        <RouterProvider router={router} />
      </AppProviders>,
    );
    expect(router.state.matches.some((m) => m.route.path === 'tg')).toBe(false);
    expect(router.state.matches.at(-1)?.route.path).toBe('*'); // the site's not-found page
  });
});

describe('Mini App routes', () => {
  // The first Mini App render in a file pays a one-time cost (module JIT, the
  // first React/jsdom work; see test/setup.ts). On a loaded machine it pushed
  // the first test of this block past the 5 s wait while the app itself was
  // fine. Pay it once here, so every test measures only its own route. The
  // wait limit of the tests is unchanged; only this warm-up may take longer.
  beforeAll(async () => {
    installTelegram();
    const { spy } = mockFetchRoutes(API);
    launch('/tg/menu');
    await screen.findByRole('heading', { level: 1, name: 'Меню' }, { timeout: 30_000 });
    cleanup();
    spy.mockRestore();
    uninstallTelegram();
    openAt('/');
  }, 60_000);

  it('/tg opens the menu at /tg/menu after sign-in', async () => {
    mockFetchRoutes(API);
    const router = launch('/tg');
    await expectHeading('Меню');
    expect(router.state.location.pathname).toBe('/tg/menu');
  });

  it.each([
    ['/tg/menu', 'Меню'],
    [`/tg/menu/${MARGHERITA.id}`, MARGHERITA.name],
    ['/tg/cart', 'Корзина'],
    ['/tg/checkout', 'Оформление заказа'],
    ['/tg/orders', 'Мои заказы'],
    [`/tg/orders/${ORDER.id}/pay`, 'Оплата заказа'],
    ['/tg/account', 'Профиль'],
  ])('%s renders the shared page, with links only inside /tg', async (path, heading) => {
    mockFetchRoutes(API);
    launch(path);
    await expectHeading(heading);
    expect(screen.queryByRole('contentinfo')).not.toBeInTheDocument(); // no site footer
    expectOnlyMiniAppLinks();
  });

  it('direct open and reload of /tg/orders/:id show that order', async () => {
    const { calls } = mockFetchRoutes(API);
    launch(`/tg/orders/${ORDER.id}`);
    await expectHeading(new RegExp(String(ORDER.order_number)));
    expect(calls.some((c) => c.path === `/api/v1/orders/${ORDER.id}`)).toBe(true);
    expectOnlyMiniAppLinks();
  });

  it('a reload rebuilds the same page from the address bar', async () => {
    mockFetchRoutes(API);
    const first = launch('/tg/cart');
    await expectHeading('Корзина');
    const href = first.state.location.pathname;
    document.body.innerHTML = '';
    const second = launch(href);
    await expectHeading('Корзина');
    expect(second.state.location.pathname).toBe('/tg/cart');
  });

  it.each([
    '/tg/unknown',
    '/tg/login',
    '/tg/register',
    '/tg/forgot-password',
    '/tg/reset-password',
    '/tg/admin',
    '/tg/admin/orders',
    '/tg/courier',
    '/tg/change-password',
    '/tg/status',
  ])('%s is not a page of the Mini App', async (path) => {
    mockFetchRoutes(API);
    const router = launch(path);
    expect(await screen.findByRole('heading', { name: 'Раздел недоступен' })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe(path); // stays under /tg
  });
});

describe('bottom tabs', () => {
  it('four tabs inside /tg; the active one is marked; clicks stay in the Mini App', async () => {
    mockFetchRoutes(API);
    const router = launch('/tg/menu');
    const nav = await screen.findByRole('navigation', { name: 'Разделы Mini App' });
    const links = within(nav).getAllByRole('link');
    expect(links.map((l) => l.getAttribute('href'))).toEqual([
      '/tg/menu',
      '/tg/cart',
      '/tg/orders',
      '/tg/account',
    ]);
    expect(within(nav).getByRole('link', { name: 'Меню' })).toHaveAttribute('aria-current', 'page');

    fireEvent.click(within(nav).getByRole('link', { name: 'Заказы' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/tg/orders'));
    expect(within(nav).getByRole('link', { name: 'Заказы' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    fireEvent.click(within(nav).getByRole('link', { name: 'Профиль' }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/tg/account'));
    fireEvent.click(within(nav).getByRole('link', { name: /Корзина, товаров/ }));
    await waitFor(() => expect(router.state.location.pathname).toBe('/tg/cart'));
  });

  it('the cart tab shows the server item count', async () => {
    mockFetchRoutes(API);
    launch('/tg/menu');
    const badge = await screen.findByTestId('mini-cart-badge');
    expect(badge).toHaveTextContent(String(CART.items_count));
    expect(
      screen.getByRole('link', { name: `Корзина, товаров: ${CART.items_count}` }),
    ).toBeInTheDocument();
  });

  it('the product page keeps the tab bar above the content (room reserved)', async () => {
    mockFetchRoutes(API);
    launch(`/tg/menu/${MARGHERITA.id}`);
    await expectHeading(MARGHERITA.name);
    expect(document.getElementById('main')).toHaveClass('pb-24');
  });
});

describe('link safety', () => {
  it.each([
    ['/tg/cart', 'allow'],
    ['/tg', 'allow'],
    ['/login', 'block'],
    ['/admin/orders', 'block'],
    ['/courier', 'block'],
    ['/', 'block'],
    ['https://www.openstreetmap.org/copyright', 'external'],
    ['tel:+996700123456', 'allow'],
    ['javascript:alert(1)', 'allow'],
  ])('%s -> %s', (href, decision) => {
    expect(decideLink(href, 'http://localhost:3000')).toBe(decision);
  });

  it('a plain anchor to a site page is blocked, an external one opens with openLink', async () => {
    const openLink = (fake.app.openLink = vi.fn());
    mockFetchRoutes(API);
    const router = launch('/tg/account');
    await screen.findByRole('heading', { name: 'Профиль' });
    const main = document.getElementById('main')!;
    const site = document.createElement('a');
    site.href = '/login';
    site.textContent = 'site';
    const external = document.createElement('a');
    external.href = 'https://www.openstreetmap.org/copyright';
    external.textContent = 'osm';
    main.append(site, external);

    const siteClick = new MouseEvent('click', { bubbles: true, cancelable: true });
    site.dispatchEvent(siteClick);
    expect(siteClick.defaultPrevented).toBe(true);
    const externalClick = new MouseEvent('click', { bubbles: true, cancelable: true });
    external.dispatchEvent(externalClick);
    expect(externalClick.defaultPrevented).toBe(true);
    expect(openLink).toHaveBeenCalledWith('https://www.openstreetmap.org/copyright');
    expect(router.state.location.pathname).toBe('/tg/account');
  });
});

describe('case E: ProductConfigurator for a guest', () => {
  function renderConfigurator(telegramActive: boolean) {
    const store = makeStore({
      auth: { accessToken: null, status: 'anonymous', passwordChangeRequired: false },
      telegram: { active: telegramActive, phase: telegramActive ? 'restart' : 'idle', attempt: 0 },
    });
    const router = createMemoryRouter(
      [
        { path: '/menu/:id', element: <ProductConfigurator product={MARGHERITA} /> },
        { path: '/login', element: <p>site login</p> },
      ],
      { initialEntries: [`/menu/${MARGHERITA.id}`] },
    );
    openAt(telegramActive ? '/tg/menu' : '/menu');
    render(
      <AppProviders store={store}>
        <RouterProvider router={router} />
      </AppProviders>,
    );
    return router;
  }

  it('in the Mini App never goes to the site login', async () => {
    mockFetchRoutes({});
    const router = renderConfigurator(true);
    const add = await screen.findByRole('button', { name: /в корзину/i });
    await act(async () => {
      fireEvent.click(add);
    });
    expect(router.state.location.pathname).toBe(`/menu/${MARGHERITA.id}`);
    expect(screen.queryByText('site login')).not.toBeInTheDocument();
  });

  it('on the site still sends the guest to /login and back (unchanged)', async () => {
    mockFetchRoutes({ 'POST /api/v1/auth/refresh': () => new Response(null, { status: 401 }) });
    const router = renderConfigurator(false);
    const add = await screen.findByRole('button', { name: /в корзину/i });
    fireEvent.click(add);
    await waitFor(() => expect(router.state.location.pathname).toBe('/login'));
    expect(router.state.location.search).toContain(encodeURIComponent(`/menu/${MARGHERITA.id}`));
  });
});
