import { RouterProvider } from 'react-router';

import { createAppRouter } from './createAppRouter';

// Created once, when the module loads: the path of the opened page decides
// which single router exists (site or Mini App).
const router = createAppRouter();

export function AppRouter() {
  return <RouterProvider router={router} />;
}
