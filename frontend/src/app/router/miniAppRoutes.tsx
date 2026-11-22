import { Navigate, type RouteObject } from 'react-router';

import { TelegramLayout } from '../../features/telegram/components/TelegramLayout';
import { CartPage } from '../../pages/cart/CartPage';
import { CheckoutPage } from '../../pages/checkout/CheckoutPage';
import { MenuPage } from '../../pages/menu/MenuPage';
import { OrderDetailPage } from '../../pages/orders/OrderDetailPage';
import { OrdersPage } from '../../pages/orders/OrdersPage';
import { PayPage } from '../../pages/orders/PayPage';
import { ProductPage } from '../../pages/product/ProductPage';
import { TelegramNotFoundPage } from '../../pages/telegram/TelegramEntryPage';
import { TelegramProfilePage } from '../../pages/telegram/TelegramProfilePage';
import { MINI_APP_START } from '../../shared/lib/miniAppMode';

/**
 * Routes of the Telegram Mini App (DEC-152 п. 1, MA-4.0 / R1). They are
 * mounted with `basename: '/tg'`, so the paths here are written without
 * the prefix and the shared pages' absolute links (`/cart`, `/menu/:id`,
 * `/orders/:id/pay`, …) resolve to `/tg/…` by themselves. The pages are the
 * site's own components — no copies. Site-only routes (login, register,
 * password pages, admin, courier, the site account) do not exist here, so
 * any such path ends on the Mini App "not found" screen.
 *
 * Every page waits for the Telegram session (RequireTelegramSession in the
 * layout); there is no RequireAuth and no redirect to /login.
 */
export const miniAppRoutes: RouteObject[] = [
  {
    element: <TelegramLayout />,
    children: [
      { index: true, element: <Navigate to={MINI_APP_START} replace /> },
      { path: 'menu', element: <MenuPage /> },
      { path: 'menu/:productId', element: <ProductPage /> },
      { path: 'cart', element: <CartPage /> },
      { path: 'checkout', element: <CheckoutPage /> },
      { path: 'orders', element: <OrdersPage /> },
      { path: 'orders/:orderId', element: <OrderDetailPage /> },
      { path: 'orders/:orderId/pay', element: <PayPage /> },
      // The Mini App's own profile page, not the site's (DEC-160 п. 1).
      { path: 'account', element: <TelegramProfilePage /> },
      { path: '*', element: <TelegramNotFoundPage /> },
    ],
  },
];
