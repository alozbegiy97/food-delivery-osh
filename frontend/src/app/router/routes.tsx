import { type RouteObject } from 'react-router';

import {
  AdminLayout,
  RequireAdmin,
  RequireStaff,
  StaffHome,
} from '../../features/admin/components/AdminLayout';

import { RequireAuth } from '../../features/auth/components/SessionGate';
import { CourierLayout } from '../../features/courier/components/CourierLayout';
import { AccountPage } from '../../pages/account/AccountPage';
import { AdminCancellationsPage } from '../../pages/admin/AdminCancellationsPage';
import { AdminCategoriesPage } from '../../pages/admin/AdminCategoriesPage';
import { AdminCouriersPage } from '../../pages/admin/AdminCouriersPage';
import { AdminDashboardPage } from '../../pages/admin/AdminDashboardPage';
import { AdminModifiersPage } from '../../pages/admin/AdminModifiersPage';
import { AdminProductEditPage } from '../../pages/admin/AdminProductEditPage';
import { AdminOrderDetailPage } from '../../pages/admin/AdminOrderDetailPage';
import { AdminOrdersPage } from '../../pages/admin/AdminOrdersPage';
import { AdminProductsPage } from '../../pages/admin/AdminProductsPage';
import { AdminSettingsPage } from '../../pages/admin/AdminSettingsPage';
import { AdminStaffPage } from '../../pages/admin/AdminStaffPage';
import { AdminZonesPage } from '../../pages/admin/AdminZonesPage';
import { KitchenPage } from '../../pages/admin/KitchenPage';
import { ChangePasswordPage } from '../../pages/auth/ChangePasswordPage';
import { CartPage } from '../../pages/cart/CartPage';
import { CheckoutPage } from '../../pages/checkout/CheckoutPage';
import { CourierHistoryPage } from '../../pages/courier/CourierHistoryPage';
import { CourierHomePage } from '../../pages/courier/CourierHomePage';
import { CourierOrderPage } from '../../pages/courier/CourierOrderPage';
import { ForgotPasswordPage } from '../../pages/auth/ForgotPasswordPage';
import { LoginPage } from '../../pages/auth/LoginPage';
import { RegisterPage } from '../../pages/auth/RegisterPage';
import { ResetPasswordPage } from '../../pages/auth/ResetPasswordPage';
import { HomePage } from '../../pages/home/HomePage';
import { MenuPage } from '../../pages/menu/MenuPage';
import { NotFoundPage } from '../../pages/not-found/NotFoundPage';
import { OrderDetailPage } from '../../pages/orders/OrderDetailPage';
import { OrdersPage } from '../../pages/orders/OrdersPage';
import { PayPage } from '../../pages/orders/PayPage';
import { ProductPage } from '../../pages/product/ProductPage';
import { SystemStatusPage } from '../../pages/system-status/SystemStatusPage';
import { RootLayout } from '../layouts/RootLayout';

export const routes: RouteObject[] = [
  {
    element: <RootLayout />,
    children: [
      { index: true, element: <HomePage /> },
      { path: 'menu', element: <MenuPage /> },
      { path: 'menu/:productId', element: <ProductPage /> },
      // Technical page of stage 1 (API, database, PostGIS); not linked in navigation.
      { path: 'status', element: <SystemStatusPage /> },
      { path: 'login', element: <LoginPage /> },
      { path: 'register', element: <RegisterPage /> },
      { path: 'forgot-password', element: <ForgotPasswordPage /> },
      { path: 'reset-password', element: <ResetPasswordPage /> },
      {
        path: 'change-password',
        element: (
          <RequireAuth>
            <ChangePasswordPage />
          </RequireAuth>
        ),
      },
      {
        // Server cart (stage 5); guests are sent to /login and come back.
        path: 'cart',
        element: (
          <RequireAuth>
            <CartPage />
          </RequireAuth>
        ),
      },
      {
        // Checkout and the customer's orders (stage 6).
        path: 'checkout',
        element: (
          <RequireAuth>
            <CheckoutPage />
          </RequireAuth>
        ),
      },
      {
        path: 'orders',
        element: (
          <RequireAuth>
            <OrdersPage />
          </RequireAuth>
        ),
      },
      {
        path: 'orders/:orderId',
        element: (
          <RequireAuth>
            <OrderDetailPage />
          </RequireAuth>
        ),
      },
      {
        // Demonstration card payment (stage 7, DEC-149).
        path: 'orders/:orderId/pay',
        element: (
          <RequireAuth>
            <PayPage />
          </RequireAuth>
        ),
      },
      {
        path: 'account',
        element: (
          <RequireAuth>
            <AccountPage />
          </RequireAuth>
        ),
      },
      {
        // Staff area (stages 4B, 8): admin sees everything, the cook only the
        // kitchen (DEC-150). Every API checks the roles again on the backend.
        path: 'admin',
        element: (
          <RequireAuth>
            <RequireStaff roles={['admin', 'cook']}>
              <AdminLayout />
            </RequireStaff>
          </RequireAuth>
        ),
        children: [
          { index: true, element: <StaffHome /> },
          {
            path: 'kitchen',
            element: (
              <RequireStaff roles={['admin', 'cook']}>
                <KitchenPage />
              </RequireStaff>
            ),
          },
          ...(
            [
              ['dashboard', <AdminDashboardPage />],
              ['orders', <AdminOrdersPage />],
              ['orders/:orderId', <AdminOrderDetailPage />],
              ['cancellations', <AdminCancellationsPage />],
              ['couriers', <AdminCouriersPage />],
              ['staff', <AdminStaffPage />],
              ['zones', <AdminZonesPage />],
              ['settings', <AdminSettingsPage />],
              ['categories', <AdminCategoriesPage />],
              ['products', <AdminProductsPage />],
              ['products/new', <AdminProductEditPage />],
              ['products/:productId', <AdminProductEditPage />],
              ['modifiers', <AdminModifiersPage />],
            ] as const
          ).map(([path, page]) => ({ path, element: <RequireAdmin>{page}</RequireAdmin> })),
        ],
      },
      {
        // Separate mobile courier cabinet (stage 9, DEC-151 п. 9); the API
        // checks the role and the ownership of every assignment.
        path: 'courier',
        element: (
          <RequireAuth>
            <RequireStaff roles={['courier']}>
              <CourierLayout />
            </RequireStaff>
          </RequireAuth>
        ),
        children: [
          { index: true, element: <CourierHomePage /> },
          { path: 'orders/:orderId', element: <CourierOrderPage /> },
          { path: 'history', element: <CourierHistoryPage /> },
        ],
      },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
];
